#!/usr/bin/env python3
"""Bridge one central Hermes mission to the existing build-1 Kanban executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


class AdapterError(ValueError):
    pass


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
ALLOWED_WORKER_EVENTS = {"change.upsert", "gate.upsert", "delivery.upsert"}
REQUIRED_PAYLOAD = {
    "change.upsert": {"path", "status"},
    "gate.upsert": {"gate_id", "status"},
    "delivery.upsert": {"kind", "status", "url"},
}
MAX_LOG_BYTES = 1024 * 1024


def _read_json(path: str | pathlib.Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    os.replace(temporary, path)


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

    def _json(self, *args: str) -> Any:
        result = self.runner(self._command(*args))
        if result.returncode:
            raise AdapterError((result.stderr or result.stdout).strip() or "Hermes Kanban command failed")
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
            "--initial-status", "ready" if allow_dispatch else "blocked",
        ]
        if workspace:
            command.extend(["--workspace", workspace])
        if allow_dispatch:
            command.extend(["--assignee", assignee or "", "--goal"])
        command.append("--json")
        task = self._json(*command)
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise AdapterError("Hermes Kanban create response has no task id")
        return task

    def list_task_ids(self, mission_id: str) -> list[str]:
        tasks = self._json("list", "--tenant", mission_id, "--json")
        if not isinstance(tasks, list):
            raise AdapterError("Hermes Kanban list response must be an array")
        if not all(isinstance(task, dict) for task in tasks):
            raise AdapterError("Hermes Kanban list response has an invalid task")
        ids = [task.get("id") for task in tasks]
        if not all(isinstance(task_id, str) and task_id for task_id in ids):
            raise AdapterError("Hermes Kanban list response has an invalid task id")
        return sorted(ids)

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
            raise AdapterError((result.stderr or result.stdout).strip() or "Hermes Kanban log failed")
        return result.stdout


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
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise AdapterError(f"central mission API returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as error:
            raise AdapterError("central mission API request failed") from error
        if not isinstance(result, dict):
            raise AdapterError("central mission API returned invalid JSON")
        return result

    def list_missions(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/missions?limit=100")
        missions = result.get("missions")
        if not isinstance(missions, list) or not all(isinstance(item, dict) for item in missions):
            raise AdapterError("central mission list is invalid")
        return missions

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
    _write_json(_state_path(state_root, mission_id), state)
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
            or not REQUIRED_PAYLOAD[event_type].issubset(payload)
            or any(not isinstance(payload[key], str) or not payload[key] for key in REQUIRED_PAYLOAD[event_type])
        ):
            raise AdapterError("worker mission event payload is invalid")
        events.append(_producer_event(
            mission_id, event_type, payload, {"task_id": task_id, "worker_id": worker_id}
        ))
    return events


def _terminal_events(mission_id: str, task_id: str, text: str, terminal: bool) -> list[dict[str, Any]]:
    if len(text.encode("utf-8")) > MAX_LOG_BYTES:
        raise AdapterError("Kanban task log exceeds the mission event limit")
    events = []
    offset = 0
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")) and not terminal:
        lines.pop()
    for line in lines:
        events.append(_producer_event(
            mission_id,
            "terminal.append",
            {"stream": "stdout", "text": line, "offset": offset},
            {"task_id": task_id},
        ))
        offset += len(line.encode("utf-8"))
    return events


def project_mission(mission_id: str, backend: Any) -> list[dict[str, Any]]:
    events = []
    task_ids = backend.list_task_ids(mission_id)
    if not task_ids:
        raise AdapterError("mission has no Kanban tasks")
    for task_id in task_ids:
        snapshot = backend.show(task_id)
        task = snapshot["task"]
        if task.get("id") != task_id:
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
            events.extend(_worker_metadata_events(
                mission_id, task_id, worker_id, run.get("metadata")
            ))

        terminal = task_payload["status"] in {"done", "archived"}
        events.extend(_terminal_events(mission_id, task_id, backend.read_log(task_id), terminal))
    unique = {}
    for event in events:
        unique.setdefault(event["correlation"]["producer_event_id"], event)
    return list(unique.values())


def sync_mission(mission_id: str, state_root: pathlib.Path, backend: Any) -> list[dict[str, Any]]:
    path = _state_path(state_root, mission_id)
    if not path.is_file():
        raise AdapterError("mission adapter state not found")
    state = _read_json(path)
    if not isinstance(state, dict) or state.get("mission_id") != mission_id:
        raise AdapterError("mission adapter state mismatch")
    return project_mission(mission_id, backend)


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
    for mission in client.list_missions():
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
        else:
            client = CentralMissionClient(
                args.central_url,
                os.environ.get("HERMES_API_TOKEN", ""),
                os.environ.get("HERMES_MISSION_PRODUCER_KEY", ""),
            )
            result = dispatch_pending(
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
        print(f"hermes-mission-adapter-error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
