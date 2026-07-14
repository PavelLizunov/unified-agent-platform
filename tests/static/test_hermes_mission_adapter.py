#!/usr/bin/env python3
import copy
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "swarm" / "mission_adapter.py"
SPEC = importlib.util.spec_from_file_location("mission_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(adapter)
FIXTURE = ROOT / "tests" / "fixtures" / "hermes-mission-events-v1.json"


class FakeKanban:
    def __init__(self, store=None):
        self.store = store or {"by_key": {}, "tasks": {}, "create_calls": 0, "logs": {}}

    @property
    def tasks(self):
        return self.store["tasks"]

    @property
    def logs(self):
        return self.store["logs"]

    @property
    def create_calls(self):
        return self.store["create_calls"]

    def ensure_root(self, *, mission_id, goal, allow_dispatch, assignee, workspace):
        self.store["create_calls"] += 1
        key = f"central-mission:{mission_id}"
        if key not in self.store["by_key"]:
            task_id = f"task-{len(self.tasks) + 1}"
            self.store["by_key"][key] = task_id
            self.tasks[task_id] = {
                "task": {
                    "id": task_id,
                    "title": goal,
                    "status": "ready" if allow_dispatch else "blocked",
                    "assignee": assignee if allow_dispatch else None,
                },
                "runs": [],
            }
        return copy.deepcopy(self.tasks[self.store["by_key"][key]]["task"])

    def list_task_ids(self, mission_id):
        return sorted(self.tasks)

    def show(self, task_id):
        return copy.deepcopy(self.tasks[task_id])

    def read_log(self, task_id):
        return self.logs.get(task_id, "")


class DeduplicatingCentralSink:
    def __init__(self):
        self.events = {}

    def append(self, events):
        for event in events:
            producer_id = event["correlation"]["producer_event_id"]
            self.events.setdefault(producer_id, event)


class MissionAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_crash_and_dispatcher_restart_do_not_duplicate_work(self):
        backend = FakeKanban()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            with mock.patch.object(adapter, "_write_json", side_effect=OSError("simulated crash")):
                with self.assertRaisesRegex(OSError, "simulated crash"):
                    adapter.accept_mission(
                        self.document, state_root, backend,
                        allow_dispatch=True, assignee="approved-profile", workspace="worktree:/tmp/repo",
                    )

            restarted_backend = FakeKanban(backend.store)
            state = adapter.accept_mission(
                self.document, state_root, restarted_backend,
                allow_dispatch=True, assignee="approved-profile", workspace="worktree:/tmp/repo",
            )
            self.assertEqual(2, restarted_backend.create_calls)
            self.assertEqual(1, len(restarted_backend.tasks))
            self.assertEqual("task-1", state["root_task_id"])

    def test_restart_replay_converges_with_correlated_delivery_events(self):
        backend = FakeKanban()
        sink = DeduplicatingCentralSink()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            state = adapter.accept_mission(self.document, state_root, backend)
            task_id = state["root_task_id"]
            backend.tasks[task_id] = {
                "task": {
                    "id": task_id, "title": "Implement", "status": "done",
                    "assignee": "approved-profile",
                },
                "runs": [{
                    "id": 7,
                    "profile": "approved-profile",
                    "status": "completed",
                    "outcome": "success",
                    "metadata": {
                        "mission_events": [
                            {"type": "change.upsert", "payload": {
                                "path": "src/lib.rs", "status": "modified",
                            }},
                            {"type": "gate.upsert", "payload": {
                                "gate_id": "tests", "status": "passed",
                            }},
                            {"type": "gate.upsert", "payload": {
                                "gate_id": "review", "status": "passed",
                            }},
                            {"type": "delivery.upsert", "payload": {
                                "kind": "pull_request", "status": "merged",
                                "url": "https://example.invalid/pr/1",
                            }},
                            {"type": "delivery.upsert", "payload": {
                                "kind": "deploy", "status": "verified",
                                "url": "https://example.invalid/deploy/1",
                            }},
                        ]
                    },
                }],
            }
            backend.logs[task_id] = "tests running\nall green\n"

            first = adapter.sync_mission(self.document["mission_id"], state_root, backend)
            sink.append(first)
            unique_count = len(sink.events)

            restarted_backend = FakeKanban(backend.store)
            restarted = adapter.sync_mission(self.document["mission_id"], state_root, restarted_backend)
            sink.append(restarted)
            self.assertEqual(unique_count, len(sink.events))
            self.assertEqual([event["type"] for event in first], [event["type"] for event in restarted])

            retry = copy.deepcopy(backend.tasks[task_id]["runs"][0])
            retry["id"] = 8
            backend.tasks[task_id]["runs"].append(retry)
            retry_events = adapter.sync_mission(self.document["mission_id"], state_root, backend)
            self.assertEqual(
                len(retry_events),
                len({event["correlation"]["producer_event_id"] for event in retry_events}),
            )
            sink.append(retry_events)

            event_types = [event["type"] for event in sink.events.values()]
            self.assertEqual(1, event_types.count("task.upsert"))
            self.assertEqual(2, event_types.count("worker.upsert"))
            self.assertEqual(2, event_types.count("terminal.append"))
            self.assertEqual(1, event_types.count("change.upsert"))
            self.assertEqual(2, event_types.count("gate.upsert"))
            self.assertEqual(2, event_types.count("delivery.upsert"))
            self.assertTrue(all(
                event["correlation"].get("task_id") == task_id for event in sink.events.values()
            ))

    def test_real_backend_is_shell_free_idempotent_and_dispatch_gated(self):
        commands = []

        def runner(command):
            commands.append(command)
            return subprocess.CompletedProcess(
                command, 0,
                stdout=json.dumps({"id": "task-1", "status": "blocked"}),
                stderr="",
            )

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        backend.ensure_root(
            mission_id="mission-1", goal="Goal", allow_dispatch=False,
            assignee=None, workspace=None,
        )
        command = commands[0]
        self.assertEqual("/opt/hermes", command[0])
        self.assertIn("central-mission:mission-1", command)
        self.assertEqual("blocked", command[command.index("--initial-status") + 1])
        self.assertNotIn("--assignee", command)
        with self.assertRaisesRegex(adapter.AdapterError, "non-scratch workspace"):
            backend.ensure_root(
                mission_id="mission-2", goal="Goal", allow_dispatch=True,
                assignee="approved-profile", workspace="scratch",
            )

    def test_worker_cannot_publish_terminal_mission_event(self):
        with self.assertRaisesRegex(adapter.AdapterError, "not allowed"):
            adapter._worker_metadata_events(
                "mission-1", "task-1", "worker-1",
                {"mission_events": [{
                    "type": "mission.completed", "payload": {"result": "forged"},
                }]},
            )


if __name__ == "__main__":
    unittest.main()
