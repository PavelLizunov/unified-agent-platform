#!/usr/bin/env python3
"""Bridge one central Hermes mission to the existing build-1 Kanban executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import flow_contract


class AdapterError(ValueError):
    pass


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
ALLOWED_WORKER_EVENTS = {"change.upsert", "gate.upsert", "delivery.upsert"}
REQUIRED_PAYLOAD = {
    "change.upsert": {"path", "status"},
    "gate.upsert": {"gate_id", "status"},
    "delivery.upsert": {"kind", "status"},
}
PAYLOAD_FIELDS = {
    **REQUIRED_PAYLOAD,
    "delivery.upsert": {"kind", "status", "url"},
}
MAX_LOG_BYTES = 1024 * 1024
MAX_TERMINAL_CHUNK_BYTES = 16 * 1024


def _latest_sticky_event(events: Any) -> dict[str, Any] | None:
    if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
        raise AdapterError("Hermes Kanban task events are invalid")
    return next(
        (
            event
            for event in reversed(events)
            if event.get("kind") in {"blocked", "unblocked"}
        ),
        None,
    )


def _read_json(path: str | pathlib.Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(
    path: pathlib.Path,
    value: Any,
    *,
    private_parent: bool = False,
    retained_mtime: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private_parent else 0o755)
    if os.name == "posix" and private_parent:
        os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    if os.name == "posix":
        os.chmod(temporary, 0o600)
    if retained_mtime is not None:
        os.utime(temporary, (retained_mtime, retained_mtime))
    os.replace(temporary, path)
    if os.name == "posix":
        os.chmod(path, 0o600)


def _accepted_event(document: Any) -> dict[str, Any]:
    if isinstance(document, dict) and isinstance(document.get("events"), list):
        matches = [event for event in document["events"] if event.get("type") == "mission.accepted"]
        if len(matches) != 1:
            raise AdapterError("exactly one mission.accepted event required")
        event = matches[0]
    else:
        event = document
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise AdapterError("mission.accepted schema_version must be 1")
    if event.get("type") != "mission.accepted":
        raise AdapterError("mission.accepted event required")
    if event.get("source") != "central-hermes" or event.get("sequence") != 1:
        raise AdapterError("mission.accepted must be the first central Hermes event")
    mission_id = event.get("mission_id")
    payload = event.get("payload")
    if not isinstance(mission_id, str) or not mission_id or not isinstance(payload, dict):
        raise AdapterError("mission_id and payload are required")
    if not isinstance(payload.get("goal"), str) or not payload["goal"].strip():
        raise AdapterError("mission.accepted payload.goal is required")
    return event


def _mission_dir(state_root: pathlib.Path, mission_id: str) -> pathlib.Path:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(state_root, 0o700)
    digest = hashlib.sha256(mission_id.encode()).hexdigest()[:24]
    return state_root / f"mission-{digest}"


def _state_path(state_root: pathlib.Path, mission_id: str) -> pathlib.Path:
    return _mission_dir(state_root, mission_id) / "adapter-state.json"


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


class HermesKanbanBackend:
    def __init__(self, hermes_bin: str, board: str, runner: Runner = _default_runner):
        self.hermes_bin = hermes_bin
        self.board = board
        self.runner = runner

    def _command(self, *args: str) -> list[str]:
        return [self.hermes_bin, "kanban", "--board", self.board, *args]

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.runner(self._command(*args))
        if result.returncode:
            raise AdapterError(flow_contract._safe_error(
                (result.stderr or result.stdout).strip() or "Hermes Kanban command failed"
            ))
        return result

    def _json(self, *args: str) -> Any:
        result = self._run(*args)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterError("Hermes Kanban returned invalid JSON") from error

    def ensure_root(
        self,
        *,
        mission_id: str,
        goal: str,
        allow_dispatch: bool,
        assignee: str | None,
        workspace: str | None,
    ) -> dict[str, Any]:
        if allow_dispatch and (not assignee or not workspace or workspace == "scratch"):
            raise AdapterError("dispatch requires an assignee and a non-scratch workspace")
        command = [
            "create", f"Mission {mission_id}", "--body", goal,
            "--tenant", mission_id, "--created-by", "central-hermes",
            "--idempotency-key", f"central-mission:{mission_id}",
            # Pinned Hermes v0.18.0 exposes ``running`` as the create-time
            # spelling for an atomically persisted, unclaimed ``ready`` card.
            "--initial-status", "running" if allow_dispatch else "blocked",
        ]
        if workspace:
            command.extend(["--workspace", workspace])
        if allow_dispatch:
            command.extend(["--assignee", assignee or "", "--goal"])
        command.append("--json")
        task = self._json(*command)
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise AdapterError("Hermes Kanban create response has no task id")
        snapshot = self.show(task["id"])
        current = snapshot["task"]
        if not allow_dispatch:
            if (
                current.get("id") != task["id"]
                or "assignee" not in current
                or current["assignee"] is not None
            ):
                raise AdapterError("blocked handoff task identity/assignee mismatch")
            events = snapshot.get("events", [])
            if not isinstance(events, list):
                raise AdapterError("Hermes Kanban task events are invalid")
            sticky = next(
                (event.get("kind") for event in reversed(events)
                 if isinstance(event, dict) and event.get("kind") in {"blocked", "unblocked"}),
                None,
            )
            if (
                current.get("status") != "blocked"
                or sticky != "blocked"
            ):
                raise AdapterError("safe handoff is not atomically sticky-blocked")
            if not isinstance(snapshot.get("runs"), list) or snapshot["runs"]:
                raise AdapterError("safe handoff unexpectedly created a Kanban run")
            task = current
        elif (
            current.get("id") != task["id"]
            or current.get("status") != "ready"
            or current.get("assignee") != assignee
            or not isinstance(snapshot.get("runs"), list)
            or snapshot["runs"]
        ):
            raise AdapterError("active handoff did not persist one unclaimed ready task")
        else:
            task = current
        return task

    def list_task_ids(self, mission_id: str) -> list[str]:
        return sorted(task["id"] for task in self.list_tasks(mission_id))

    def resume_root_from_answer(
        self,
        task_id: str,
        *,
        assignee: str,
        workspace: str,
        question_id: str,
        answer_digest: str,
    ) -> dict[str, Any]:
        if (
            not assignee
            or not workspace.startswith("worktree:")
            or not workspace.removeprefix("worktree:")
            or not question_id
            or len(question_id) > 128
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for character in question_id)
            or len(answer_digest) != 64
            or any(character not in "0123456789abcdef" for character in answer_digest)
        ):
            raise AdapterError("owner-answer resume contract is invalid")
        reference = f"owner-answer:{question_id}:{answer_digest[:16]}"
        snapshot = self.show(task_id)
        task = snapshot["task"]
        runs = snapshot.get("runs")
        if (
            task.get("id") != task_id
            or task.get("status") not in {"blocked", "ready", "running"}
            or task.get("assignee") not in {None, assignee}
            or task.get("workspace_kind") != "worktree"
            or task.get("workspace_path") != workspace.removeprefix("worktree:")
            or not isinstance(runs, list)
            or sum(run.get("status") == "running" for run in runs if isinstance(run, dict)) > 1
        ):
            raise AdapterError("owner-answer resume selected an invalid Kanban root")
        if task.get("status") == "blocked":
            sticky = _latest_sticky_event(snapshot.get("events"))
            if sticky is None or sticky.get("kind") != "blocked":
                raise AdapterError("owner-answer root is not atomically sticky-blocked")
            if task.get("assignee") is None:
                self._run("assign", task_id, assignee)
                snapshot = self.show(task_id)
                task = snapshot["task"]
                if task.get("status") != "blocked" or task.get("assignee") != assignee:
                    raise AdapterError("owner-answer assignee did not persist")
            self._run("unblock", "--reason", reference, task_id)
            snapshot = self.show(task_id)
            task = snapshot["task"]
        if task.get("status") not in {"ready", "running"} or task.get("assignee") != assignee:
            raise AdapterError("owner-answer resume did not make the task runnable")
        sticky = _latest_sticky_event(snapshot.get("events"))
        payload = sticky.get("payload") if sticky else None
        if (
            sticky is None
            or sticky.get("kind") != "unblocked"
            or not isinstance(payload, dict)
            or payload.get("reason") != reference
        ):
            raise AdapterError("owner-answer resume lacks its exact durable Kanban checkpoint")
        runs = snapshot.get("runs")
        active = [
            run for run in runs or []
            if isinstance(run, dict) and run.get("status") == "running"
        ]
        if not isinstance(runs, list) or (task.get("status") == "ready" and active) or len(active) > 1:
            raise AdapterError("owner-answer resume has an invalid run state")
        return snapshot

    def list_tasks(self, mission_id: str) -> list[dict[str, Any]]:
        tasks = self._json("list", "--tenant", mission_id, "--json")
        if not isinstance(tasks, list):
            raise AdapterError("Hermes Kanban list response must be an array")
        if not all(isinstance(task, dict) for task in tasks):
            raise AdapterError("Hermes Kanban list response has an invalid task")
        if not all(isinstance(task.get("id"), str) and task["id"] for task in tasks):
            raise AdapterError("Hermes Kanban list response has an invalid task id")
        return tasks

    def show(self, task_id: str) -> dict[str, Any]:
        result = self._json("show", task_id, "--json")
        if not isinstance(result, dict) or not isinstance(result.get("task"), dict):
            raise AdapterError("Hermes Kanban show response is invalid")
        return result

    def read_log(self, task_id: str) -> str:
        result = self.runner(self._command("log", task_id))
        if result.returncode:
            if "no log" in (result.stderr or "").lower():
                return ""
            raise AdapterError(flow_contract._safe_error(
                (result.stderr or result.stdout).strip() or "Hermes Kanban log failed"
            ))
        return result.stdout

    def claim(
        self, task_id: str, *, ttl_seconds: int, provenance: str | None = None
    ) -> dict[str, Any]:
        if ttl_seconds <= 0:
            raise AdapterError("Kanban claim TTL must be positive")
        if provenance is not None and re.fullmatch(r"[0-9a-f]{64}", provenance) is None:
            raise AdapterError("Kanban claim provenance is invalid")
        command = ["claim", task_id, "--ttl", str(ttl_seconds)]
        if provenance is not None:
            command.extend(("--claimer", provenance))
        self._run(*command)
        snapshot = self.show(task_id)
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        active = [
            run for run in runs or []
            if isinstance(run, dict) and run.get("status") == "running"
        ]
        if (
            not isinstance(task, dict)
            or task.get("id") != task_id
            or task.get("status") != "running"
            or not isinstance(runs, list)
            or len(active) != 1
        ):
            raise AdapterError("Hermes Kanban claim did not create one running task/run")
        return snapshot

    def schedule(self, task_id: str, *, reason: str) -> dict[str, Any]:
        if not reason:
            raise AdapterError("Kanban schedule reason is required")
        self._run("schedule", task_id, reason)
        snapshot = self.show(task_id)
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        if (
            not isinstance(task, dict)
            or task.get("id") != task_id
            or task.get("status") != "scheduled"
            or not isinstance(runs, list)
            or any(isinstance(run, dict) and run.get("status") == "running" for run in runs)
        ):
            raise AdapterError("Hermes Kanban task did not enter scheduled state")
        return snapshot

    def unblock(self, task_id: str, *, reason: str) -> dict[str, Any]:
        if not reason:
            raise AdapterError("Kanban unblock reason is required")
        self._run("unblock", task_id, "--reason", reason)
        snapshot = self.show(task_id)
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        if (
            not isinstance(task, dict)
            or task.get("id") != task_id
            or task.get("status") != "ready"
            or not isinstance(runs, list)
            or any(isinstance(run, dict) and run.get("status") == "running" for run in runs)
        ):
            raise AdapterError("Hermes Kanban task did not return to ready state")
        return snapshot

    def verify_claim(
        self,
        task_id: str,
        run_id: str,
        *,
        min_remaining_seconds: int = 60,
        provenance: str | None = None,
    ) -> dict[str, Any]:
        if provenance is not None and re.fullmatch(r"[0-9a-f]{64}", provenance) is None:
            raise AdapterError("Kanban claim provenance is invalid")
        snapshot = self.show(task_id)
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        events = snapshot.get("events")
        matching = [
            run for run in runs or []
            if isinstance(run, dict) and str(run.get("id")) == str(run_id)
        ]
        active = [
            run for run in runs or []
            if isinstance(run, dict) and run.get("status") == "running"
        ]
        claims = [
            event for event in events or []
            if (
                isinstance(event, dict)
                and event.get("kind") == "claimed"
                and str(event.get("run_id")) == str(run_id)
                and isinstance(event.get("payload"), dict)
                and str(event["payload"].get("run_id")) == str(run_id)
            )
        ]
        minimum = int(time.time()) + min_remaining_seconds
        if (
            not isinstance(task, dict)
            or task.get("id") != task_id
            or task.get("status") != "running"
            or len(matching) != 1
            or len(active) != 1
            or str(active[0].get("id")) != str(run_id)
            or matching[0].get("status") != "running"
            # Pinned Hermes omits private claim columns from ``kanban show``;
            # the durable public lease proof is the matching claimed event.
            or len(claims) != 1
            or not isinstance(claims[0]["payload"].get("lock"), str)
            or not claims[0]["payload"]["lock"]
            or (
                provenance is not None
                and claims[0]["payload"]["lock"] != provenance
            )
            or not isinstance(claims[0]["payload"].get("expires"), int)
            or claims[0]["payload"]["expires"] <= minimum
        ):
            raise AdapterError("Hermes Kanban claim is absent, stale, or expired")
        return snapshot

    def complete(
        self, task_id: str, *, result: str, summary: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        self._run(
            "complete", task_id,
            "--result", result,
            "--summary", summary,
            "--metadata", json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        )
        snapshot = self.show(task_id)
        if snapshot.get("task", {}).get("status") != "done":
            raise AdapterError("Hermes Kanban completion did not persist done status")
        return snapshot

    def archive(self, task_id: str) -> dict[str, Any]:
        snapshot = self.show(task_id)
        status = snapshot.get("task", {}).get("status")
        if status == "archived":
            return snapshot
        if status != "done":
            raise AdapterError("only a completed Kanban task can be archived")
        self._run("archive", task_id)
        snapshot = self.show(task_id)
        if snapshot.get("task", {}).get("status") != "archived":
            raise AdapterError("Kanban task archive did not persist")
        return snapshot

    def gc(self) -> bool:
        result = self.runner(self._command("gc", "--require-idle"))
        output = result.stdout.strip()
        if (
            output == "GC deferred: board is not idle"
            and result.returncode in (0, 3)
        ):
            return False
        if result.returncode:
            raise AdapterError(
                flow_contract._safe_error(
                    (result.stderr or result.stdout).strip()
                    or "Hermes Kanban command failed"
                )
            )
        if not output.startswith("GC complete: "):
            raise AdapterError("Hermes Kanban returned an invalid GC result")
        return True

    def edit_metadata(
        self, task_id: str, *, result: str, summary: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        self._run(
            "edit", task_id,
            "--result", result,
            "--summary", summary,
            "--metadata", json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        )
        return self.show(task_id)


class CentralMissionClient:
    def __init__(self, base_url: str, api_token: str, producer_key: str):
        parsed = urllib.parse.urlsplit(str(base_url or "").strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise AdapterError("invalid central mission URL")
        if not api_token.strip() or not producer_key.strip():
            raise AdapterError("central mission credentials are required")
        self.base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        self.api_token = api_token.strip()
        self.producer_key = producer_key.strip()
        # Central Hermes is a private control-plane endpoint. Never send its
        # bearer or producer credentials through an ambient egress proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if body is not None:
            headers.update({
                "Content-Type": "application/json",
                "X-Hermes-Mission-Producer-Key": self.producer_key,
            })
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise AdapterError(f"central mission API returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as error:
            raise AdapterError("central mission API request failed") from error
        if not isinstance(result, dict):
            raise AdapterError("central mission API returned invalid JSON")
        return result

    def list_missions(
        self, dispatch_profile: str, *, reconcile: bool = False
    ) -> list[dict[str, Any]]:
        parameters: dict[str, Any] = {"dispatch_profile": dispatch_profile, "limit": 1}
        if reconcile:
            parameters["reconcile"] = 1
        query = urllib.parse.urlencode(parameters)
        result = self._request("GET", f"/api/missions?{query}")
        missions = result.get("missions")
        if not isinstance(missions, list) or not all(isinstance(item, dict) for item in missions):
            raise AdapterError("central mission list is invalid")
        return missions

    def get_mission(self, mission_id: str) -> dict[str, Any]:
        result = self._request(
            "GET", f"/api/missions/{urllib.parse.quote(mission_id, safe='')}"
        )
        mission = result.get("mission")
        if not isinstance(mission, dict):
            raise AdapterError("central mission API returned an invalid projection")
        return mission

    def accept_mission(
        self,
        *,
        mission_id: str,
        goal: str,
        dispatch_profile: str,
        parent_mission_id: str,
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/api/missions",
            {
                "mission_id": mission_id,
                "goal": goal,
                "dispatch_profile": dispatch_profile,
                "parent_mission_id": parent_mission_id,
            },
        )
        mission = result.get("mission")
        if not isinstance(mission, dict):
            raise AdapterError("central mission API returned an invalid accepted mission")
        return mission

    def publish(self, mission_id: str, event: dict[str, Any]) -> None:
        self._request("POST", f"/api/missions/{urllib.parse.quote(mission_id, safe='')}/events", event)


def accept_mission(
    document: Any,
    state_root: pathlib.Path,
    backend: Any,
    *,
    allow_dispatch: bool = False,
    assignee: str | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    event = _accepted_event(document)
    mission_id = event["mission_id"]
    task = backend.ensure_root(
        mission_id=mission_id,
        goal=event["payload"]["goal"].strip(),
        allow_dispatch=allow_dispatch,
        assignee=assignee,
        workspace=workspace,
    )
    state = {
        "schema_version": 1,
        "mission_id": mission_id,
        "root_task_id": task["id"],
        "tenant": mission_id,
        "idempotency_key": f"central-mission:{mission_id}",
    }
    _write_json(_state_path(state_root, mission_id), state, private_parent=True)
    return state


def recover_mission_state(
    mission_id: str, state_root: pathlib.Path, backend: Any
) -> dict[str, Any]:
    path = _state_path(state_root, mission_id)
    roots = [
        task for task in backend.list_tasks(mission_id)
        if task.get("title") == f"Mission {mission_id}"
        and task.get("created_by") == "central-hermes"
        and task.get("tenant") == mission_id
    ]
    if len(roots) != 1:
        raise AdapterError("mission adapter state cannot be recovered from one exact Kanban root")
    root_task_id = roots[0]["id"]
    if path.is_file():
        state = _read_json(path)
        expected = {
            "schema_version": 1,
            "mission_id": mission_id,
            "tenant": mission_id,
            "idempotency_key": f"central-mission:{mission_id}",
        }
        if not isinstance(state, dict) or any(state.get(key) != value for key, value in expected.items()):
            raise AdapterError("mission adapter state mismatch")
        if state.get("root_task_id") != root_task_id:
            raise AdapterError("mission adapter state has the wrong root task id")
        return state

    state = {
        "schema_version": 1,
        "mission_id": mission_id,
        "root_task_id": root_task_id,
        "tenant": mission_id,
        "idempotency_key": f"central-mission:{mission_id}",
    }
    _write_json(path, state, private_parent=True)
    return state


def _producer_event(
    mission_id: str,
    event_type: str,
    payload: dict[str, Any],
    correlation: dict[str, str],
) -> dict[str, Any]:
    identity_correlation = correlation
    if event_type in ALLOWED_WORKER_EVENTS:
        identity_correlation = {"task_id": correlation.get("task_id", "")}
    material = json.dumps(
        {"type": event_type, "payload": payload, "correlation": identity_correlation},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    producer_event_id = f"build1-flow:{hashlib.sha256(material).hexdigest()[:24]}"
    return {
        "schema_version": 1,
        "mission_id": mission_id,
        "type": event_type,
        "source": "build1-flow",
        "correlation": {**correlation, "producer_event_id": producer_event_id},
        "payload": payload,
    }


def _worker_metadata_events(
    mission_id: str,
    task_id: str,
    worker_id: str,
    metadata: Any,
) -> list[dict[str, Any]]:
    if metadata is None:
        return []
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError as error:
            raise AdapterError("worker metadata is invalid JSON") from error
    if not isinstance(metadata, dict):
        raise AdapterError("worker metadata must be an object")
    items = metadata.get("mission_events", [])
    if not isinstance(items, list):
        raise AdapterError("worker metadata.mission_events must be an array")
    events = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in ALLOWED_WORKER_EVENTS:
            raise AdapterError("worker mission event type is not allowed")
        payload = item.get("payload")
        event_type = item["type"]
        if (
            not isinstance(payload, dict)
            or not REQUIRED_PAYLOAD[event_type] <= set(payload) <= PAYLOAD_FIELDS[event_type]
            or any(not isinstance(payload[key], str) or not payload[key] for key in REQUIRED_PAYLOAD[event_type])
        ):
            raise AdapterError("worker mission event payload is invalid")
        if event_type == "delivery.upsert":
            not_applicable = (
                payload.get("kind") == "delivery"
                and payload.get("status") == "not_applicable"
            )
            if (
                (not_applicable and "url" in payload)
                or (not not_applicable and not isinstance(payload.get("url"), str))
                or (isinstance(payload.get("url"), str) and not payload["url"])
            ):
                raise AdapterError("worker mission event payload is invalid")
        events.append(_producer_event(
            mission_id, event_type, payload, {"task_id": task_id, "worker_id": worker_id}
        ))
    return events


def _utf8_chunks(text: str) -> list[tuple[str, int]]:
    encoded = text.encode("utf-8")
    chunks = []
    start = 0
    while start < len(encoded):
        end = min(start + MAX_TERMINAL_CHUNK_BYTES, len(encoded))
        while end < len(encoded) and encoded[end] & 0xC0 == 0x80:
            end -= 1
        chunk = encoded[start:end].decode("utf-8")
        chunks.append((chunk, end - start))
        start = end
    return chunks


def _terminal_events(mission_id: str, task_id: str, text: str, terminal: bool) -> list[dict[str, Any]]:
    tail: list[tuple[int, str, int]] = []
    retained_bytes = 0
    offset = 0
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")) and not terminal:
        lines.pop()
    for line in lines:
        for chunk, chunk_bytes in _utf8_chunks(line):
            chunk_offset = offset
            offset += chunk_bytes
            if not chunk.strip():
                continue
            tail.append((chunk_offset, chunk, chunk_bytes))
            retained_bytes += chunk_bytes
            while retained_bytes > MAX_LOG_BYTES:
                retained_bytes -= tail.pop(0)[2]

    events = []
    for chunk_offset, chunk, _chunk_bytes in tail:
        events.append(_producer_event(
            mission_id,
            "terminal.append",
            {"stream": "stdout", "text": chunk, "offset": chunk_offset},
            {"task_id": task_id},
        ))
    return events


def project_task_snapshot(
    mission_id: str,
    task_id: str,
    snapshot: dict[str, Any],
    log_text: str,
) -> list[dict[str, Any]]:
    events = []
    task = snapshot.get("task")
    if not isinstance(task, dict) or task.get("id") != task_id:
        raise AdapterError("Kanban task id mismatch")
    task_payload = {
        "task_id": task_id,
        "title": task.get("title") or task_id,
        "status": task.get("status") or "unknown",
        "assignee": task.get("assignee"),
    }
    events.append(_producer_event(mission_id, "task.upsert", task_payload, {"task_id": task_id}))

    runs = snapshot.get("runs", [])
    if not isinstance(runs, list):
        raise AdapterError("Kanban runs must be an array")
    metadata_events = []
    for run in sorted(runs, key=lambda value: str(value.get("id"))):
        if not isinstance(run, dict) or run.get("id") is None:
            raise AdapterError("Kanban run is invalid")
        worker_id = f"{task_id}:run:{run['id']}"
        worker_payload = {
            "worker_id": worker_id,
            "run_id": str(run["id"]),
            "profile": run.get("profile"),
            "status": run.get("outcome") or run.get("status") or "unknown",
        }
        correlation = {"task_id": task_id, "worker_id": worker_id}
        events.append(_producer_event(mission_id, "worker.upsert", worker_payload, correlation))
        metadata_events.extend(_worker_metadata_events(
            mission_id, task_id, worker_id, run.get("metadata")
        ))

    terminal = task_payload["status"] in {"done", "archived"}
    events.extend(_terminal_events(mission_id, task_id, log_text, terminal))
    events.extend(metadata_events)
    return events


def project_mission(mission_id: str, backend: Any) -> list[dict[str, Any]]:
    events = []
    task_ids = backend.list_task_ids(mission_id)
    if not task_ids:
        raise AdapterError("mission has no Kanban tasks")
    for task_id in task_ids:
        events.extend(project_task_snapshot(
            mission_id,
            task_id,
            backend.show(task_id),
            backend.read_log(task_id),
        ))
    unique = {}
    for event in events:
        unique.setdefault(event["correlation"]["producer_event_id"], event)
    return list(unique.values())


def sync_mission(mission_id: str, state_root: pathlib.Path, backend: Any) -> list[dict[str, Any]]:
    recover_mission_state(mission_id, state_root, backend)
    return project_mission(mission_id, backend)


def reconcile_pending(
    client: Any,
    state_root: pathlib.Path,
    backend: Any,
    *,
    dispatch_profile: str,
    before_publish: Callable[[str, dict[str, Any]], None] | None = None,
    event_source: Callable[[str, dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    if not dispatch_profile:
        raise AdapterError("reconcile requires a profile")
    for mission in client.list_missions(dispatch_profile, reconcile=True):
        tasks = mission.get("tasks")
        if (
            mission.get("dispatch_profile") != dispatch_profile
            or mission.get("status") not in {"active", "waiting_owner"}
            or not isinstance(tasks, list)
            or not tasks
        ):
            raise AdapterError("central reconcile projection is invalid")
        mission_id = mission.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id:
            raise AdapterError("central reconcile projection has no mission id")
        state = recover_mission_state(mission_id, state_root, backend)
        if not all(
            isinstance(task, dict) and isinstance(task.get("task_id"), str) and task["task_id"]
            for task in tasks
        ):
            raise AdapterError("central reconcile projection has an invalid task")
        projected_ids = {task["task_id"] for task in tasks}
        if state["root_task_id"] not in projected_ids:
            raise AdapterError("central projection does not contain the exact Kanban root")
        events = (
            sync_mission(mission_id, state_root, backend)
            if event_source is None
            else event_source(mission_id, state)
        )
        for event in events:
            if before_publish is not None:
                before_publish(mission_id, event)
            client.publish(mission_id, event)
        return {**state, "published_events": len(events)}
    return None


def dispatch_pending(
    client: Any,
    state_root: pathlib.Path,
    backend: Any,
    *,
    dispatch_profile: str,
    workspace: str,
    assignee: str | None = None,
    activate: bool = False,
) -> dict[str, Any] | None:
    if not dispatch_profile or not workspace or workspace == "scratch":
        raise AdapterError("poll requires a profile and non-scratch workspace")
    if activate and not assignee:
        raise AdapterError("activation requires an assignee")
    for mission in client.list_missions(dispatch_profile):
        tasks = mission.get("tasks")
        if not isinstance(tasks, list):
            raise AdapterError("central mission projection has invalid tasks")
        if (
            mission.get("dispatch_profile") != dispatch_profile
            or mission.get("status") != "active"
            or mission.get("stage") != "accepted"
            or tasks
        ):
            continue
        mission_id = mission.get("mission_id")
        goal = mission.get("goal")
        if not isinstance(mission_id, str) or not mission_id or not isinstance(goal, str) or not goal.strip():
            raise AdapterError("central mission projection is incomplete")
        accepted = {
            "schema_version": 1,
            "mission_id": mission_id,
            "sequence": 1,
            "type": "mission.accepted",
            "source": "central-hermes",
            "correlation": {},
            "payload": {"goal": goal, "dispatch_profile": dispatch_profile},
        }
        state = accept_mission(
            accepted,
            state_root,
            backend,
            allow_dispatch=activate,
            assignee=assignee,
            workspace=workspace,
        )
        events = sync_mission(mission_id, state_root, backend)
        for event in events:
            client.publish(mission_id, event)
        return {**state, "published_events": len(events)}
    return None


def coordinator_tick(
    client: Any,
    state_root: pathlib.Path,
    backend: Any,
    *,
    dispatch_profile: str,
    workspace: str,
    assignee: str | None = None,
    activate: bool = False,
) -> dict[str, Any] | None:
    reconciled = reconcile_pending(
        client, state_root, backend, dispatch_profile=dispatch_profile
    )
    if reconciled is not None:
        return {**reconciled, "action": "reconciled"}
    dispatched = dispatch_pending(
        client,
        state_root,
        backend,
        dispatch_profile=dispatch_profile,
        workspace=workspace,
        assignee=assignee,
        activate=activate,
    )
    return None if dispatched is None else {**dispatched, "action": "dispatched"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-bin", default="/home/uap/hermes-agent/.venv/bin/hermes")
    parser.add_argument("--board", default="default")
    parser.add_argument("--state-root", type=pathlib.Path, default=pathlib.Path("/home/uap/swarm-out"))
    sub = parser.add_subparsers(dest="command", required=True)

    accept = sub.add_parser("accept")
    accept.add_argument("--event", required=True)
    accept.add_argument("--allow-dispatch", action="store_true")
    accept.add_argument("--assignee")
    accept.add_argument("--workspace")

    sync = sub.add_parser("sync")
    sync.add_argument("--mission-id", required=True)
    sync.add_argument("--output", type=pathlib.Path)

    poll = sub.add_parser("poll")
    poll.add_argument("--central-url", default=os.environ.get("HERMES_API_URL"))
    poll.add_argument("--dispatch-profile", required=True)
    poll.add_argument("--workspace", required=True)
    poll.add_argument("--assignee")
    poll.add_argument("--activate", action="store_true")

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--central-url", default=os.environ.get("HERMES_API_URL"))
    reconcile.add_argument("--dispatch-profile", required=True)

    tick = sub.add_parser("tick")
    tick.add_argument("--central-url", default=os.environ.get("HERMES_API_URL"))
    tick.add_argument("--dispatch-profile", required=True)
    tick.add_argument("--workspace", required=True)
    tick.add_argument("--assignee")
    tick.add_argument("--activate", action="store_true")

    args = parser.parse_args(argv)
    backend = HermesKanbanBackend(args.hermes_bin, args.board)
    try:
        if args.command == "accept":
            result = accept_mission(
                _read_json(args.event), args.state_root, backend,
                allow_dispatch=args.allow_dispatch, assignee=args.assignee, workspace=args.workspace,
            )
        elif args.command == "sync":
            result = sync_mission(args.mission_id, args.state_root, backend)
        elif args.command in {"poll", "reconcile", "tick"}:
            client = CentralMissionClient(
                args.central_url,
                os.environ.get("HERMES_API_TOKEN", ""),
                os.environ.get("HERMES_MISSION_PRODUCER_KEY", ""),
            )
            if args.command == "poll":
                result = dispatch_pending(
                    client,
                    args.state_root,
                    backend,
                    dispatch_profile=args.dispatch_profile,
                    workspace=args.workspace,
                    assignee=args.assignee,
                    activate=args.activate,
                )
            elif args.command == "reconcile":
                result = reconcile_pending(
                    client,
                    args.state_root,
                    backend,
                    dispatch_profile=args.dispatch_profile,
                )
            else:
                result = coordinator_tick(
                    client,
                    args.state_root,
                    backend,
                    dispatch_profile=args.dispatch_profile,
                    workspace=args.workspace,
                    assignee=args.assignee,
                    activate=args.activate,
                )
        if args.command == "sync" and args.output:
            _write_json(args.output, result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (AdapterError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(
            f"hermes-mission-adapter-error: {flow_contract._safe_error(error)}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
