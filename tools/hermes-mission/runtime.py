"""Central Hermes mission log and the two owner-facing projections.

This module is copied into the pinned Hermes checkout by ``apply_overlay.py``.
It intentionally uses only the Python standard library already present in
Hermes: SQLite is the authority, Workspace receives the structured view, and
Telegram renders that same view as compact text.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable


SCHEMA_VERSION = 1
STAGES = (
    "accepted",
    "planning",
    "implementing",
    "testing",
    "reviewing",
    "delivering",
    "verifying",
    "complete",
)
TERMINAL_TYPES = {"mission.completed", "mission.failed", "mission.cancelled"}
NOTIFY_TYPES = {"mission.stage", "mission.question", "mission.answer", *TERMINAL_TYPES}
REQUIRED_PAYLOAD = {
    "mission.accepted": {"goal"},
    "mission.stage": {"stage", "progress_percent"},
    "mission.question": {"question_id", "text"},
    "mission.answer": {"question_id", "text"},
    "task.upsert": {"task_id", "title", "status"},
    "worker.upsert": {"worker_id", "status"},
    "terminal.append": {"stream", "text"},
    "change.upsert": {"path", "status"},
    "gate.upsert": {"gate_id", "status"},
    "delivery.upsert": {"kind", "status", "url"},
    "mission.completed": {"result"},
    "mission.failed": {"error"},
    "mission.cancelled": {"reason"},
}
PAYLOAD_FIELDS = {
    **REQUIRED_PAYLOAD,
    "mission.accepted": {"goal", "dispatch_profile", "parent_mission_id"},
    "task.upsert": {"task_id", "title", "status", "assignee"},
    "worker.upsert": {"worker_id", "status", "run_id", "profile"},
    "terminal.append": {"stream", "text", "offset"},
}
CORRELATION_FIELDS = {"session_id", "run_id", "task_id", "worker_id", "producer_event_id"}
PRODUCER_TYPES = set(REQUIRED_PAYLOAD) - {
    "mission.accepted", "mission.answer", *TERMINAL_TYPES,
}
_EVENT_FIELDS = {"schema_version", "mission_id", "type", "source", "correlation", "payload"}
_NULLABLE_PAYLOAD = {("task.upsert", "assignee"), ("worker.upsert", "profile")}
_ID_PAYLOAD_FIELDS = {
    "assignee", "dispatch_profile", "gate_id", "kind", "parent_mission_id", "profile", "question_id",
    "run_id", "status", "stream", "task_id", "worker_id",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_EVENT_JSON = 65_536
_MAX_TERMINAL_ENTRIES = 200
_MAX_TERMINAL_CHARS = 65_536
_MAX_OWNER_ANSWER_CHARS = 4_000
_MAX_RETAINED_TERMINAL_MISSIONS = 100
_COMPLETION_GATES = {"tests", "review", "ci", "post-verify", "cleanup"}
_COMPLETION_DELIVERIES = {
    "pull_request": "merged",
    "default_branch": "verified",
}
NOTIFICATION_SEND_TIMEOUT_SECONDS = 240
# ponytail: lease exceeds the bounded send; a crash releases binding after five minutes.
_NOTIFICATION_LEASE_SECONDS = 300


class MissionError(ValueError):
    """A mission request violated the v1 contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _require_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise MissionError(f"invalid {name}")
    return text


def _validate_submission(mission_id: str, submission: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(submission, dict)
        or isinstance(submission.get("schema_version"), bool)
        or submission.get("schema_version") != SCHEMA_VERSION
    ):
        raise MissionError("invalid mission event version")
    if unknown := set(submission) - _EVENT_FIELDS:
        raise MissionError(f"unknown mission event fields: {', '.join(sorted(unknown))}")
    if submission.get("mission_id") != mission_id:
        raise MissionError("mission event identity mismatch")
    event_type = str(submission.get("type") or "").strip()
    source = str(submission.get("source") or "").strip()
    correlation = submission.get("correlation", {})
    payload = submission.get("payload", {})
    if not event_type or len(event_type) > 64 or not source or len(source) > 64:
        raise MissionError("invalid mission event type/source")
    if event_type not in REQUIRED_PAYLOAD:
        raise MissionError("unsupported mission event type")
    if not isinstance(correlation, dict) or not isinstance(payload, dict):
        raise MissionError("correlation and payload must be objects")
    if unknown := set(correlation) - CORRELATION_FIELDS:
        raise MissionError(f"unknown correlation fields: {', '.join(sorted(unknown))}")
    if unknown := set(payload) - PAYLOAD_FIELDS[event_type]:
        raise MissionError(f"unknown payload fields: {', '.join(sorted(unknown))}")
    missing = REQUIRED_PAYLOAD[event_type] - payload.keys()
    if missing:
        raise MissionError(f"missing payload fields: {', '.join(sorted(missing))}")
    for name, value in correlation.items():
        _require_id(value, f"correlation.{name}")
    for name, value in payload.items():
        if value is None and (event_type, name) in _NULLABLE_PAYLOAD:
            continue
        if name == "progress_percent":
            continue
        if name == "offset":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MissionError("invalid payload.offset")
            continue
        if not isinstance(value, str) or not value.strip():
            raise MissionError(f"invalid payload.{name}")
        if name in _ID_PAYLOAD_FIELDS:
            _require_id(value, f"payload.{name}")
    if event_type == "mission.stage":
        if payload.get("stage") not in STAGES:
            raise MissionError("invalid mission stage")
        progress = payload.get("progress_percent")
        if not isinstance(progress, int) or isinstance(progress, bool) or not 0 <= progress <= 100:
            raise MissionError("invalid mission progress")
    if event_type == "mission.accepted" and "dispatch_profile" in payload:
        _require_id(payload.get("dispatch_profile"), "dispatch_profile")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "type": event_type,
        "source": source,
        "correlation": correlation,
        "payload": payload,
    }
    if len(_json(normalized).encode("utf-8")) > _MAX_EVENT_JSON:
        raise MissionError("mission event too large")
    return normalized


def _producer_submission(mission_id: str, submission: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_submission(mission_id, submission)
    if normalized["type"] not in PRODUCER_TYPES or normalized["source"] != "build1-flow":
        raise MissionError("producer cannot publish this mission event")
    _require_id(normalized["correlation"].get("producer_event_id"), "producer_event_id")
    return normalized


def sanitize_producer_submission(
    mission_id: str,
    submission: dict[str, Any],
    redactor: Callable[[str], str],
) -> dict[str, Any]:
    """Validate the closed producer schema and protect every producer string."""
    normalized = _producer_submission(mission_id, submission)
    for group in ("correlation", "payload"):
        normalized[group] = dict(normalized[group])
        for name, value in normalized[group].items():
            if isinstance(value, str):
                redacted = redactor(value)
                if not isinstance(redacted, str):
                    raise MissionError("producer redactor returned a non-string")
                if group == "correlation" and name == "producer_event_id":
                    if redacted != value:
                        raise MissionError("sensitive producer_event_id is not allowed")
                    continue
                normalized[group][name] = redacted
    return _producer_submission(mission_id, normalized)


def empty_projection() -> dict[str, Any]:
    return {
        "mission_id": None,
        "sequence": 0,
        "status": None,
        "stage": None,
        "progress_percent": 0,
        "goal": None,
        "dispatch_profile": None,
        "parent_mission_id": None,
        "question": None,
        "answer": None,
        "result": None,
        "error": None,
        "tasks": [],
        "workers": [],
        "terminal": [],
        "changes": [],
        "gates": [],
        "deliveries": [],
    }


def project(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce one ordered log. Unknown event types are retained by SQLite but ignored here."""
    view = empty_projection()
    tasks: OrderedDict[str, dict[str, Any]] = OrderedDict()
    workers: OrderedDict[str, dict[str, Any]] = OrderedDict()
    changes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    gates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    deliveries: OrderedDict[str, dict[str, Any]] = OrderedDict()
    terminal: list[dict[str, Any]] = []
    expected = 1
    terminal_chars = 0

    for event in events:
        if event.get("sequence") != expected:
            raise MissionError("mission event sequence gap")
        expected += 1
        if view["mission_id"] not in (None, event.get("mission_id")):
            raise MissionError("projection mission mismatch")
        view["mission_id"] = event["mission_id"]
        view["sequence"] = event["sequence"]
        kind, payload = event["type"], event["payload"]
        if kind == "mission.accepted":
            view.update(
                status="active",
                stage="accepted",
                goal=payload["goal"],
                dispatch_profile=payload.get("dispatch_profile"),
                parent_mission_id=payload.get("parent_mission_id"),
            )
        elif kind == "mission.stage":
            progress = payload["progress_percent"]
            if progress < view["progress_percent"]:
                raise MissionError("mission progress decreased")
            view.update(stage=payload["stage"], progress_percent=progress)
            if view.get("question") is None:
                view["status"] = "active"
        elif kind == "mission.question":
            view.update(
                status="waiting_owner",
                question={"question_id": payload["question_id"], "text": payload["text"]},
                answer=None,
            )
        elif kind == "mission.answer":
            question = view.get("question")
            if (
                view.get("status") != "waiting_owner"
                or not isinstance(question, dict)
                or question.get("question_id") != payload["question_id"]
            ):
                raise MissionError("mission answer does not match the open question")
            view.update(status="active", question=None, answer=dict(payload))
        elif kind == "task.upsert":
            tasks[str(payload["task_id"])] = dict(payload)
        elif kind == "worker.upsert":
            workers[str(payload["worker_id"])] = dict(payload)
        elif kind == "terminal.append":
            text = str(payload["text"])
            entry = {"sequence": event["sequence"], "stream": payload["stream"], "text": text}
            terminal.append(entry)
            terminal_chars += len(text)
            while len(terminal) > _MAX_TERMINAL_ENTRIES or terminal_chars > _MAX_TERMINAL_CHARS:
                terminal_chars -= len(terminal.pop(0)["text"])
        elif kind == "change.upsert":
            changes[str(payload["path"])] = dict(payload)
        elif kind == "gate.upsert":
            gates[str(payload["gate_id"])] = dict(payload)
        elif kind == "delivery.upsert":
            deliveries[str(payload["kind"])] = dict(payload)
        elif kind == "mission.completed":
            view.update(status="completed", stage="complete", progress_percent=100, result=payload["result"])
        elif kind == "mission.failed":
            view.update(status="failed", error=payload["error"])
        elif kind == "mission.cancelled":
            view.update(status="cancelled", error=payload["reason"])

    view.update(
        tasks=list(tasks.values()),
        workers=list(workers.values()),
        terminal=terminal,
        changes=list(changes.values()),
        gates=list(gates.values()),
        deliveries=list(deliveries.values()),
    )
    stable = {key: value for key, value in view.items() if key != "projection_id"}
    view["projection_id"] = hashlib.sha256(_json(stable).encode("utf-8")).hexdigest()[:16]
    return view


def telegram_text(view: dict[str, Any]) -> str:
    """Render the compact Telegram view from the exact Workspace projection."""
    status = view.get("status") or "unknown"
    stage = view.get("stage") or "unknown"
    lines = [
        f"Mission {view.get('mission_id') or 'unknown'}",
        f"{stage} · {view.get('progress_percent', 0)}% · {status}",
    ]
    if view.get("question"):
        lines.append(f"Question: {view['question']['text']}")
    if view.get("answer"):
        lines.append(f"Answer received: {view['answer']['text']}")
    if view.get("result"):
        lines.append(f"Result: {view['result']}")
    if view.get("error"):
        lines.append(f"Error: {view['error']}")
    lines.append(
        "Tasks {tasks} · Workers {workers} · Gates {gates} · Deliveries {deliveries}".format(
            tasks=len(view.get("tasks", [])),
            workers=len(view.get("workers", [])),
            gates=len(view.get("gates", [])),
            deliveries=len(view.get("deliveries", [])),
        )
    )
    return "\n".join(lines)


def completion_ready(
    view: dict[str, Any], *, telegram_terminal_ready: bool = False
) -> bool:
    """Apply the narrow A7.3 one-task delivery completion policy."""
    if (
        not telegram_terminal_ready
        or view.get("status") != "active"
        or view.get("question") is not None
    ):
        return False
    tasks = view.get("tasks")
    workers = view.get("workers")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or tasks[0].get("status") not in {"done", "archived"}
        or not isinstance(workers, list)
        or len(workers) != 1
        or workers[0].get("status") not in {"success", "completed"}
    ):
        return False
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    if any(gates.get(gate_id) != "passed" for gate_id in _COMPLETION_GATES):
        return False
    deliveries = {
        item.get("kind"): item.get("status")
        for item in view.get("deliveries", [])
        if isinstance(item, dict)
    }
    return all(
        deliveries.get(kind) == status
        for kind, status in _COMPLETION_DELIVERIES.items()
    )


def rejection_ready(view: dict[str, Any]) -> bool:
    """Apply the narrow A7.3 exhausted-cycle failure policy."""
    if (
        view.get("status") != "active"
        or view.get("question") is not None
    ):
        return False
    tasks = view.get("tasks")
    workers = view.get("workers")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or tasks[0].get("status") not in {"done", "archived"}
        or not isinstance(workers, list)
        or len(workers) != 1
        or workers[0].get("status") != "completed"
    ):
        return False
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    deliveries = {
        item.get("kind"): item.get("status")
        for item in view.get("deliveries", [])
        if isinstance(item, dict)
    }
    if gates in (
        {"tests": "passed", "review": "failed", "cleanup": "passed"},
        {"tests": "failed", "cleanup": "passed"},
    ):
        return not deliveries or deliveries == {"pull_request": "failed"}
    if gates == {
        "tests": "passed", "review": "passed", "ci": "failed", "cleanup": "passed",
    }:
        return deliveries == {"pull_request": "failed"}
    return gates == {
        "tests": "passed", "review": "passed", "ci": "passed",
        "post-verify": "failed", "cleanup": "passed",
    } and deliveries == {"pull_request": "merged"}


def _rejection_terminal(view: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    if not rejection_ready(view):
        return None
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    if gates.get("tests") == "failed":
        return "central:auto-author-checks-failed:v1", {
            "error": "Author checks failed after the approved cycle limit",
        }
    if gates.get("post-verify") == "failed":
        return "central:auto-post-verify-failed:v1", {
            "error": "Post-verify failed after the approved repair mission",
        }
    if gates.get("ci") == "failed":
        return "central:auto-ci-failed:v1", {
            "error": "Required CI failed after the approved cycle limit",
        }
    return "central:auto-review-rejected:v1", {
        "error": "Independent review rejected the candidate",
    }


class MissionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
            self.path.touch(mode=0o600, exist_ok=True)
            os.chmod(self.path, 0o600)
        self._init_schema()

    def _harden_permissions(self) -> None:
        if os.name != "posix":
            return
        os.chmod(self.path.parent, 0o700)
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
        ):
            if candidate.exists():
                os.chmod(candidate, 0o600)

    @classmethod
    def default(cls) -> "MissionStore":
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        return cls(home / "missions-v1.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        self._harden_permissions()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_permissions()

    def _init_schema(self) -> None:
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mission_events (
                    mission_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    producer_event_id TEXT,
                    PRIMARY KEY (mission_id, sequence),
                    UNIQUE (mission_id, event_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS mission_producer_event
                    ON mission_events(mission_id, producer_event_id)
                    WHERE producer_event_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS mission_tombstones (
                    mission_id TEXT PRIMARY KEY,
                    pruned_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_subscriptions (
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    last_notified_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease TEXT,
                    notification_lease_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease_until REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (platform, chat_id, thread_id)
                );
                CREATE TABLE IF NOT EXISTS mission_subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    previous_mission_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    related_mission_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    UNIQUE (
                        platform, chat_id, thread_id, previous_mission_id,
                        mission_id, reason, related_mission_id
                    )
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(mission_subscriptions)")
            }
            if "notification_lease" not in columns:
                connection.execute(
                    "ALTER TABLE mission_subscriptions ADD COLUMN notification_lease TEXT"
                )
            if "notification_lease_sequence" not in columns:
                connection.execute(
                    """ALTER TABLE mission_subscriptions
                       ADD COLUMN notification_lease_sequence INTEGER NOT NULL DEFAULT 0"""
                )
            if "notification_lease_until" not in columns:
                connection.execute(
                    """ALTER TABLE mission_subscriptions
                       ADD COLUMN notification_lease_until REAL NOT NULL DEFAULT 0"""
                )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission_id": row["mission_id"],
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "occurred_at": row["occurred_at"],
            "type": row["type"],
            "source": row["source"],
            "correlation": json.loads(row["correlation_json"]),
            "payload": json.loads(row["payload_json"]),
        }

    def events(self, mission_id: str, after: int = 0) -> list[dict[str, Any]]:
        mission_id = _require_id(mission_id, "mission_id")
        if not isinstance(after, int) or after < 0:
            raise MissionError("invalid mission cursor")
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? AND sequence > ? ORDER BY sequence",
                (mission_id, after),
            ).fetchall()
        return [self._row(row) for row in rows]

    def projection(self, mission_id: str) -> dict[str, Any]:
        events = self.events(mission_id)
        if not events:
            raise MissionError("mission not found")
        return project(events)

    def workspace_payload(self, mission_id: str, after: int = 0) -> dict[str, Any]:
        view = self.projection(mission_id)
        return {
            "mission": view,
            "events": self.events(mission_id, after),
            "cursor": view["sequence"],
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._db() as connection:
            rows = connection.execute(
                """SELECT mission_id, MAX(rowid) AS last_row
                   FROM mission_events GROUP BY mission_id
                   ORDER BY last_row DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self.projection(row["mission_id"]) for row in rows]

    def _prune_terminal(self, connection: sqlite3.Connection, keep: int) -> int:
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        last_row: dict[str, int] = {}
        for row in connection.execute("SELECT rowid, * FROM mission_events ORDER BY rowid"):
            grouped.setdefault(row["mission_id"], []).append(self._row(row))
            last_row[row["mission_id"]] = row["rowid"]
        # ponytail: replaying the bounded single-owner ledger avoids another lifecycle index.
        views = {mission_id: project(events) for mission_id, events in grouped.items()}
        active = {
            mission_id for mission_id, view in views.items()
            if view["status"] in {"active", "waiting_owner"}
        }
        protected = {
            row["mission_id"]
            for row in connection.execute("SELECT mission_id FROM mission_subscriptions")
        }
        for mission_id, view in views.items():
            parent = view.get("parent_mission_id")
            # A terminal repair keeps the Telegram binding until its terminal
            # notification is checkpointed.  Retain the parent needed by the
            # subsequent atomic binding restore throughout that handoff.
            if isinstance(parent, str) and mission_id in protected:
                protected.add(parent)
            if mission_id in active and isinstance(parent, str):
                protected.add(parent)
            if isinstance(parent, str) and parent in active:
                protected.add(mission_id)
        terminal = sorted(
            (
                mission_id for mission_id, view in views.items()
                if view["status"] in {"completed", "failed", "cancelled"}
                and mission_id not in protected
            ),
            key=last_row.__getitem__,
            reverse=True,
        )
        pruned = terminal[keep:]
        for mission_id in pruned:
            connection.execute(
                """INSERT INTO mission_tombstones(mission_id, pruned_at)
                   VALUES (?, ?) ON CONFLICT(mission_id) DO NOTHING""",
                (mission_id, _utc_now()),
            )
            connection.execute(
                """DELETE FROM mission_subscription_history
                   WHERE previous_mission_id = ? OR mission_id = ? OR related_mission_id = ?""",
                (mission_id, mission_id, mission_id),
            )
            connection.execute(
                "DELETE FROM mission_events WHERE mission_id = ?", (mission_id,)
            )
        return len(pruned)

    def prune_terminal(self, keep: int = _MAX_RETAINED_TERMINAL_MISSIONS) -> int:
        """Remove old unbound terminal missions while keeping recent owner history."""
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
            raise MissionError("invalid terminal mission retention")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._prune_terminal(connection, keep)

    def dispatch_candidates(
        self, dispatch_profile: str, limit: int = 1, *, reconcile: bool = False
    ) -> list[dict[str, Any]]:
        dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        limit = max(1, min(int(limit), 100))
        if not reconcile:
            limit = 1
        with self._db() as connection:
            rows = connection.execute(
                """SELECT mission_id, payload_json FROM mission_events
                   WHERE sequence = 1 AND type = 'mission.accepted'
                   ORDER BY rowid"""
            ).fetchall()
        candidates = []
        # ponytail: this full accepted-row scan is enough at single-owner scale;
        # add a durable dispatch index only after measured volume justifies it.
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("dispatch_profile") != dispatch_profile:
                continue
            view = self.projection(row["mission_id"])
            if (
                not reconcile
                and view["status"] in {"active", "waiting_owner"}
                and bool(view["tasks"])
            ):
                return []
            eligible = (
                reconcile
                and view["status"] in {"active", "waiting_owner"}
                and bool(view["tasks"])
            ) or (
                not reconcile
                and view["status"] == "active"
                and view["stage"] == "accepted"
                and not view["tasks"]
            )
            if eligible and len(candidates) < limit:
                candidates.append(view)
                if reconcile and len(candidates) == limit:
                    break
        return candidates

    def latest(self) -> str | None:
        missions = self.list(1)
        return missions[0]["mission_id"] if missions else None

    def accept(
        self,
        goal: str,
        *,
        mission_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        dispatch_profile: str | None = None,
        parent_mission_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        goal = str(goal or "").strip()
        if not goal or len(goal) > 8_192:
            raise MissionError("invalid mission goal")
        mission_id = _require_id(mission_id or f"mission-{uuid.uuid4()}", "mission_id")
        if dispatch_profile is not None:
            dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        if parent_mission_id is not None:
            parent_mission_id = _require_id(parent_mission_id, "parent_mission_id")
            if parent_mission_id == mission_id:
                raise MissionError("mission cannot be its own parent")
            self._require_repair_parent(parent_mission_id, mission_id)
        correlation = {
            key: value
            for key, value in (("session_id", session_id), ("run_id", run_id))
            if value
        }
        existing = self.events(mission_id)
        if existing:
            first = existing[0]
            if (
                first["type"] == "mission.accepted"
                and first["payload"].get("goal") == goal
                and first["payload"].get("dispatch_profile") == dispatch_profile
                and first["payload"].get("parent_mission_id") == parent_mission_id
            ):
                if (
                    parent_mission_id is not None
                    and self.projection(mission_id).get("status") == "active"
                ):
                    self._inherit_parent_subscriptions(parent_mission_id, mission_id)
                self.prune_terminal()
                return first, False
            raise MissionError("mission already accepted with different parameters")
        payload = {"goal": goal}
        if dispatch_profile is not None:
            payload["dispatch_profile"] = dispatch_profile
        if parent_mission_id is not None:
            payload["parent_mission_id"] = parent_mission_id
        accepted = self._append(
            mission_id,
            {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": "mission.accepted",
                "source": "central-hermes",
                "correlation": correlation,
                "payload": payload,
            },
        )
        if parent_mission_id is not None:
            self._inherit_parent_subscriptions(parent_mission_id, mission_id)
        self.prune_terminal()
        return accepted

    def _require_repair_parent(self, parent_mission_id: str, child_mission_id: str) -> None:
        parent = self.projection(parent_mission_id)
        if parent.get("status") != "active" or parent.get("parent_mission_id") is not None:
            raise MissionError("repair parent must be an active root mission")
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (parent_mission_id,),
            ).fetchall()
            if rows:
                if any(row["notification_lease_until"] > now for row in rows):
                    raise MissionError("repair parent notification in progress")
                return
            inherited = connection.execute(
                """SELECT 1 FROM mission_subscription_history AS history
                   JOIN mission_subscriptions AS current
                     ON current.platform = history.platform
                    AND current.chat_id = history.chat_id
                    AND current.thread_id = history.thread_id
                   WHERE history.previous_mission_id = ?
                     AND history.mission_id = ?
                     AND history.reason = 'repair-inherit'
                     AND history.related_mission_id = ?
                     AND current.mission_id = ?
                   LIMIT 1""",
                (
                    parent_mission_id, child_mission_id,
                    child_mission_id, child_mission_id,
                ),
            ).fetchone()
        if not inherited:
            raise MissionError("repair parent has no Telegram subscription")

    @staticmethod
    def _subscription_history(
        connection: sqlite3.Connection,
        row: sqlite3.Row | dict[str, Any],
        previous_mission_id: str,
        mission_id: str,
        reason: str,
        related_mission_id: str,
    ) -> None:
        connection.execute(
            """INSERT INTO mission_subscription_history(
                   platform, chat_id, thread_id, previous_mission_id,
                   mission_id, reason, related_mission_id, occurred_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(
                   platform, chat_id, thread_id, previous_mission_id,
                   mission_id, reason, related_mission_id
               ) DO NOTHING""",
            (
                row["platform"], row["chat_id"], row["thread_id"],
                previous_mission_id, mission_id, reason, related_mission_id,
                _utc_now(),
            ),
        )

    def _inherit_parent_subscriptions(
        self, parent_mission_id: str, child_mission_id: str
    ) -> None:
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (parent_mission_id,),
            ).fetchall()
            if not rows:
                current = connection.execute(
                    """SELECT 1 FROM mission_subscription_history AS history
                       JOIN mission_subscriptions AS subscription
                         ON subscription.platform = history.platform
                        AND subscription.chat_id = history.chat_id
                        AND subscription.thread_id = history.thread_id
                       WHERE history.previous_mission_id = ?
                         AND history.mission_id = ?
                         AND history.reason = 'repair-inherit'
                         AND history.related_mission_id = ?
                         AND subscription.mission_id = ?
                       LIMIT 1""",
                    (
                        parent_mission_id, child_mission_id,
                        child_mission_id, child_mission_id,
                    ),
                ).fetchone()
                if current:
                    return
                raise MissionError("repair parent has no Telegram subscription")
            if any(row["notification_lease_until"] > now for row in rows):
                raise MissionError("repair parent notification in progress")
            for row in rows:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET mission_id = ?, last_notified_sequence = 0,
                           notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ?""",
                    (
                        child_mission_id, row["platform"], row["chat_id"],
                        row["thread_id"], parent_mission_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionError("repair subscription inheritance lost its binding")
                self._subscription_history(
                    connection, row, parent_mission_id, child_mission_id,
                    "repair-inherit", child_mission_id,
                )

    def _restore_parent_subscriptions(
        self, connection: sqlite3.Connection, child_mission_id: str, parent_mission_id: str
    ) -> None:
        rows = connection.execute(
            """SELECT * FROM mission_subscriptions
               WHERE mission_id = ? AND platform = 'telegram'""",
            (child_mission_id,),
        ).fetchall()
        for row in rows:
            updated = connection.execute(
                """UPDATE mission_subscriptions
                   SET mission_id = ?, last_notified_sequence = 0,
                       notification_lease = NULL,
                       notification_lease_sequence = 0,
                       notification_lease_until = 0
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?""",
                (
                    parent_mission_id, row["platform"], row["chat_id"],
                    row["thread_id"], child_mission_id,
                ),
            )
            if updated.rowcount != 1:
                raise MissionError("repair subscription restoration lost its binding")
            self._subscription_history(
                connection, row, child_mission_id, parent_mission_id,
                "repair-restore", child_mission_id,
            )

    def answer(
        self, mission_id: str, question_id: str, text: str
    ) -> tuple[dict[str, Any], bool]:
        """Record one idempotent owner answer to the currently open question."""
        question_id = _require_id(question_id, "question_id")
        text = str(text or "").strip()
        if not text or len(text) > _MAX_OWNER_ANSWER_CHARS:
            raise MissionError("owner answer must contain 1..4000 characters")
        fingerprint = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:32]
        return self.append_central(
            mission_id,
            {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": "mission.answer",
                "source": "central-hermes",
                "correlation": {
                    "producer_event_id": f"central:answer:{fingerprint}"
                },
                "payload": {"question_id": question_id, "text": text},
            },
        )

    def append_central(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        normalized = dict(submission)
        normalized["source"] = "central-hermes"
        normalized = _validate_submission(mission_id, normalized)
        if normalized["type"] == "mission.completed":
            raise MissionError("mission completion requires the automatic delivery contract")
        result = self._append(mission_id, normalized)
        if normalized["type"] in TERMINAL_TYPES:
            self.prune_terminal()
        return result

    def append_producer(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return self._append(mission_id, _producer_submission(mission_id, submission))

    def completion_notification(self, mission_id: str) -> dict[str, Any] | None:
        """Build the terminal Telegram projection without committing terminal state."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous:
                raise MissionError("mission not found")
            telegram = connection.execute(
                """SELECT 1 FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram' LIMIT 1""",
                (mission_id,),
            ).fetchone()
        view = project(previous)
        if not telegram:
            return None
        if completion_ready(view, telegram_terminal_ready=True):
            event_type = "mission.completed"
            producer_event_id = "central:auto-complete:v1"
            payload = {"result": "Delivery completed, merged, and verified"}
        elif rejection := _rejection_terminal(view):
            event_type = "mission.failed"
            producer_event_id, payload = rejection
        else:
            return None
        sequence = len(previous) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "mission_id": mission_id,
            "sequence": sequence,
            "event_id": f"{mission_id}:{sequence}",
            "occurred_at": _utc_now(),
            "type": event_type,
            "source": "central-hermes",
            "correlation": {"producer_event_id": producer_event_id},
            "payload": payload,
        }

    def complete_if_ready(self, mission_id: str) -> tuple[dict[str, Any], bool] | None:
        """Let Central, never the producer, append the terminal delivery event."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous:
                raise MissionError("mission not found")
            view = project(previous)
            sequence = len(previous) + 1
            telegram = connection.execute(
                """SELECT last_notified_sequence FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (mission_id,),
            ).fetchall()
            telegram_terminal_ready = bool(telegram) and all(
                row["last_notified_sequence"] >= sequence for row in telegram
            )
            rejection = _rejection_terminal(view)
            if completion_ready(view, telegram_terminal_ready=telegram_terminal_ready):
                event_type = "mission.completed"
                producer_event_id = "central:auto-complete:v1"
                payload = {"result": "Delivery completed, merged, and verified"}
            elif rejection is not None and (not telegram or telegram_terminal_ready):
                event_type = "mission.failed"
                producer_event_id, payload = rejection
            else:
                return None
            event = _validate_submission(
                mission_id,
                {
                    "schema_version": SCHEMA_VERSION,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": producer_event_id},
                    "payload": payload,
                },
            )
            event.update(
                sequence=sequence,
                event_id=f"{mission_id}:{sequence}",
                occurred_at=_utc_now(),
            )
            connection.execute(
                """INSERT INTO mission_events
                   (mission_id, sequence, event_id, occurred_at, type, source,
                    correlation_json, payload_json, producer_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission_id,
                    sequence,
                    event["event_id"],
                    event["occurred_at"],
                    event["type"],
                    event["source"],
                    _json(event["correlation"]),
                    _json(event["payload"]),
                    event["correlation"]["producer_event_id"],
                ),
            )
            parent_mission_id = view.get("parent_mission_id")
            if isinstance(parent_mission_id, str):
                self._restore_parent_subscriptions(
                    connection, mission_id, parent_mission_id
                )
            self._prune_terminal(connection, _MAX_RETAINED_TERMINAL_MISSIONS)
        return event, True

    def _append(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        mission_id = _require_id(mission_id, "mission_id")
        event = _validate_submission(mission_id, submission)
        producer_id = event["correlation"].get("producer_event_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if event["type"] == "mission.accepted" and connection.execute(
                "SELECT 1 FROM mission_tombstones WHERE mission_id = ?", (mission_id,)
            ).fetchone():
                raise MissionError("mission id was already retired")
            if producer_id:
                duplicate = connection.execute(
                    "SELECT * FROM mission_events WHERE mission_id = ? AND producer_event_id = ?",
                    (mission_id, producer_id),
                ).fetchone()
                if duplicate:
                    stored = self._row(duplicate)
                    if any(stored[key] != event[key] for key in ("type", "source", "correlation", "payload")):
                        raise MissionError("producer event id collision")
                    return stored, False
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence", (mission_id,)
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous and event["type"] != "mission.accepted":
                raise MissionError("mission must start with mission.accepted")
            if previous and event["type"] == "mission.accepted":
                raise MissionError("mission already accepted")
            if previous:
                current = project(previous)
                if current["status"] in {"completed", "failed", "cancelled"}:
                    raise MissionError("mission is terminal")
                if event["type"] == "mission.stage" and event["payload"]["progress_percent"] < current["progress_percent"]:
                    raise MissionError("mission progress decreased")
                if event["type"] == "mission.answer":
                    question = current.get("question")
                    if (
                        current.get("status") != "waiting_owner"
                        or not isinstance(question, dict)
                        or question.get("question_id") != event["payload"]["question_id"]
                    ):
                        raise MissionError("mission answer does not match the open question")
            sequence = len(previous) + 1
            event.update(
                sequence=sequence,
                event_id=f"{mission_id}:{sequence}",
                occurred_at=_utc_now(),
            )
            connection.execute(
                """INSERT INTO mission_events
                   (mission_id, sequence, event_id, occurred_at, type, source,
                    correlation_json, payload_json, producer_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission_id,
                    sequence,
                    event["event_id"],
                    event["occurred_at"],
                    event["type"],
                    event["source"],
                    _json(event["correlation"]),
                    _json(event["payload"]),
                    producer_id,
                ),
            )
        return event, True

    def bind(self, mission_id: str, platform: str, chat_id: str, thread_id: str | None = None) -> None:
        mission_id = _require_id(mission_id, "mission_id")
        platform = _require_id(platform, "platform")
        chat_id = str(chat_id or "").strip()
        thread_id = str(thread_id or "").strip()
        if not chat_id or len(chat_id) > 256 or len(thread_id) > 256:
            raise MissionError("invalid mission subscription")
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            if not rows:
                raise MissionError("mission not found")
            project([self._row(row) for row in rows])
            current = connection.execute(
                """SELECT mission_id, notification_lease_until
                   FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                (platform, chat_id, thread_id),
            ).fetchone()
            if current and current["mission_id"] == mission_id:
                return
            if current and current["notification_lease_until"] > now:
                raise MissionError("mission subscription notification in progress")
            connection.execute(
                """INSERT INTO mission_subscriptions(
                       platform, chat_id, thread_id, mission_id,
                       last_notified_sequence, notification_lease,
                       notification_lease_sequence, notification_lease_until
                   ) VALUES (?, ?, ?, ?, 0, NULL, 0, 0)
                   ON CONFLICT(platform, chat_id, thread_id) DO UPDATE SET
                       mission_id = excluded.mission_id,
                       last_notified_sequence = 0,
                       notification_lease = NULL,
                       notification_lease_sequence = 0,
                       notification_lease_until = 0""",
                (platform, chat_id, thread_id, mission_id),
            )
            self._subscription_history(
                connection,
                {"platform": platform, "chat_id": chat_id, "thread_id": thread_id},
                current["mission_id"] if current else "",
                mission_id,
                "manual-bind",
                mission_id,
            )

    def restore_parent_after_terminal_notification(self, mission_id: str) -> None:
        """Restore a repair binding only after its committed terminal update was delivered."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            if not rows:
                raise MissionError("mission not found")
            view = project([self._row(row) for row in rows])
            if view["status"] not in {"completed", "failed", "cancelled"}:
                raise MissionError("repair mission is not terminal")
            parent_mission_id = view.get("parent_mission_id")
            if not isinstance(parent_mission_id, str):
                return
            if connection.execute(
                """SELECT 1 FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'
                     AND last_notified_sequence < ? LIMIT 1""",
                (mission_id, view["sequence"]),
            ).fetchone():
                raise MissionError("repair terminal notification not checkpointed")
            self._restore_parent_subscriptions(
                connection, mission_id, parent_mission_id
            )
            self._prune_terminal(connection, _MAX_RETAINED_TERMINAL_MISSIONS)

    def binding_history(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_subscription_history ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def bound_mission(self, platform: str, chat_id: str, thread_id: str | None = None) -> str | None:
        with self._db() as connection:
            row = connection.execute(
                """SELECT mission_id FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                (str(platform), str(chat_id), str(thread_id or "")),
            ).fetchone()
        return row["mission_id"] if row else None

    def pending_subscriptions(self, mission_id: str, sequence: int) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND last_notified_sequence < ?""",
                (mission_id, sequence),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_notification(self, subscription: dict[str, Any], sequence: int) -> str | None:
        token = uuid.uuid4().hex
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            updated = connection.execute(
                """UPDATE mission_subscriptions
                   SET notification_lease = ?, notification_lease_sequence = ?,
                       notification_lease_until = ?
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?
                     AND last_notified_sequence < ?
                     AND notification_lease_until <= ?""",
                (
                    token,
                    sequence,
                    now + _NOTIFICATION_LEASE_SECONDS,
                    subscription["platform"],
                    subscription["chat_id"],
                    subscription["thread_id"],
                    subscription["mission_id"],
                    sequence,
                    now,
                ),
            )
        return token if updated.rowcount == 1 else None

    def finish_notification(
        self,
        subscription: dict[str, Any],
        sequence: int,
        token: str,
        *,
        delivered: bool,
    ) -> bool:
        with self._db() as connection:
            if delivered:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET last_notified_sequence = ?,
                           notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ? AND notification_lease = ?
                         AND notification_lease_sequence = ?""",
                    (
                        sequence,
                        subscription["platform"],
                        subscription["chat_id"],
                        subscription["thread_id"],
                        subscription["mission_id"],
                        token,
                        sequence,
                    ),
                )
            else:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ? AND notification_lease = ?
                         AND notification_lease_sequence = ?""",
                    (
                        subscription["platform"],
                        subscription["chat_id"],
                        subscription["thread_id"],
                        subscription["mission_id"],
                        token,
                        sequence,
                    ),
                )
            if updated.rowcount == 1:
                return True
            current = connection.execute(
                """SELECT last_notified_sequence FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?""",
                (
                    subscription["platform"],
                    subscription["chat_id"],
                    subscription["thread_id"],
                    subscription["mission_id"],
                ),
            ).fetchone()
        return bool(delivered and current and current["last_notified_sequence"] >= sequence)


async def notify_subscribers(
    store: MissionStore,
    event: dict[str, Any],
    sender: Callable[[dict[str, Any], str], Awaitable[None]],
) -> int:
    """Deliver owner updates at least once; send-before-cursor crashes may duplicate."""
    if event["type"] not in NOTIFY_TYPES:
        return 0
    history = store.events(event["mission_id"])
    view = (
        project([*history, event])
        if event["type"] in TERMINAL_TYPES and event["sequence"] > len(history)
        else project(history)
    )
    text = telegram_text(view)
    sent = 0
    first_error: Exception | None = None
    for subscription in store.pending_subscriptions(event["mission_id"], event["sequence"]):
        token = store.claim_notification(subscription, event["sequence"])
        if token is None:
            continue
        try:
            await sender(subscription, text)
        except Exception as error:
            store.finish_notification(
                subscription, event["sequence"], token, delivered=False
            )
            first_error = first_error or error
        else:
            if store.finish_notification(
                subscription, event["sequence"], token, delivered=True
            ):
                sent += 1
            else:
                first_error = first_error or RuntimeError(
                    "mission subscription changed during notification"
                )
    if first_error is not None:
        raise first_error
    return sent


def producer_key_valid(provided: str | None) -> bool:
    expected = os.environ.get("HERMES_MISSION_PRODUCER_KEY", "").strip()
    return bool(expected and provided and hmac.compare_digest(expected, provided.strip()))


def owner_key_valid(provided: str | None) -> bool:
    expected = os.environ.get("HERMES_MISSION_OWNER_KEY", "").strip()
    return bool(expected and provided and hmac.compare_digest(expected, provided.strip()))


def terminal_request_allowed(remote: str | None) -> bool:
    """Keep terminal mission authority inside the Central Hermes process boundary."""
    try:
        return ipaddress.ip_address(remote or "").is_loopback
    except ValueError:
        return False
