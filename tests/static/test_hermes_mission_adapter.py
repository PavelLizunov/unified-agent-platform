#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import time
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
                    "title": f"Mission {mission_id}",
                    "status": "ready" if allow_dispatch else "blocked",
                    "assignee": assignee if allow_dispatch else None,
                    "created_by": "central-hermes",
                    "tenant": mission_id,
                },
                "runs": [],
            }
        return copy.deepcopy(self.tasks[self.store["by_key"][key]]["task"])

    def list_task_ids(self, mission_id):
        return sorted(self.tasks)

    def list_tasks(self, mission_id):
        return [copy.deepcopy(self.tasks[task_id]["task"]) for task_id in sorted(self.tasks)]

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


class FakeCentral:
    def __init__(self, dispatch_profile="build1-uap"):
        self.mission = {
            "mission_id": "mission-auto",
            "status": "active",
            "stage": "accepted",
            "goal": "Implement the safe change",
            "dispatch_profile": dispatch_profile,
            "tasks": [],
        }
        self.events = {}
        self.fail_publish_once = False
        self.fail_after_commit_once = False
        self.requested_profiles = []

    def list_missions(self, dispatch_profile, *, reconcile=False):
        self.requested_profiles.append(dispatch_profile)
        if self.mission["dispatch_profile"] != dispatch_profile:
            return []
        if bool(self.mission["tasks"]) != reconcile:
            return []
        return [copy.deepcopy(self.mission)]

    def publish(self, mission_id, event):
        if self.fail_publish_once:
            self.fail_publish_once = False
            raise adapter.AdapterError("simulated crash before central commit")
        self.assert_mission(mission_id)
        producer_id = event["correlation"]["producer_event_id"]
        if producer_id not in self.events:
            self.events[producer_id] = copy.deepcopy(event)
            if event["type"] == "task.upsert":
                self.mission["tasks"] = [copy.deepcopy(event["payload"])]
        if self.fail_after_commit_once:
            self.fail_after_commit_once = False
            raise adapter.AdapterError("simulated lost response after central commit")

    def assert_mission(self, mission_id):
        if mission_id != self.mission["mission_id"]:
            raise AssertionError("wrong mission")


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
            if os.name == "posix":
                self.assertEqual(0o700, state_root.stat().st_mode & 0o777)

    def test_native_archive_is_idempotent_and_gc_requires_atomic_idle_board(self):
        calls = []
        statuses = iter(("done", "archived", "archived"))

        def runner(command):
            calls.append(command)
            if "show" in command:
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=json.dumps({"task": {"id": "task-1", "status": next(statuses)}}),
                    stderr="",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="GC complete: 0 workspace(s), 0 event row(s), 0 log file(s) removed\n",
                stderr="",
            )

        backend = adapter.HermesKanbanBackend("hermes", "default", runner)
        self.assertEqual("archived", backend.archive("task-1")["task"]["status"])
        self.assertEqual("archived", backend.archive("task-1")["task"]["status"])
        self.assertTrue(backend.gc())
        self.assertEqual(1, sum("archive" in command for command in calls))
        self.assertEqual(1, sum("gc" in command for command in calls))
        self.assertEqual(["gc", "--require-idle"], calls[-1][-2:])

        def active_runner(command):
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout="GC deferred: board is not idle\n", stderr=""
            )

        self.assertFalse(adapter.HermesKanbanBackend(
            "hermes", "default", active_runner
        ).gc())
        self.assertEqual(2, sum("gc" in command for command in calls))

        def invalid_runner(command):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with self.assertRaisesRegex(adapter.AdapterError, "invalid GC result"):
            adapter.HermesKanbanBackend(
                "hermes", "default", invalid_runner
            ).gc()

        def failed_runner(command):
            return subprocess.CompletedProcess(
                command, 1, stdout="GC deferred: board is not idle\n", stderr="failed"
            )

        with self.assertRaisesRegex(adapter.AdapterError, "failed"):
            adapter.HermesKanbanBackend("hermes", "default", failed_runner).gc()

    def test_restart_replay_converges_with_correlated_delivery_events(self):
        backend = FakeKanban()
        sink = DeduplicatingCentralSink()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            state = adapter.accept_mission(self.document, state_root, backend)
            task_id = state["root_task_id"]
            backend.tasks[task_id] = {
                "task": {
                    "id": task_id, "title": f"Mission {self.document['mission_id']}", "status": "done",
                    "assignee": "approved-profile",
                    "created_by": "central-hermes", "tenant": self.document["mission_id"],
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
        active_created = False

        def runner(command):
            nonlocal active_created
            commands.append(command)
            action = command[command.index("central") + 1]
            active = "--initial-status" in command and command[command.index("--initial-status") + 1] == "running"
            active_created = active_created or active
            return subprocess.CompletedProcess(
                command, 0,
                stdout=json.dumps(
                    {"id": "task-1", "status": "ready" if active else "blocked"}
                    if action == "create"
                    else {
                        "task": {
                            "id": "task-1", "status": "ready" if active_created else "blocked",
                            "assignee": "approved-profile" if active_created else None,
                        },
                        "events": [{"kind": "created"}] + ([] if active_created else [{"kind": "blocked"}]),
                        "runs": [],
                    }
                ),
                stderr="",
            )

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        task = backend.ensure_root(
            mission_id="mission-1", goal="Goal", allow_dispatch=False,
            assignee=None, workspace=None,
        )
        command = commands[0]
        self.assertEqual("/opt/hermes", command[0])
        self.assertIn("central-mission:mission-1", command)
        self.assertEqual("blocked", command[command.index("--initial-status") + 1])
        self.assertNotIn("--assignee", command)
        self.assertEqual("blocked", task["status"])
        backend.ensure_root(
            mission_id="mission-1", goal="Goal", allow_dispatch=False,
            assignee=None, workspace=None,
        )
        self.assertEqual([], [item for item in commands if "block" in item])
        with self.assertRaisesRegex(adapter.AdapterError, "non-scratch workspace"):
            backend.ensure_root(
                mission_id="mission-2", goal="Goal", allow_dispatch=True,
                assignee="approved-profile", workspace="scratch",
            )
        backend.ensure_root(
            mission_id="mission-2", goal="Goal", allow_dispatch=True,
            assignee="approved-profile", workspace="worktree:/tmp/repo",
        )
        active_command = next(command for command in reversed(commands) if "--initial-status" in command)
        self.assertEqual("running", active_command[active_command.index("--initial-status") + 1])

    def test_worker_cannot_publish_terminal_mission_event(self):
        with self.assertRaisesRegex(adapter.AdapterError, "not allowed"):
            adapter._worker_metadata_events(
                "mission-1", "task-1", "worker-1",
                {"mission_events": [{
                    "type": "mission.completed", "payload": {"result": "forged"},
                }]},
            )

    def test_owner_answer_resume_is_idempotent_and_keeps_text_off_argv(self):
        commands = []
        state = {
            "status": "blocked",
            "assignee": None,
            "events": [{"kind": "created"}, {"kind": "blocked"}],
        }

        def runner(command):
            commands.append(command)
            action = command[command.index("central") + 1]
            if action == "assign":
                state["assignee"] = command[-1]
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if action == "unblock":
                state["status"] = "ready"
                reason = command[command.index("--reason") + 1]
                state["events"].append({
                    "kind": "unblocked",
                    "payload": {"reason": reason},
                })
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if action == "show":
                output = {
                    "task": {
                        "id": "task-1",
                        "status": state["status"],
                        "assignee": state["assignee"],
                        "workspace_kind": "worktree",
                        "workspace_path": "/tmp/repo",
                    },
                    "events": list(state["events"]),
                    "runs": [],
                }
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(output), stderr=""
                )
            raise AssertionError(command)

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        digest = hashlib.sha256(b"private owner answer").hexdigest()
        first = backend.resume_root_from_answer(
            "task-1",
            assignee="approved-profile",
            workspace="worktree:/tmp/repo",
            question_id="q-product",
            answer_digest=digest,
        )
        self.assertEqual("ready", first["task"]["status"])
        self.assertEqual("approved-profile", first["task"]["assignee"])
        self.assertFalse(any("private owner answer" in argument for command in commands for argument in command))
        first_unblocks = sum("unblock" in command for command in commands)

        backend.resume_root_from_answer(
            "task-1",
            assignee="approved-profile",
            workspace="worktree:/tmp/repo",
            question_id="q-product",
            answer_digest=digest,
        )
        self.assertEqual(first_unblocks, sum("unblock" in command for command in commands))

    def test_owner_answer_resume_rejects_unrelated_unblock(self):
        digest = hashlib.sha256(b"private owner answer").hexdigest()

        def runner(command):
            action = command[command.index("central") + 1]
            if action != "show":
                raise AssertionError(command)
            output = {
                "task": {
                    "id": "task-1",
                    "status": "ready",
                    "assignee": "approved-profile",
                    "workspace_kind": "worktree",
                    "workspace_path": "/tmp/repo",
                },
                "events": [
                    {"kind": "created"},
                    {"kind": "blocked"},
                    {"kind": "unblocked", "payload": {"reason": "manual-recovery"}},
                ],
                "runs": [],
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(output), stderr=""
            )

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        with self.assertRaisesRegex(adapter.AdapterError, "exact durable"):
            backend.resume_root_from_answer(
                "task-1",
                assignee="approved-profile",
                workspace="worktree:/tmp/repo",
                question_id="q-product",
                answer_digest=digest,
            )

    def test_native_claim_and_completion_are_fail_closed(self):
        commands = []

        def runner(command):
            commands.append(command)
            action = command[command.index("central") + 1]
            if action == "show":
                output = {
                    "task": {"id": "task-1", "status": "done" if any("complete" in item for item in commands) else "running"},
                    "runs": [
                        {"id": 8, "status": "scheduled"},
                        {"id": 9, "status": "completed" if any("complete" in item for item in commands) else "running"},
                    ],
                }
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(output), stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        claimed = backend.claim("task-1", ttl_seconds=60)
        self.assertEqual("running", claimed["task"]["status"])
        completed = backend.complete(
            "task-1", result="success", summary="done", metadata={"mission_events": []}
        )
        self.assertEqual("done", completed["task"]["status"])
        self.assertTrue(all(isinstance(command, list) for command in commands))
        complete_command = next(command for command in commands if "complete" in command)
        self.assertIn("--metadata", complete_command)

    def test_native_capacity_schedule_and_unblock_are_fail_closed(self):
        commands = []
        status = "running"

        def runner(command):
            nonlocal status
            commands.append(command)
            action = command[command.index("central") + 1]
            if action == "schedule":
                status = "scheduled"
            elif action == "unblock":
                status = "ready"
            output = {
                "task": {"id": "task-1", "status": status},
                "runs": [{"id": 9, "status": "running" if status == "running" else "scheduled"}],
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(output) if action == "show" else "", stderr=""
            )

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        self.assertEqual(
            "scheduled",
            backend.schedule("task-1", reason="automatic capacity cooldown")["task"]["status"],
        )
        self.assertEqual(
            "ready",
            backend.unblock("task-1", reason="automatic capacity retry")["task"]["status"],
        )
        self.assertTrue(any("schedule" in command for command in commands))
        self.assertTrue(any("unblock" in command for command in commands))

    def test_native_claim_verification_rejects_expired_or_wrong_run(self):
        expires = int(time.time()) + 600
        event_run_id = 9

        def runner(command):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({
                    "task": {
                        "id": "task-1",
                        "status": "running",
                    },
                    "runs": [{
                        "id": 9,
                        "status": "running",
                    }],
                    "events": [{
                        "kind": "claimed",
                        "payload": {
                            "lock": "build-1:123",
                            "expires": expires,
                            "run_id": 9,
                        },
                        "run_id": event_run_id,
                    }],
                }),
                stderr="",
            )

        backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
        self.assertEqual(
            "running",
            backend.verify_claim("task-1", "9", min_remaining_seconds=60)["task"]["status"],
        )
        with self.assertRaisesRegex(adapter.AdapterError, "stale, or expired"):
            backend.verify_claim("task-1", "other", min_remaining_seconds=60)

        event_run_id = 99
        with self.assertRaisesRegex(adapter.AdapterError, "stale, or expired"):
            backend.verify_claim("task-1", "9", min_remaining_seconds=60)

        event_run_id = 9
        expires = int(time.time()) - 1
        with self.assertRaisesRegex(adapter.AdapterError, "stale, or expired"):
            backend.verify_claim("task-1", "9", min_remaining_seconds=60)

    def test_safe_backend_rejects_malformed_final_native_state(self):
        cases = {
            "missing-assignee": {
                "task": {"id": "task-1", "status": "blocked"},
                "events": [{"kind": "blocked"}], "runs": [],
            },
            "missing-id": {
                "task": {"status": "blocked", "assignee": None},
                "events": [{"kind": "blocked"}], "runs": [],
            },
            "mismatched-id": {
                "task": {"id": "task-other", "status": "blocked", "assignee": None},
                "events": [{"kind": "blocked"}], "runs": [],
            },
            "malformed-runs": {
                "task": {"id": "task-1", "status": "blocked", "assignee": None},
                "events": [{"kind": "blocked"}], "runs": None,
            },
            "missing-sticky-block": {
                "task": {"id": "task-1", "status": "blocked", "assignee": None},
                "events": [{"kind": "created"}], "runs": [],
            },
            "ready": {
                "task": {"id": "task-1", "status": "ready", "assignee": None},
                "events": [{"kind": "blocked"}], "runs": [],
            },
        }
        for name, malformed in cases.items():
            with self.subTest(name=name):
                def runner(command):
                    action = command[command.index("central") + 1]
                    if action == "create":
                        output = {"id": "task-1", "status": "blocked"}
                    else:
                        output = malformed
                    return subprocess.CompletedProcess(
                        command, 0, stdout=json.dumps(output), stderr=""
                    )

                backend = adapter.HermesKanbanBackend("/opt/hermes", "central", runner=runner)
                with self.assertRaises(adapter.AdapterError):
                    backend.ensure_root(
                        mission_id="mission-malformed", goal="Goal", allow_dispatch=False,
                        assignee=None, workspace=None,
                    )

    def test_worker_metadata_rejects_unknown_payload_fields(self):
        with self.assertRaisesRegex(adapter.AdapterError, "payload is invalid"):
            adapter._worker_metadata_events(
                "mission-1", "task-1", "worker-1",
                {"mission_events": [{
                    "type": "change.upsert",
                    "payload": {
                        "path": "src/lib.rs",
                        "status": "modified",
                        "details": "arbitrary producer data",
                    },
                }]},
            )

    @unittest.skipUnless(os.name == "posix", "POSIX mode invariant")
    def test_adapter_state_is_owner_only(self):
        backend = FakeKanban()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            mission_dir = adapter._mission_dir(state_root, self.document["mission_id"])
            mission_dir.mkdir(mode=0o777)
            os.chmod(mission_dir, 0o777)
            adapter.accept_mission(self.document, state_root, backend)
            state_path = adapter._state_path(state_root, self.document["mission_id"])
            self.assertEqual(0o700, stat.S_IMODE(state_path.parent.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(state_path.stat().st_mode))

    def test_pull_dispatch_recovers_after_task_create_before_publish(self):
        backend = FakeKanban()
        central = FakeCentral()
        central.fail_publish_once = True
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            with self.assertRaisesRegex(adapter.AdapterError, "simulated crash"):
                adapter.dispatch_pending(
                    central,
                    state_root,
                    backend,
                    dispatch_profile="build1-uap",
                    workspace="worktree:/tmp/repo",
                )

            restarted_backend = FakeKanban(backend.store)
            result = adapter.dispatch_pending(
                central,
                state_root,
                restarted_backend,
                dispatch_profile="build1-uap",
                workspace="worktree:/tmp/repo",
            )
            self.assertEqual("task-1", result["root_task_id"])
            self.assertEqual(2, restarted_backend.create_calls)
            self.assertEqual(1, len(restarted_backend.tasks))
            self.assertEqual(1, len(central.events))
            self.assertEqual(1, len(central.mission["tasks"]))
            self.assertEqual(["build1-uap", "build1-uap"], central.requested_profiles)
            self.assertEqual("blocked", restarted_backend.tasks["task-1"]["task"]["status"])
            self.assertIsNone(restarted_backend.tasks["task-1"]["task"]["assignee"])

            self.assertIsNone(adapter.dispatch_pending(
                central,
                state_root,
                restarted_backend,
                dispatch_profile="build1-uap",
                workspace="worktree:/tmp/repo",
            ))
            self.assertEqual(2, restarted_backend.create_calls)

    def test_pull_activation_requires_explicit_assignee(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(adapter.AdapterError, "activation requires an assignee"):
                adapter.dispatch_pending(
                    FakeCentral(), pathlib.Path(directory), FakeKanban(),
                    dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
                    activate=True,
                )

    def test_pull_converges_when_central_response_is_lost_after_commit(self):
        backend = FakeKanban()
        central = FakeCentral()
        central.fail_after_commit_once = True
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            with self.assertRaisesRegex(adapter.AdapterError, "lost response"):
                adapter.dispatch_pending(
                    central, state_root, backend,
                    dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
                )

            self.assertIsNone(adapter.dispatch_pending(
                central, state_root, backend,
                dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
            ))
            self.assertEqual(1, backend.create_calls)
            self.assertEqual(1, len(backend.tasks))
            self.assertEqual(1, len(central.events))
            self.assertEqual(1, len(central.mission["tasks"]))

    def test_reconcile_recovers_deleted_state_and_partial_multi_event_publish(self):
        backend = FakeKanban()
        central = FakeCentral()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            dispatched = adapter.dispatch_pending(
                central, state_root, backend,
                dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
            )
            task_id = dispatched["root_task_id"]
            backend.tasks[task_id]["task"].update(status="done", assignee="approved-profile")
            backend.tasks[task_id]["runs"] = [{
                "id": 1,
                "profile": "approved-profile",
                "status": "completed",
                "outcome": "success",
                "metadata": {"mission_events": [{
                    "type": "gate.upsert",
                    "payload": {"gate_id": "tests", "status": "passed"},
                }]},
            }]
            backend.logs[task_id] = "work complete\n"
            adapter._state_path(state_root, "mission-auto").unlink()

            original_publish = central.publish
            calls = 0

            def fail_after_first_event(mission_id, event):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise adapter.AdapterError("simulated partial publish")
                original_publish(mission_id, event)

            central.publish = fail_after_first_event
            with self.assertRaisesRegex(adapter.AdapterError, "partial publish"):
                adapter.reconcile_pending(
                    central, state_root, backend, dispatch_profile="build1-uap"
                )

            self.assertTrue(adapter._state_path(state_root, "mission-auto").is_file())
            central.publish = original_publish
            result = adapter.reconcile_pending(
                central, state_root, backend, dispatch_profile="build1-uap"
            )
            self.assertEqual(task_id, result["root_task_id"])
            self.assertEqual(
                {"task.upsert", "worker.upsert", "terminal.append", "gate.upsert"},
                {event["type"] for event in central.events.values()},
            )
            self.assertEqual(1, len(backend.tasks))
            self.assertEqual(1, backend.create_calls)

    def test_reconcile_rejects_ambiguous_native_root(self):
        backend = FakeKanban()
        central = FakeCentral()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            adapter.dispatch_pending(
                central, state_root, backend,
                dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
            )
            duplicate = copy.deepcopy(backend.tasks["task-1"])
            duplicate["task"]["id"] = "task-2"
            backend.tasks["task-2"] = duplicate
            with self.assertRaisesRegex(adapter.AdapterError, "one exact Kanban root"):
                adapter.reconcile_pending(
                    central, state_root, backend, dispatch_profile="build1-uap"
                )

    def test_coordinator_tick_reconciles_before_dispatch(self):
        backend = FakeKanban()
        central = FakeCentral()
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory)
            first = adapter.coordinator_tick(
                central, state_root, backend,
                dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
            )
            self.assertEqual("dispatched", first["action"])
            self.assertEqual(1, backend.create_calls)

            central.mission["status"] = "waiting_owner"
            second = adapter.coordinator_tick(
                central, state_root, backend,
                dispatch_profile="build1-uap", workspace="worktree:/tmp/repo",
            )
            self.assertEqual("reconciled", second["action"])
            self.assertEqual(1, backend.create_calls)
            self.assertEqual(1, len(central.events))

    def test_central_client_keeps_credentials_in_headers(self):
        listing = mock.MagicMock()
        listing.__enter__.return_value.read.return_value = b'{"missions": []}'
        reconciling = mock.MagicMock()
        reconciling.__enter__.return_value.read.return_value = b'{"missions": []}'
        accepted = mock.MagicMock()
        accepted.__enter__.return_value.read.return_value = (
            b'{"mission":{"mission_id":"repair-1","goal":"Repair",'
            b'"dispatch_profile":"build1-repair","parent_mission_id":"mission-1"}}'
        )
        published = mock.MagicMock()
        published.__enter__.return_value.read.return_value = b'{"created": true}'
        opener = mock.MagicMock()
        opener.open.side_effect = [listing, reconciling, accepted, published]
        with mock.patch.object(
            adapter.urllib.request, "build_opener", return_value=opener
        ) as build_opener:
            client = adapter.CentralMissionClient(
                "http://central.example:30642",
                "api-token",
                "producer-key",
            )
            self.assertEqual([], client.list_missions("build1-uap"))
            self.assertEqual([], client.list_missions("build1-uap", reconcile=True))
            self.assertEqual(
                "repair-1",
                client.accept_mission(
                    mission_id="repair-1",
                    goal="Repair",
                    dispatch_profile="build1-repair",
                    parent_mission_id="mission-1",
                )["mission_id"],
            )
            client.publish("mission-1", {"type": "task.upsert"})

        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual({}, proxy_handler.proxies)
        first_request = opener.open.call_args_list[0].args[0]
        reconcile_request = opener.open.call_args_list[1].args[0]
        accept_request = opener.open.call_args_list[2].args[0]
        second_request = opener.open.call_args_list[3].args[0]
        first_headers = {key.lower(): value for key, value in first_request.header_items()}
        second_headers = {key.lower(): value for key, value in second_request.header_items()}
        self.assertEqual("Bearer api-token", first_headers["authorization"])
        self.assertEqual("producer-key", second_headers["x-hermes-mission-producer-key"])
        self.assertEqual("POST", accept_request.method)
        self.assertEqual("/api/missions", adapter.urllib.parse.urlsplit(accept_request.full_url).path)
        self.assertEqual(
            {
                "mission_id": "repair-1",
                "goal": "Repair",
                "dispatch_profile": "build1-repair",
                "parent_mission_id": "mission-1",
            },
            json.loads(accept_request.data),
        )
        self.assertIn("dispatch_profile=build1-uap", first_request.full_url)
        self.assertIn("limit=1", first_request.full_url)
        self.assertNotIn("reconcile=1", first_request.full_url)
        self.assertIn("reconcile=1", reconcile_request.full_url)
        self.assertNotIn("api-token", first_request.full_url)
        self.assertNotIn("producer-key", second_request.full_url)


if __name__ == "__main__":
    unittest.main()
