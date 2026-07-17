#!/usr/bin/env python3
"""Hermetic A7.3 delivery coordinator crash/restart gate."""

from __future__ import annotations

import importlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "swarm"))
coordinator = importlib.import_module("delivery_coordinator")
installer = importlib.import_module("install_flow_v2")


def profile(root: pathlib.Path) -> dict:
    return {
        "schema_version": 3,
        "dispatch_profile": "build1-vpnrouter-a7-3",
        "goal": "Fix issue 39",
        "repo": "PavelLizunov/VPNRouter",
        "remote": "https://github.com/PavelLizunov/VPNRouter.git",
        "source_checkout": str(root / "source"),
        "default_branch": "main",
        "worktree_root": str(root / "worktrees"),
        "branch_prefix": "codex/a7-3-vpnrouter",
        "assignee": "coordinator-codex-luna-a7",
        "required_files": [
            "Cli.cs", "Config.cs", "Core.cs", "Runtime.cs", "Tests.cs", "WindowsTests.cs"
        ],
        "author_checks": [["dotnet", "test"]],
        "review_checks": [["dotnet", "test"]],
        "post_verify_checks": [["dotnet", "test"], ["windows-brat", "status"]],
        "required_ci_checks": ["test"],
        "commit_message": "fix(cli): detect active runtime",
        "pull_request_title": "fix(cli): report active runtime",
        "pull_request_body": "Closes #39",
        "max_review_cycles": 3,
        "claim_ttl_seconds": 28800,
        "command_timeout_seconds": 900,
        "ci_timeout_seconds": 900,
        "crash_after_author_commit_once": True,
    }


def dirty_git_checkout(checkout: pathlib.Path, files: list[str], branch: str) -> str:
    checkout.mkdir(parents=True)
    for command in (
        ["git", "init", "-b", branch],
        ["git", "config", "user.name", "Test"],
        ["git", "config", "user.email", "test@example.invalid"],
    ):
        subprocess.run(command, cwd=checkout, check=True, capture_output=True, text=True)
    for name in files:
        (checkout / name).write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=checkout, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=checkout, check=True, capture_output=True, text=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout, check=True, capture_output=True, text=True,
    ).stdout.strip()
    for name in files:
        (checkout / name).write_text("first turn\n", encoding="utf-8")
    return base_sha


class FakeClient:
    def __init__(self):
        self.mission = {
            "mission_id": "mission-a7-3",
            "goal": "Fix issue 39",
            "dispatch_profile": "build1-vpnrouter-a7-3",
            "status": "active",
            "stage": "accepted",
            "tasks": [],
        }
        self.stages = []
        self.hide_terminal = False

    def list_missions(self, _profile, *, reconcile=False):
        if self.hide_terminal:
            return []
        return [self.mission] if reconcile else ([] if self.mission["tasks"] else [self.mission])

    def publish(self, _mission_id, event):
        self.stages.append(event)

    def get_mission(self, _mission_id):
        return {**self.mission, "status": "completed"}


class FakeBackend:
    def __init__(self):
        self.task = {
            "id": "task-1", "status": "ready", "assignee": "coordinator-codex-luna-a7"
        }
        self.runs = []
        self.claims = 0
        self.archives = 0
        self.gcs = 0

    def show(self, _task_id):
        return {"task": dict(self.task), "runs": [dict(run) for run in self.runs]}

    def claim(self, _task_id, *, ttl_seconds):
        assert ttl_seconds == 28800
        self.claims += 1
        expires = int(time.time()) + ttl_seconds
        self.task.update(status="running", claim_expires=expires)
        self.runs = [{
            "id": 7,
            "status": "running",
            "profile": "coordinator-codex-luna-a7",
            "claim_expires": expires,
        }]
        return self.show("task-1")

    def verify_claim(self, task_id, run_id, *, min_remaining_seconds=60):
        snapshot = self.show(task_id)
        matching = [run for run in snapshot["runs"] if str(run["id"]) == str(run_id)]
        minimum = int(time.time()) + min_remaining_seconds
        if (
            snapshot["task"].get("status") != "running"
            or snapshot["task"].get("claim_expires", 0) <= minimum
            or len(matching) != 1
            or matching[0].get("status") != "running"
            or matching[0].get("claim_expires", 0) <= minimum
        ):
            raise coordinator.mission_adapter.AdapterError("stale claim")
        return snapshot

    def complete(self, _task_id, **_kwargs):
        self.task.update(status="done", result=_kwargs["result"])
        self.runs[0].update(
            status="done",
            outcome="completed",
            summary=_kwargs["summary"],
            metadata=_kwargs["metadata"],
        )
        return self.show("task-1")

    def archive(self, _task_id):
        self.archives += 1
        self.task["status"] = "archived"
        return self.show("task-1")

    def gc(self):
        self.gcs += 1
        return True

    def edit_metadata(self, _task_id, **_kwargs):
        return self.show("task-1")

    def read_log(self, _task_id):
        return ""


class OwnerAnswerClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.mission.update(
            status="waiting_owner",
            question={"question_id": "q-product", "text": "Preserve current behavior?"},
            answer=None,
        )

    def list_missions(self, _profile, *, reconcile=False):
        has_tasks = bool(self.mission["tasks"])
        return [self.mission] if reconcile == has_tasks else []

    def publish(self, _mission_id, event):
        super().publish(_mission_id, event)
        if event.get("type") == "task.upsert":
            self.mission["tasks"] = [dict(event["payload"])]

    def get_mission(self, _mission_id):
        return dict(self.mission)

    def answer(self, text="Keep the existing behavior"):
        self.mission.update(
            status="active",
            question=None,
            answer={"question_id": "q-product", "text": text},
        )


class OwnerAnswerBackend(FakeBackend):
    def __init__(self, failure_point):
        super().__init__()
        self.task = None
        self.events = []
        self.failure_point = failure_point
        self.resume_calls = 0

    def ensure_root(self, *, mission_id, goal, allow_dispatch, assignee, workspace):
        assert not allow_dispatch and assignee is None and workspace.startswith("worktree:")
        if self.task is None:
            self.task = {
                "id": "task-1",
                "title": f"Mission {mission_id}",
                "status": "blocked",
                "assignee": None,
                "created_by": "central-hermes",
                "tenant": mission_id,
                "workspace_kind": "worktree",
                "workspace_path": workspace.removeprefix("worktree:"),
            }
            self.events = [{"kind": "created"}, {"kind": "blocked"}]
        return dict(self.task)

    def list_tasks(self, _mission_id):
        return [] if self.task is None else [dict(self.task)]

    def list_task_ids(self, _mission_id):
        return [] if self.task is None else [self.task["id"]]

    def show(self, _task_id):
        assert self.task is not None
        return {
            "task": dict(self.task),
            "events": [dict(event) for event in self.events],
            "runs": [dict(run) for run in self.runs],
        }

    def resume_root_from_answer(self, task_id, **kwargs):
        self.resume_calls += 1
        if self.failure_point == "before":
            self.failure_point = None
            raise coordinator.mission_adapter.AdapterError("crash before Kanban update")
        assert self.task is not None and self.task["id"] == task_id
        assert kwargs["question_id"] == "q-product"
        assert kwargs["workspace"] == f"worktree:{self.task['workspace_path']}"
        if self.task["status"] == "blocked":
            self.task.update(status="ready", assignee=kwargs["assignee"])
            reference = (
                f"owner-answer:{kwargs['question_id']}:"
                f"{kwargs['answer_digest'][:16]}"
            )
            self.events.append({
                "kind": "unblocked",
                "payload": {"reason": reference},
            })
        if self.failure_point == "after":
            self.failure_point = None
            raise coordinator.mission_adapter.AdapterError("crash after Kanban update")
        return self.show(task_id)

    def claim(self, task_id, *, ttl_seconds):
        assert self.task is not None
        return super().claim(task_id, ttl_seconds=ttl_seconds)


class MutatingCompletionBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.show_calls = 0
        self.mutate_on_show = None

    def show(self, task_id):
        self.show_calls += 1
        if self.show_calls == self.mutate_on_show:
            self.runs[0]["metadata"] = {"mission_events": []}
        return super().show(task_id)


class LostCompleteResponseBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.fail_after_complete_once = True

    def complete(self, task_id, **kwargs):
        snapshot = super().complete(task_id, **kwargs)
        if self.fail_after_complete_once:
            self.fail_after_complete_once = False
            raise coordinator.mission_adapter.AdapterError("lost completion response")
        return snapshot


class RejectionBackend(LostCompleteResponseBackend):
    def list_tasks(self, mission_id):
        return [{
            **self.task,
            "title": f"Mission {mission_id}",
            "created_by": "central-hermes",
            "tenant": mission_id,
        }]

    def read_log(self, _task_id):
        return "review rejected\n"


class RejectionClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.mission["tasks"] = [{"task_id": "task-1"}]

    def list_missions(self, _profile, *, reconcile=False):
        if self.mission["status"] != "active":
            return []
        return [self.mission] if reconcile else []

    def publish(self, _mission_id, event):
        if self.mission["status"] != "active":
            raise coordinator.mission_adapter.AdapterError("mission is terminal")
        self.stages.append(event)
        gates = {
            item["payload"]["gate_id"]: item["payload"]["status"]
            for item in self.stages
            if item.get("type") == "gate.upsert"
        }
        if gates in (
            {"tests": "passed", "review": "failed", "cleanup": "passed"},
            {"tests": "failed", "cleanup": "passed"},
            {"tests": "passed", "review": "passed", "ci": "failed", "cleanup": "passed"},
        ):
            self.mission["status"] = "failed"

    def get_mission(self, _mission_id):
        return dict(self.mission)


class HermeticCoordinator(coordinator.DeliveryCoordinator):
    def __init__(self, *args, counters: dict, **kwargs):
        super().__init__(*args, **kwargs)
        self.counters = counters

    def _ensure_worktree(self, state, paths):
        if not paths["author"].exists():
            self.counters["worktrees"] += 1
            paths["author"].mkdir(parents=True)
        state.setdefault("base_sha", "base-sha")

    def _git(self, _checkout, *arguments, **_kwargs):
        if arguments[:2] == ("rev-parse", "HEAD"):
            return "candidate-sha"
        return ""

    def _author(self, state, paths):
        self.counters["authors"] += 1
        state.update(
            phase="author_committed",
            candidate_sha="candidate-sha",
            author_summary={},
            author_telemetry={},
        )
        self._save(paths, state)

    def _recover_author_commit(self, state, paths):
        return False

    def _publish_stage(self, state, stage, progress):
        self.client.stages.append((state["mission_id"], stage, progress))

    def _reconcile(self, **_kwargs):
        return None

    def _review(self, state, paths):
        self.counters["reviews"] += 1
        state.update(phase="reviewed", review_verification={}, reviewer_telemetry={})
        self._save(paths, state)
        return True

    def _pr(self, state, paths):
        state.update(phase="pr_open", pr_number=39, pr_url="https://example.invalid/pr/39")
        self._save(paths, state)

    def _wait_ci(self, state):
        state["ci_checks"] = [{"conclusion": "SUCCESS"}]

    def _validate_review(self, state):
        return None

    def _merge(self, state):
        state["merge_sha"] = "merge-sha"

    def _post_verify(self, state, paths):
        state.update(default_sha="default-sha", post_verify_checks=[])

    def _cleanup(self, state, paths, *, preserve_remote=False):
        self.counters["cleanups"] += 1
        for name in ("author", "review", "verify"):
            if paths[name].exists():
                paths[name].rmdir()


class TickReviewCoordinator(HermeticCoordinator):
    _review = coordinator.DeliveryCoordinator._review

    def _publish_stage(self, _state, _stage, _progress):
        return None

    def _reconcile(self, *, before_publish=None, event_source=None):
        if event_source is None or self.client.mission["status"] != "active":
            return
        mission_id = self.client.mission["mission_id"]
        adapter_state = {"root_task_id": self.backend.task["id"]}
        for event in event_source(mission_id, adapter_state):
            if before_publish is not None:
                before_publish(mission_id, event)
            self.client.publish(mission_id, event)


class RepairClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.children = {}
        self.accept_calls = 0
        self.lose_first_accept_response = True

    def accept_mission(self, **document):
        self.accept_calls += 1
        child = self.children.setdefault(
            document["mission_id"],
            {
                **document,
                "status": "active",
                "stage": "accepted",
                "tasks": [],
            },
        )
        if self.lose_first_accept_response:
            self.lose_first_accept_response = False
            raise coordinator.mission_adapter.AdapterError("lost child accept response")
        return dict(child)

    def get_mission(self, mission_id):
        if mission_id in self.children:
            return dict(self.children[mission_id])
        return {**self.mission, "status": "completed"}


class RepairCoordinator(HermeticCoordinator):
    def _post_verify(self, state, paths):
        self.counters["post_verify"] = self.counters.get("post_verify", 0) + 1
        if state.get("repair_mission_id") is None:
            state["default_sha"] = "failed-default-sha"
            raise coordinator.PostVerifyFailed("windows post-verify token=super-secret failed")
        state.update(default_sha="repaired-default-sha", post_verify_checks=[])


class DeliveryCoordinatorTests(unittest.TestCase):
    def test_owner_question_rejects_nonsticky_blocked_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = OwnerAnswerClient()
            backend = OwnerAnswerBackend(None)
            state_root = root / "state"
            accepted = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "sequence": 1,
                "type": "mission.accepted",
                "source": "central-hermes",
                "correlation": {},
                "payload": {
                    "goal": approved["goal"],
                    "dispatch_profile": approved["dispatch_profile"],
                },
            }
            digest = coordinator.hashlib.sha256(b"mission-a7-3").hexdigest()[:12]
            adapter_state = coordinator.mission_adapter.accept_mission(
                accepted,
                state_root,
                backend,
                workspace=f"worktree:{root / 'worktrees' / ('author-' + digest)}",
            )
            client.mission["tasks"] = [{
                "task_id": adapter_state["root_task_id"],
                "title": "Mission mission-a7-3",
                "status": "blocked",
                "assignee": None,
            }]
            backend.events = [
                {"kind": "created"},
                {"kind": "unblocked", "payload": {"reason": "manual-recovery"}},
            ]

            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, state_root
            )
            with self.assertRaisesRegex(coordinator.DeliveryError, "sticky-blocked"):
                instance.tick()

    def test_owner_answer_resumes_same_mission_across_both_crash_windows(self):
        for failure_point in ("before", "after"):
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                approved = profile(root)
                client = OwnerAnswerClient()
                backend = OwnerAnswerBackend(failure_point)
                state_root = root / "state"
                accepted = {
                    "schema_version": 1,
                    "mission_id": "mission-a7-3",
                    "sequence": 1,
                    "type": "mission.accepted",
                    "source": "central-hermes",
                    "correlation": {},
                    "payload": {
                        "goal": approved["goal"],
                        "dispatch_profile": approved["dispatch_profile"],
                    },
                }
                digest = coordinator.hashlib.sha256(b"mission-a7-3").hexdigest()[:12]
                adapter_state = coordinator.mission_adapter.accept_mission(
                    accepted,
                    state_root,
                    backend,
                    workspace=f"worktree:{root / 'worktrees' / ('author-' + digest)}",
                )
                client.mission["tasks"] = [{
                    "task_id": adapter_state["root_task_id"],
                    "title": "Mission mission-a7-3",
                    "status": "blocked",
                    "assignee": None,
                }]
                instance = coordinator.DeliveryCoordinator(
                    approved, client, backend, state_root
                )

                waiting = instance.tick()
                self.assertEqual("waiting_owner", waiting["action"])
                self.assertEqual("blocked", backend.task["status"])
                self.assertIsNone(backend.task["assignee"])
                self.assertEqual([], backend.runs)

                client.answer()
                with self.assertRaisesRegex(
                    coordinator.mission_adapter.AdapterError, "crash .* Kanban update"
                ):
                    instance.tick()
                paths = instance._paths("mission-a7-3")
                pending = coordinator.mission_adapter._read_json(paths["state"])
                self.assertEqual("owner_answer_pending", pending["phase"])
                self.assertEqual("q-product", pending["owner_answers"][0]["question_id"])

                restarted = coordinator.DeliveryCoordinator(
                    approved, client, backend, state_root
                )
                with (
                    mock.patch.object(restarted, "_assert_nonroutable_assignee"),
                    mock.patch.object(restarted, "_ensure_worktree"),
                    mock.patch.object(restarted, "_publish_stage"),
                    mock.patch.object(restarted, "_reconcile_active"),
                    mock.patch.object(restarted, "_recover_author_commit", return_value=False),
                    mock.patch.object(
                        restarted,
                        "_author",
                        side_effect=coordinator.InjectedCrash("stop after owner resume"),
                    ),
                    self.assertRaisesRegex(coordinator.InjectedCrash, "stop after owner resume"),
                ):
                    restarted.tick()

                resumed = coordinator.mission_adapter._read_json(paths["state"])
                self.assertEqual("claimed", resumed["phase"])
                self.assertEqual("task-1", resumed["root_task_id"])
                self.assertEqual(1, len(resumed["owner_answers"]))
                self.assertEqual("running", backend.task["status"])
                self.assertEqual(1, backend.claims)
                self.assertEqual(2, backend.resume_calls)

    def test_owner_answer_is_bound_into_the_next_author_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(codex_bin="codex", codex_home=str(root / "codex-home"))
            captured = {}

            def runner(_command, **kwargs):
                captured["prompt"] = kwargs["input"]
                raise RuntimeError("prompt captured")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            text = "Keep the existing behavior"
            state = {
                "review_cycle": 1,
                "owner_answers": [{
                    "question_id": "q-product",
                    "text": text,
                    "sha256": coordinator.hashlib.sha256(text.encode()).hexdigest(),
                }],
            }
            with (
                mock.patch.object(
                    instance,
                    "_actor",
                    return_value={"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
                ),
                mock.patch.object(instance, "_assert_claim"),
                self.assertRaisesRegex(RuntimeError, "prompt captured"),
            ):
                instance._author(state, instance._paths("owner-answer-prompt"))

            self.assertIn("q-product", captured["prompt"])
            self.assertIn(text, captured["prompt"])

    def test_command_failure_keeps_bounded_stderr_and_stdout_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["codex_home"] = str(root / "codex")
            result = subprocess.CompletedProcess(
                ["gate"], 1, stdout="diagnostic line\n" * 500, stderr="[FAIL] gate"
            )
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state",
                runner=lambda *_args, **_kwargs: result,
            )

            with self.assertRaises(coordinator.DeliveryError) as raised:
                instance._run(["gate"])

            message = str(raised.exception)
            self.assertLessEqual(len(message), coordinator._MAX_CHECK_FAILURE_CHARS)
            self.assertIn("[FAIL] gate", message)
            self.assertIn("diagnostic", message)

    def test_command_failure_redacts_secret_shaped_output_before_persistence(self):
        result = subprocess.CompletedProcess(
            ["gate"],
            1,
            stdout="API_TOKEN=ghp_" + ("a" * 36) + "\ncompile failed",
            stderr="Authorization: Bearer sk-proj-" + ("b" * 40),
        )

        message = coordinator._command_failure(result, result.args)

        self.assertIn("compile failed", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn("ghp_", message)
        self.assertNotIn("sk-proj", message)

    def test_command_failure_redacts_single_token_uri_userinfo(self):
        secret = "single-token-credential"
        result = subprocess.CompletedProcess(
            ["gate"], 1, stdout=f"failed at https://{secret}@host/path", stderr=""
        )

        message = coordinator._command_failure(result, result.args)

        self.assertIn("[REDACTED]", message)
        self.assertNotIn(secret, message)

    def test_persisted_codex_events_redact_and_bound_command_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "events.jsonl"
            secret = "single-token-credential"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": f"curl https://{secret}@host/path",
                    "aggregated_output": "failure " + secret + ("x" * 5000),
                    "status": "failed",
                },
            }

            coordinator._private_codex_events(
                path, json.dumps(event) + "\nraw non-json secret=" + secret
            )

            persisted = path.read_text(encoding="utf-8")
            parsed = json.loads(persisted.splitlines()[0])
            self.assertIn("[REDACTED]", parsed["item"]["command"])
            self.assertLessEqual(
                len(parsed["item"]["aggregated_output"]),
                coordinator._MAX_CHECK_FAILURE_CHARS,
            )
            self.assertNotIn(secret, persisted)
            self.assertEqual("[REDACTED non-json Codex event]", persisted.splitlines()[1])

    def test_main_redacts_uri_userinfo_from_error_output(self):
        secret = "single-token-credential"
        stderr = io.StringIO()
        with (
            mock.patch.object(
                coordinator,
                "load_profile",
                side_effect=coordinator.flow_contract.ContractError(
                    f"remote mismatch: https://{secret}@host/repo.git"
                ),
            ),
            mock.patch("sys.stderr", stderr),
        ):
            status = coordinator.main(["--profile", "unused.json"])

        self.assertEqual(2, status)
        self.assertIn("[REDACTED]", stderr.getvalue())
        self.assertNotIn(secret, stderr.getvalue())

    def test_failed_author_run_removes_raw_last_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(codex_bin="codex", codex_home=str(root / "codex-home"))
            raw_paths = []

            def runner(command, **_kwargs):
                raw = pathlib.Path(command[command.index("--output-last-message") + 1])
                raw_paths.append(raw)
                raw.write_text("https://single-token-credential@host", encoding="utf-8")
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="author failed")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            paths = instance._paths("failed-author-output")
            state = {"review_cycle": 1}
            with (
                mock.patch.object(
                    instance,
                    "_actor",
                    return_value={"model": "gpt-5.6-luna", "reasoning_effort": "medium"},
                ),
                mock.patch.object(instance, "_assert_claim"),
                self.assertRaisesRegex(coordinator.DeliveryError, "author failed"),
            ):
                instance._author(state, paths)

            self.assertTrue(raw_paths)
            self.assertTrue(all(not path.exists() for path in raw_paths))
            self.assertFalse((paths["directory"] / "author-1-last.txt").exists())

    def test_invalid_reviewer_output_removes_raw_last_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(codex_bin="codex", codex_home=str(root / "codex-home"))
            raw_paths = []

            def runner(command, **_kwargs):
                raw = pathlib.Path(command[command.index("--output-last-message") + 1])
                raw_paths.append(raw)
                raw.write_text('{"verdict":"reject","findings":["secret"', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            paths = instance._paths("invalid-review-output")
            state = {"review_cycle": 1, "candidate_sha": "candidate"}
            route = {
                "reviewer": {"model": "gpt-5.6-sol", "reasoning_effort": "low"},
                "review_mode": "same_provider_independent",
                "decision_id": "decision",
            }
            with (
                mock.patch.object(instance, "_current_route", return_value=route),
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_remove_worktree"),
                mock.patch.object(instance, "_git"),
                mock.patch.object(
                    coordinator.flow_contract,
                    "source_attestation",
                    return_value={"sha256": "source"},
                ),
                self.assertRaises(ValueError),
            ):
                instance._review(state, paths)

            self.assertTrue(raw_paths)
            self.assertTrue(all(not path.exists() for path in raw_paths))
            self.assertFalse((paths["directory"] / "review-1-last.json").exists())

    def test_legacy_findings_are_sanitized_before_the_next_author_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["codex_bin"] = "codex"
            approved["codex_home"] = str(root / "codex-home")
            secret = "legacy-single-token"
            captured = {}

            def runner(_command, **kwargs):
                captured["prompt"] = kwargs["input"]
                raise RuntimeError("prompt captured")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            paths = instance._paths("legacy-diagnostic")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "legacy-diagnostic",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "needs_fix",
                "review_cycle": 2,
                "prior_author_failures": 1,
                "review_findings": [f"failed at https://{secret}@host/path"],
                "route_decisions": {},
            })

            state = instance._load_state("legacy-diagnostic", paths)
            with (
                mock.patch.object(
                    instance,
                    "_actor",
                    return_value={"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
                ),
                mock.patch.object(instance, "_assert_claim"),
                self.assertRaisesRegex(RuntimeError, "prompt captured"),
            ):
                instance._author(state, paths)

            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual(["failed at https[REDACTED]host/path"], persisted["review_findings"])
            self.assertIn("[REDACTED]", captured["prompt"])
            self.assertNotIn(secret, captured["prompt"])

    def test_route_escalates_durably_without_profile_model_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["required_files"] = ["Cli.cs"]
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            paths = instance._paths("mission-route")
            state = {"prior_review_rejections": 0, "route_decisions": {}}

            standard = instance._ensure_route(state, paths)
            self.assertEqual("gpt-5.6-luna", standard["author"]["model"])
            self.assertEqual("gpt-5.6-sol", standard["reviewer"]["model"])

            state["prior_review_rejections"] = 1
            complex_route = instance._ensure_route(state, paths)
            self.assertEqual("gpt-5.6-sol", complex_route["author"]["model"])
            self.assertEqual("gpt-5.6-terra", complex_route["reviewer"]["model"])

            state["prior_review_rejections"] = 2
            escalated = instance._ensure_route(state, paths)
            self.assertEqual("gpt-5.6-terra", escalated["author"]["model"])
            self.assertEqual("gpt-5.6-sol", escalated["reviewer"]["model"])
            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual(escalated, persisted["route_decisions"]["2"])

    def test_in_progress_v1_route_remains_exactly_recoverable_under_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["required_files"] = ["Cli.cs"]
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            legacy = coordinator.flow_contract._choose_delivery_route(
                coordinator.flow_contract._legacy_delivery_policy(instance.policy),
                {
                    "schema_version": 1,
                    "changed_files": 1,
                    "prior_review_rejections": 0,
                    "flags": instance.profile["route_flags"],
                },
                policy_id="openai-autonomy-v1",
            )
            state = {
                "prior_review_rejections": 0,
                "prior_ci_failures": 0,
                "route_decisions": {"0": legacy},
            }

            recovered = instance._ensure_route(state, instance._paths("legacy-mission"))

            self.assertEqual(legacy, recovered)
            self.assertEqual("openai-autonomy-v1", recovered["policy_id"])
            self.assertEqual("gpt-5.6-luna", recovered["author"]["model"])
            tampered = json.loads(json.dumps(legacy))
            tampered["author"]["model"] = "gpt-5.6-terra"
            with self.assertRaisesRegex(
                coordinator.flow_contract.ContractError, "exact v1 policy"
            ):
                coordinator.flow_contract.validate_stored_delivery_route(
                    instance.policy, tampered
                )

    def test_legacy_pr_head_is_migrated_before_ci_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            paths = instance._paths("legacy-pr")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "legacy-pr",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "pr_open",
                "branch": "codex/legacy-pr",
                "candidate_sha": "reviewed-v1-sha",
                "pr_number": 39,
            })

            recovered = instance._load_state("legacy-pr", paths)

            self.assertEqual("reviewed-v1-sha", recovered["pr_head_sha"])
            self.assertEqual(
                "reviewed-v1-sha",
                coordinator.mission_adapter._read_json(paths["state"])["pr_head_sha"],
            )

    def test_profile_is_closed_and_policy_is_the_only_model_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "profile.json"
            value = profile(pathlib.Path(directory))
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = coordinator.load_profile(path)
            instance = coordinator.DeliveryCoordinator(
                loaded, FakeClient(), FakeBackend(), pathlib.Path(directory) / "state"
            )
            state = {"prior_review_rejections": 0}
            decision = coordinator.flow_contract.choose_delivery_route(
                instance.policy, instance._route_signals(state)
            )
            self.assertEqual("gpt-5.6-sol", decision["author"]["model"])
            self.assertEqual("gpt-5.6-terra", decision["reviewer"]["model"])

            value = profile(pathlib.Path(directory))
            value["assignee"] = "real-hermes-profile"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "reserved non-routable"):
                coordinator.load_profile(path)

            value = profile(pathlib.Path(directory))
            value["route_flags"] = ["cross_process", "cross_process"]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "route_flags"):
                coordinator.load_profile(path)

            for retries in (3, 7):
                value = profile(pathlib.Path(directory))
                value["max_review_cycles"] = retries
                path.write_text(json.dumps(value), encoding="utf-8")
                self.assertEqual(retries, coordinator.load_profile(path)["max_review_cycles"])

            for retries in (2, 8):
                value = profile(pathlib.Path(directory))
                value["max_review_cycles"] = retries
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(coordinator.DeliveryError, "between 3 and 7"):
                    coordinator.load_profile(path)

            value = profile(pathlib.Path(directory))
            value["author_model"] = "gpt-9-unapproved"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "unknown profile fields"):
                coordinator.load_profile(path)

            loaded = profile(pathlib.Path(directory))
            instance = coordinator.DeliveryCoordinator(
                loaded, FakeClient(), FakeBackend(), pathlib.Path(directory) / "state"
            )
            state = {
                "prior_review_rejections": 0,
                "route_decisions": {"0": decision},
            }
            self.assertEqual(
                ["--strict-config", "-c", 'model_reasoning_effort="xhigh"'],
                instance._reasoning_args(state, "author"),
            )
            self.assertEqual(
                ["--strict-config", "-c", 'model_reasoning_effort="xhigh"'],
                instance._reasoning_args(state, "reviewer"),
            )

    def test_legacy_two_cycle_profile_requires_atomic_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "delivery-test.json"
            value = profile(pathlib.Path(directory))
            value.update(
                schema_version=2,
                max_review_cycles=2,
                author_model="gpt-5.6-sol",
                reviewer_model="gpt-5.6-terra",
                author_reasoning_effort="xhigh",
                reviewer_reasoning_effort="xhigh",
            )
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "migrate before activation"):
                coordinator.load_profile(path)

            inactive = lambda _unit: "inactive"
            self.assertTrue(installer.migrate_profile(path, unit_state=inactive))
            migrated = coordinator.load_profile(path)
            self.assertEqual(3, migrated["schema_version"])
            self.assertEqual(3, migrated["max_review_cycles"])
            self.assertFalse(set(migrated) & installer._LEGACY_MODEL_FIELDS)
            self.assertFalse(installer.migrate_profile(path, unit_state=inactive))
            if os.name != "nt":
                self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_profile_migration_refuses_active_timer_or_service(self):
        for active_kind in ("timer", "service"):
            with self.subTest(active_kind=active_kind), tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory) / "delivery-test.json"
                value = profile(pathlib.Path(directory))
                value.update(schema_version=2, max_review_cycles=2)
                path.write_text(json.dumps(value), encoding="utf-8")
                before = path.read_bytes()

                def state(unit):
                    return "active" if unit.endswith(f".{active_kind}") else "inactive"

                with self.assertRaisesRegex(SystemExit, f"{active_kind}.*must be inactive"):
                    installer.migrate_profile(path, unit_state=state)
                self.assertEqual(before, path.read_bytes())

    def test_required_ci_check_must_exist_and_succeed(self):
        for status in ("REQUESTED", "WAITING"):
            with self.subTest(status=status):
                self.assertEqual(
                    "pending",
                    coordinator._ci_decision([{"name": "test", "status": status}], ["test"]),
                )
        self.assertEqual(
            "pending",
            coordinator._ci_decision([{"name": "other", "conclusion": "SUCCESS"}], ["test"]),
        )
        self.assertEqual(
            "failed",
            coordinator._ci_decision([{"name": "test", "conclusion": "SKIPPED"}], ["test"]),
        )
        self.assertEqual(
            "passed",
            coordinator._ci_decision(
                [
                    {"name": "test", "conclusion": "SUCCESS"},
                    {"name": "optional", "conclusion": "NEUTRAL"},
                ],
                ["test"],
            ),
        )

    def test_ci_uses_actions_jobs_and_persists_only_bounded_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            push_only = False
            association = [{
                "number": 39,
                "head": {"ref": "codex/fix", "sha": "candidate-sha"},
                "base": {"ref": approved["default_branch"]},
            }]
            def runner(command, **_kwargs):
                nonlocal push_only
                self.assertNotIn("statusCheckRollup", command)
                endpoint = command[4]
                if endpoint.endswith("/actions/runs"):
                    runs = [{
                        "id": 70, "workflow_id": 9, "name": "CI", "status": "completed",
                        "conclusion": "success", "head_sha": "candidate-sha", "event": "push",
                        "head_branch": "codex/fix", "pull_requests": [],
                    }, {
                        "id": 72, "workflow_id": 10, "name": "Foreign", "status": "completed",
                        "conclusion": "success", "head_sha": "candidate-sha",
                        "event": "pull_request", "head_branch": "codex/fix",
                        "pull_requests": [{
                            "number": 40,
                            "head": {"ref": "codex/fix", "sha": "candidate-sha"},
                            "base": {"ref": "release"},
                        }],
                    }, {
                        "id": 73, "workflow_id": 11, "name": "Manual", "status": "completed",
                        "conclusion": "success", "head_sha": "candidate-sha",
                        "event": "workflow_dispatch", "head_branch": "codex/fix",
                        "pull_requests": association,
                    }, {
                        "id": 74, "workflow_id": 12, "name": "Foreign push",
                        "status": "completed", "conclusion": "success",
                        "head_sha": "candidate-sha", "event": "push",
                        "head_branch": "codex/fix", "pull_requests": [{
                            "number": 40,
                            "head": {"ref": "codex/fix", "sha": "candidate-sha"},
                            "base": {"ref": "release"},
                        }],
                    }]
                    if not push_only:
                        runs.append({
                            "id": 71, "workflow_id": 9, "name": "CI", "status": "completed",
                            "conclusion": "success", "head_sha": "candidate-sha",
                            "event": "pull_request", "head_branch": "codex/fix",
                            "pull_requests": association,
                        })
                    output = {
                        "total_count": len(runs),
                        "workflow_runs": runs,
                    }
                elif endpoint.endswith(("/actions/runs/70/jobs", "/actions/runs/71/jobs")):
                    output = {
                        "total_count": 1,
                        "jobs": [{
                            "name": "test", "status": "completed", "conclusion": "success",
                            "head_sha": "candidate-sha",
                            "details_url": "https://example.invalid/private-details",
                        }],
                    }
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(output), stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            state = {
                "pr_number": 39, "pr_head_sha": "candidate-sha", "branch": "codex/fix",
            }
            with (
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_assert_pr_head"),
            ):
                instance._wait_ci(state)
                instance._require_ci_green_now(state)

            self.assertEqual(
                [
                    {"name": "workflow:CI", "outcome": "SUCCESS"},
                    {"name": "test", "outcome": "SUCCESS"},
                ],
                state["ci_checks"],
            )
            self.assertNotIn("detailsUrl", json.dumps(state))
            push_only = True
            self.assertEqual(
                "passed",
                coordinator._ci_decision(instance._ci_rollup(state), ["test"]),
            )

    def test_pending_ci_timeout_enters_the_bounded_quality_failure_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(ci_timeout_seconds=1, gh_bin="gh", codex_home=str(root / "codex"))
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            pending = [{"name": "test", "status": "IN_PROGRESS"}]
            with (
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_assert_pr_head"),
                mock.patch.object(instance, "_ci_rollup", return_value=pending),
                mock.patch.object(coordinator.time, "monotonic", side_effect=[0, 0, 2]),
                mock.patch.object(coordinator.time, "sleep"),
            ):
                with self.assertRaisesRegex(coordinator.CIFailed, "timed out") as raised:
                    instance._wait_ci({"pr_number": 39})

            self.assertEqual(pending, raised.exception.checks)

    def test_repair_cycle_reuses_exact_durable_pr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []
            views = [
                {
                    "number": 39,
                    "url": "https://example.invalid/pr/39",
                    "state": "OPEN",
                    "headRefName": "codex/fix",
                    "headRefOid": "old-candidate",
                    "baseRefName": approved["default_branch"],
                },
                {
                    "number": 39,
                    "url": "https://example.invalid/pr/39",
                    "state": "OPEN",
                    "headRefName": "codex/fix",
                    "headRefOid": "new-candidate",
                    "baseRefName": approved["default_branch"],
                },
            ]

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0] == "git":
                    output = ""
                elif command[0:3] == ["gh", "pr", "view"]:
                    self.assertEqual("39", command[3])
                    output = json.dumps(views.pop(0))
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            paths = instance._paths("mission-a7-3")
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "new-candidate",
                "pr_number": 39,
                "pr_head_sha": "old-candidate",
                "pr_base_branch": approved["default_branch"],
            }

            instance._pr(state, paths)

            self.assertEqual(39, state["pr_number"])
            self.assertEqual("new-candidate", state["pr_head_sha"])
            push = next(command for command in commands if command[0] == "git")
            self.assertIn(
                "--force-with-lease=refs/heads/codex/fix:old-candidate", push
            )
            self.assertFalse(any(command[0:3] == ["gh", "pr", "create"] for command in commands))

    def test_repair_cycle_refuses_pr_identity_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0] == "git":
                    output = ""
                elif command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps({
                        "number": 40,
                        "url": "https://example.invalid/pr/40",
                        "state": "OPEN",
                        "headRefName": "codex/fix",
                        "headRefOid": "new-candidate",
                        "baseRefName": approved["default_branch"],
                    })
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            paths = instance._paths("mission-a7-3")
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "new-candidate",
                "pr_number": 39,
                "pr_head_sha": "old-candidate",
                "pr_base_branch": approved["default_branch"],
            }

            with self.assertRaisesRegex(coordinator.DeliveryError, "changed before repair push"):
                instance._pr(state, paths)

            self.assertEqual(39, state["pr_number"])
            self.assertFalse(any(command[0:3] == ["gh", "pr", "create"] for command in commands))

    def test_repair_cycle_refuses_a_retargeted_base_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps({
                        "number": 39,
                        "url": "https://example.invalid/pr/39",
                        "state": "OPEN",
                        "headRefName": "codex/fix",
                        "headRefOid": "old-candidate",
                        "baseRefName": "release",
                    })
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                raise AssertionError(command)

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "new-candidate",
                "pr_number": 39,
                "pr_head_sha": "old-candidate",
                "pr_base_branch": approved["default_branch"],
            }

            with self.assertRaisesRegex(
                coordinator.DeliveryError, "changed before repair push"
            ):
                instance._pr(state, instance._paths("mission-a7-3"))
            self.assertFalse(any(command[0] == "git" for command in commands))

    def test_repair_push_response_loss_converges_without_a_second_push(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps({
                        "number": 39,
                        "url": "https://example.invalid/pr/39",
                        "state": "OPEN",
                        "headRefName": "codex/fix",
                        "headRefOid": "new-candidate",
                        "baseRefName": approved["default_branch"],
                    })
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            paths = instance._paths("mission-a7-3")
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "new-candidate",
                "pr_number": 39,
                "pr_head_sha": "old-candidate",
                "pr_base_branch": approved["default_branch"],
            }

            instance._pr(state, paths)

            self.assertEqual("new-candidate", state["pr_head_sha"])
            self.assertFalse(any(command[0] == "git" for command in commands))

    def test_initial_push_response_loss_recovers_the_exact_remote_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            remote_head = None
            pr_exists = False
            push_calls = 0

            def runner(command, **_kwargs):
                nonlocal remote_head, pr_exists, push_calls
                if command[0] == "git" and "ls-remote" in command:
                    output = (
                        f"{remote_head}\trefs/heads/codex/fix\n" if remote_head else ""
                    )
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                if command[0] == "git" and "push" in command:
                    push_calls += 1
                    remote_head = "candidate-sha"
                    return subprocess.CompletedProcess(
                        command, 1, stdout="", stderr="lost initial push response"
                    )
                if command[0:3] == ["gh", "pr", "view"]:
                    if not pr_exists:
                        return subprocess.CompletedProcess(
                            command, 1, stdout="", stderr="no pull request"
                        )
                    output = json.dumps({
                        "number": 39,
                        "url": "https://example.invalid/pr/39",
                        "state": "OPEN",
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "candidate-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                if command[0:3] == ["gh", "pr", "create"]:
                    pr_exists = True
                    return subprocess.CompletedProcess(
                        command, 0, stdout="", stderr=""
                    )
                raise AssertionError(command)

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "candidate-sha",
            }
            paths = instance._paths("mission-a7-3")

            with self.assertRaisesRegex(coordinator.DeliveryError, "lost initial push"):
                instance._pr(state, paths)
            instance._pr(state, paths)

            self.assertEqual(1, push_calls)
            self.assertEqual(39, state["pr_number"])
            self.assertEqual("candidate-sha", state["pr_head_sha"])

    def test_initial_pr_create_response_loss_recovers_the_exact_bound_pr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            pr_exists = False
            create_calls = 0
            commands = []

            def runner(command, **_kwargs):
                nonlocal pr_exists, create_calls
                commands.append(command)
                if command[0] == "git" and "ls-remote" in command:
                    output = "candidate-sha\trefs/heads/codex/fix\n"
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                if command[0:3] == ["gh", "pr", "view"]:
                    if not pr_exists:
                        return subprocess.CompletedProcess(
                            command, 1, stdout="", stderr="no pull request"
                        )
                    output = json.dumps({
                        "number": 39,
                        "url": "https://example.invalid/pr/39",
                        "state": "OPEN",
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "candidate-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                if command[0:3] == ["gh", "pr", "create"]:
                    create_calls += 1
                    pr_exists = True
                    return subprocess.CompletedProcess(
                        command, 1, stdout="", stderr="lost PR create response"
                    )
                raise AssertionError(command)

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "candidate-sha",
            }
            paths = instance._paths("mission-a7-3")

            with self.assertRaisesRegex(coordinator.DeliveryError, "lost PR create"):
                instance._pr(state, paths)
            instance._pr(state, paths)

            self.assertEqual(1, create_calls)
            self.assertEqual(39, state["pr_number"])
            self.assertEqual("candidate-sha", state["pr_head_sha"])
            self.assertFalse(any("headRefOid" in argument for command in commands for argument in command))

    def test_merge_requeries_ci_and_stops_when_a_green_check_turns_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []

            def runner(command, **_kwargs):
                commands.append(command)
                if "headRefName,commits,baseRefName" in command:
                    output = json.dumps({
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "candidate-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                elif "state,mergedAt,mergeCommit,url,headRefName,commits,baseRefName" in command:
                    output = json.dumps({
                        "state": "OPEN", "mergedAt": None, "mergeCommit": None,
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "candidate-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                elif command[1:4] == ["api", "--method", "GET"]:
                    endpoint = command[4]
                    if endpoint.endswith("/actions/runs"):
                        output = json.dumps({
                            "total_count": 1,
                            "workflow_runs": [{
                                "id": 71, "workflow_id": 9, "name": "CI", "status": "completed",
                                "conclusion": "failure", "head_sha": "candidate-sha",
                                "event": "pull_request", "head_branch": "codex/fix",
                                "pull_requests": [{
                                    "number": 39,
                                    "head": {"ref": "codex/fix", "sha": "candidate-sha"},
                                    "base": {"ref": approved["default_branch"]},
                                }],
                            }],
                        })
                    elif endpoint.endswith("/actions/runs/71/jobs"):
                        output = json.dumps({
                            "total_count": 1,
                            "jobs": [{
                                "name": "test", "status": "completed",
                                "conclusion": "failure", "head_sha": "candidate-sha",
                            }],
                        })
                    else:
                        raise AssertionError(command)
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/fix",
                "candidate_sha": "candidate-sha",
                "pr_number": 39,
                "pr_head_sha": "candidate-sha",
                "pr_base_branch": approved["default_branch"],
                "ci_checks": [{"name": "test", "conclusion": "SUCCESS"}],
            }
            with (
                mock.patch.object(instance, "_wait_ci"),
                mock.patch.object(instance, "_validate_review"),
            ):
                with self.assertRaisesRegex(coordinator.CIFailed, "merge boundary"):
                    instance._merge(state)
            self.assertFalse(any(command[1:3] == ["pr", "merge"] for command in commands))
        self.assertEqual(
            "failed",
            coordinator._ci_decision(
                [
                    {"name": "test", "conclusion": "SUCCESS"},
                    {"name": "optional", "conclusion": "FAILURE"},
                ],
                ["test"],
            ),
        )

    def test_merge_rejects_a_merged_pr_with_a_different_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))

            def runner(command, **_kwargs):
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps({
                        "state": "MERGED",
                        "mergedAt": "2026-07-15T00:00:00Z",
                        "mergeCommit": {"oid": "merge-sha"},
                        "url": "https://example.invalid/pr/39",
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "unreviewed-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr=""
                    )
                raise AssertionError(command)

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            state = {
                "candidate_sha": "reviewed-sha", "pr_number": 39,
                "branch": "codex/fix",
                "pr_base_branch": approved["default_branch"],
            }
            with (
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_assert_pr_head"),
                mock.patch.object(instance, "_wait_ci"),
                mock.patch.object(instance, "_validate_review"),
            ):
                with self.assertRaisesRegex(coordinator.DeliveryError, "merged state"):
                    instance._merge(state)

    def test_merge_uses_exact_head_api_and_deletes_only_that_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            commands = []
            merged = False
            remote_head = "candidate-sha"

            def runner(command, **_kwargs):
                nonlocal merged, remote_head
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps({
                        "state": "MERGED" if merged else "OPEN",
                        "mergedAt": "2026-07-16T00:00:00Z" if merged else None,
                        "mergeCommit": {"oid": "merge-sha"} if merged else None,
                        "url": "https://example.invalid/pr/39",
                        "headRefName": "codex/fix",
                        "commits": [{"oid": "candidate-sha"}],
                        "baseRefName": approved["default_branch"],
                    })
                elif command[0:2] == ["gh", "api"]:
                    merged = True
                    output = json.dumps({"merged": True, "sha": "merge-sha"})
                elif command[0] == "git" and "ls-remote" in command:
                    output = (
                        "candidate-sha\trefs/heads/codex/fix\n" if remote_head else ""
                    )
                elif command[0] == "git" and "push" in command:
                    remote_head = ""
                    output = ""
                elif command[0] == "git":
                    output = ""
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            state = {
                "candidate_sha": "candidate-sha", "pr_number": 39,
                "branch": "codex/fix", "pr_base_branch": approved["default_branch"],
            }
            with (
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_assert_pr_head"),
                mock.patch.object(instance, "_wait_ci"),
                mock.patch.object(instance, "_validate_review"),
                mock.patch.object(instance, "_require_ci_green_now"),
            ):
                instance._merge(state)

            api = next(command for command in commands if command[0:2] == ["gh", "api"])
            self.assertIn("sha=candidate-sha", api)
            self.assertNotIn("--match-head-commit", api)
            self.assertEqual("merge-sha", state["merge_sha"])
            self.assertEqual("", remote_head)

    def test_ci_failure_is_checkpointed_and_escalates_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["required_files"] = ["Cli.cs"]
            client = FakeClient()
            client.mission["tasks"] = [{"task_id": "task-1"}]
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            counters = {"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0}
            state_root = root / "state"
            instance = HermeticCoordinator(
                approved, client, backend, state_root, counters=counters
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "pr_open",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "prior_review_rejections": 0,
                "prior_ci_failures": 0,
                "route_decisions": {},
                "crash_injected": True,
                "candidate_sha": "candidate-sha",
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_number": 39,
                "pr_url": "https://example.invalid/pr/39",
                "pr_head_sha": "candidate-sha",
            })
            checks = [{
                "name": "test",
                "conclusion": "FAILURE",
                "detailsUrl": "https://example.invalid/raw-details",
            }]
            with mock.patch.object(
                instance, "_wait_ci",
                side_effect=coordinator.CIFailed("required CI failed", checks),
            ):
                result = instance.tick()

            self.assertEqual("needs_fix", result["action"])
            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual(2, persisted["review_cycle"])
            self.assertEqual(1, persisted["prior_ci_failures"])
            self.assertEqual([{"name": "test", "outcome": "FAILURE"}], persisted["ci_checks"])
            self.assertNotIn("detailsUrl", json.dumps(persisted))

            restarted = coordinator.DeliveryCoordinator(
                approved, client, backend, state_root
            )
            recovered = restarted._load_state("mission-a7-3", paths)
            decision = restarted._ensure_route(recovered, paths)
            self.assertEqual("complex", decision["route"])
            self.assertEqual("gpt-5.6-sol", decision["author"]["model"])
            self.assertEqual("gpt-5.6-terra", decision["reviewer"]["model"])
            self.assertEqual(decision, recovered["route_decisions"]["1"])

    def test_final_ci_failure_preserves_pr_and_converges_to_terminal_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = RejectionClient()
            backend = RejectionBackend()
            backend.fail_after_complete_once = False
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "ci_failed",
                "failure_kind": "ci",
                "failure_error": "test=FAILURE",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 3,
                "crash_injected": True,
                "candidate_sha": "candidate-sha",
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_number": 39,
                "pr_head_sha": "candidate-sha",
                "pr_base_branch": approved["default_branch"],
                "pr_url": "https://example.invalid/pr/39",
            })

            with (
                mock.patch.object(
                    instance, "_finalize_failed_pr", return_value=True
                ) as finalize,
                mock.patch.object(instance, "_cleanup") as cleanup,
            ):
                result = instance.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual("ci_failed", result["state"]["outcome"])
            self.assertEqual("failed", client.mission["status"])
            self.assertTrue(result["state"]["failed_pr_preserved"])
            finalize.assert_called_once()
            cleanup.assert_called_once()
            self.assertTrue(cleanup.call_args.kwargs["preserve_remote"])
            self.assertEqual(
                instance._failure_contract(result["state"])[2],
                backend.runs[0]["metadata"]["mission_events"],
            )
            self.assertTrue(instance._rejection_persisted(result["state"]))

    def test_final_review_failure_preserves_the_pr_from_an_earlier_ci_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = RejectionClient()
            backend = RejectionBackend()
            backend.fail_after_complete_once = False
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "review_rejected",
                "failure_kind": "review",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 3,
                "crash_injected": True,
                "candidate_sha": "unpublished-repair",
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_number": 39,
                "pr_head_sha": "last-pushed-candidate",
                "pr_base_branch": approved["default_branch"],
                "pr_url": "https://example.invalid/pr/39",
            })

            with (
                mock.patch.object(
                    instance, "_finalize_failed_pr", return_value=True
                ) as finalize,
                mock.patch.object(instance, "_cleanup") as cleanup,
            ):
                result = instance.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual("review_rejected", result["state"]["outcome"])
            self.assertTrue(result["state"]["failed_pr_preserved"])
            finalize.assert_called_once()
            cleanup.assert_called_once()
            self.assertTrue(cleanup.call_args.kwargs["preserve_remote"])

    def test_open_failed_pr_is_preserved_without_an_unsafe_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []
            views = [
                {
                    "state": "OPEN", "headRefName": "codex/fix",
                    "headRefOid": "candidate-sha", "baseRefName": approved["default_branch"],
                },
            ]
            remote_heads = ["candidate-sha\trefs/heads/codex/fix\n"]

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps(views.pop(0))
                elif "ls-remote" in command:
                    output = remote_heads.pop(0)
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            preserved = instance._finalize_failed_pr({
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_number": 39,
                "branch": "codex/fix",
                "candidate_sha": "candidate-sha",
                "pr_head_sha": "candidate-sha",
                "pr_base_branch": approved["default_branch"],
            })
            self.assertTrue(preserved)
            self.assertFalse(any(command[0:3] == ["gh", "pr", "close"] for command in commands))
            self.assertFalse(any(command[0] == "git" and "push" in command for command in commands))

            commands.clear()
            views.append({
                "state": "OPEN", "headRefName": "codex/fix", "headRefOid": "different-sha",
                "baseRefName": approved["default_branch"],
            })
            with self.assertRaisesRegex(coordinator.DeliveryError, "identity"):
                instance._finalize_failed_pr({
                    "root_task_id": "task-1",
                    "run_id": "7",
                    "pr_number": 39,
                    "branch": "codex/fix",
                    "candidate_sha": "candidate-sha",
                    "pr_head_sha": "candidate-sha",
                    "pr_base_branch": approved["default_branch"],
                })
            self.assertFalse(any(command[0:3] == ["gh", "pr", "close"] for command in commands))
            self.assertFalse(any(command[0] == "git" for command in commands))

    def test_already_closed_failed_pr_lease_deletes_only_the_exact_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []
            views = [
                {
                    "state": "CLOSED", "headRefName": "codex/fix",
                    "headRefOid": "candidate-sha", "baseRefName": approved["default_branch"],
                },
                {
                    "state": "CLOSED", "headRefName": "codex/fix",
                    "headRefOid": "candidate-sha", "baseRefName": approved["default_branch"],
                },
            ]
            remote_heads = ["candidate-sha\trefs/heads/codex/fix\n", ""]

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps(views.pop(0))
                elif "ls-remote" in command:
                    output = remote_heads.pop(0)
                elif "push" in command and "--delete" in command:
                    output = ""
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(
                    command, 0, stdout=output, stderr=""
                )

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            preserved = instance._finalize_failed_pr({
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_number": 39,
                "branch": "codex/fix",
                "candidate_sha": "candidate-sha",
                "pr_head_sha": "candidate-sha",
                "pr_base_branch": approved["default_branch"],
            })

            self.assertFalse(preserved)
            deletion = next(
                command for command in commands
                if command[0] == "git" and "--delete" in command
            )
            self.assertIn(
                "--force-with-lease=refs/heads/codex/fix:candidate-sha", deletion
            )
            self.assertFalse(any(command[0:3] == ["gh", "pr", "close"] for command in commands))

    def test_failed_pr_cleanup_refuses_a_moved_remote_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            commands = []
            views = [
                {
                    "state": "OPEN", "headRefName": "codex/fix",
                    "headRefOid": "candidate-sha", "baseRefName": approved["default_branch"],
                },
            ]

            def runner(command, **_kwargs):
                commands.append(command)
                if command[0:3] == ["gh", "pr", "view"]:
                    output = json.dumps(views.pop(0))
                elif "ls-remote" in command:
                    output = "moved-sha\trefs/heads/codex/fix\n"
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            with self.assertRaisesRegex(coordinator.DeliveryError, "branch moved"):
                instance._finalize_failed_pr({
                    "root_task_id": "task-1",
                    "run_id": "7",
                    "pr_number": 39,
                    "branch": "codex/fix",
                    "candidate_sha": "unpublished-repair",
                    "pr_head_sha": "candidate-sha",
                    "pr_base_branch": approved["default_branch"],
                })
            self.assertFalse(any(command[0] == "git" and "push" in command for command in commands))

    def test_failed_pr_cleanup_stops_before_mutation_without_a_live_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(gh_bin="gh", codex_home=str(root / "codex"))
            commands = []

            def runner(command, **_kwargs):
                commands.append(command)
                raise AssertionError(command)

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state", runner=runner
            )
            with self.assertRaisesRegex(
                coordinator.mission_adapter.AdapterError, "stale claim"
            ):
                instance._finalize_failed_pr({
                    "root_task_id": "task-1",
                    "run_id": "7",
                    "pr_number": 39,
                    "branch": "codex/fix",
                    "candidate_sha": "candidate-sha",
                    "pr_head_sha": "candidate-sha",
                    "pr_base_branch": approved["default_branch"],
                })
            self.assertEqual([], commands)

    def test_reserved_assignee_must_not_resolve_to_a_worker_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            profile_dir = root / "hermes" / "profiles" / approved["assignee"]
            profile_dir.mkdir(parents=True)
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(root / "hermes")}):
                with self.assertRaisesRegex(coordinator.DeliveryError, "resolves to a Hermes"):
                    instance._assert_nonroutable_assignee()

    def test_existing_author_commit_is_checkpointed_without_a_second_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["codex_home"] = str(root / "codex")
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state"
            )
            paths = instance._paths("mission-recover")
            paths["author"].mkdir(parents=True)

            def git(*arguments):
                return subprocess.run(
                    ["git", *arguments],
                    cwd=paths["author"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Test")
            for name in approved["required_files"]:
                (paths["author"] / name).write_text("base\n", encoding="utf-8")
            git("add", "--", *approved["required_files"])
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            for name in approved["required_files"]:
                (paths["author"] / name).write_text("candidate\n", encoding="utf-8")
            git("add", "--", *approved["required_files"])
            git("commit", "-m", approved["commit_message"])
            paths["directory"].mkdir(parents=True, exist_ok=True)
            (paths["directory"] / "author-1.jsonl").write_text("{}\n", encoding="utf-8")
            state = {
                "mission_id": "mission-recover",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "claimed",
                "branch": "codex/recover",
                "review_cycle": 1,
                "base_sha": base,
                "root_task_id": "task-1",
                "run_id": "7",
            }
            with (
                mock.patch.object(instance, "_checks", return_value=[]) as checks,
                mock.patch.object(instance, "_record_author") as record,
            ):
                self.assertTrue(instance._recover_author_commit(state, paths))
            checks.assert_called_once()
            record.assert_called_once()

    def test_expired_claim_stops_the_coordinator(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend()
            expired = int(time.time()) - 1
            backend.task.update(status="running", claim_expires=expired)
            backend.runs = [{"id": 7, "status": "running", "claim_expires": expired}]
            client = FakeClient()
            instance = coordinator.DeliveryCoordinator(
                profile(pathlib.Path(directory)),
                client,
                backend,
                pathlib.Path(directory) / "state",
            )
            with self.assertRaisesRegex(coordinator.mission_adapter.AdapterError, "stale claim"):
                instance._publish_stage(
                    {"mission_id": "mission-a7-3", "root_task_id": "task-1", "run_id": "7"},
                    "delivering",
                    80,
                )
            self.assertEqual([], client.stages)

    def test_expired_or_revoked_claim_stops_active_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {
                "mission_id": "mission-a7-3",
                "root_task_id": "task-1",
                "run_id": "7",
            }
            for failure in ("expired", "revoked"):
                with self.subTest(failure=failure):
                    backend = FakeBackend()
                    backend.claim("task-1", ttl_seconds=28800)
                    instance = coordinator.DeliveryCoordinator(
                        profile(pathlib.Path(directory)),
                        client := FakeClient(),
                        backend,
                        pathlib.Path(directory) / "state",
                    )
                    client.mission["tasks"] = [{"task_id": "task-1"}]

                    def mutate_before_publication(_mission_id, _state_root, _backend):
                        if failure == "expired":
                            expired = int(time.time()) - 1
                            backend.task["claim_expires"] = expired
                            backend.runs[0]["claim_expires"] = expired
                        else:
                            backend.task["status"] = "ready"
                            backend.runs[0]["status"] = "cancelled"
                        return [{"type": "task.upsert"}]

                    with (
                        mock.patch.object(
                            coordinator.mission_adapter,
                            "recover_mission_state",
                            return_value={"root_task_id": "task-1"},
                        ),
                        mock.patch.object(
                            coordinator.mission_adapter,
                            "sync_mission",
                            side_effect=mutate_before_publication,
                        ),
                        self.assertRaisesRegex(
                            coordinator.mission_adapter.AdapterError, "stale claim"
                        ),
                    ):
                        instance._reconcile_active(state)
                    self.assertEqual([], client.stages)

    def test_terminal_metadata_mutation_stops_final_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = FakeClient()
            client.mission["tasks"] = [{"task_id": "task-1"}]
            backend = MutatingCompletionBackend()
            state = {
                "mission_id": "mission-a7-3",
                "phase": "task_completed",
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_url": "https://example.invalid/pr/39",
                "default_sha": "default-sha",
            }
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            backend.task.update(status="done", result="success")
            backend.runs = [{
                "id": 7,
                "status": "done",
                "outcome": "completed",
                "summary": "Reviewed change merged, verified, and cleaned",
                "metadata": {"mission_events": instance._events(state, cleanup=True)},
            }]
            backend.mutate_on_show = 3
            with (
                mock.patch.object(
                    coordinator.mission_adapter,
                    "recover_mission_state",
                    return_value={"root_task_id": "task-1"},
                ),
                self.assertRaisesRegex(
                    coordinator.DeliveryError, "approved completion contract"
                ),
            ):
                instance._reconcile_completed(state)
            self.assertEqual([], client.stages)

    def test_child_environment_excludes_control_plane_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            approved = profile(pathlib.Path(directory))
            approved.update(codex_home=str(pathlib.Path(directory) / "codex"))
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), pathlib.Path(directory) / "state"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "HERMES_API_TOKEN": "secret-api",
                    "HERMES_MISSION_PRODUCER_KEY": "secret-producer",
                    "HERMES_DASHBOARD_PASSWORD": "secret-dashboard",
                },
            ):
                environment = instance._safe_env()
                model_environment = instance._model_env(
                    instance._paths("mission-environment")
                )
            self.assertNotIn("HERMES_API_TOKEN", environment)
            self.assertNotIn("HERMES_MISSION_PRODUCER_KEY", environment)
            self.assertNotIn("HERMES_DASHBOARD_PASSWORD", environment)
            self.assertEqual(approved["codex_home"], environment["CODEX_HOME"])
            self.assertNotEqual(environment.get("HOME"), model_environment["HOME"])
            self.assertEqual(os.devnull, model_environment["GIT_CONFIG_GLOBAL"])
            self.assertEqual("1", model_environment["GIT_CONFIG_NOSYSTEM"])
            self.assertNotIn("GH_TOKEN", model_environment)

    def test_systemd_timer_retries_the_expected_crash_without_a_daemon(self):
        service = (ROOT / "tools/swarm/systemd/hermes-delivery-coordinator@.service").read_text()
        timer = (ROOT / "tools/swarm/systemd/hermes-delivery-coordinator@.timer").read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("SuccessExitStatus=75", service)
        self.assertIn("UMask=0077", service)
        self.assertIn(
            "EnvironmentFile=%h/.config/uap/delivery-coordinator.env", service
        )
        self.assertIn("UnsetEnvironment=HERMES_MISSION_OWNER_KEY", service)
        self.assertNotIn("%h/hermes-workspace/.env", service)
        self.assertIn("OnUnitActiveSec=1min", timer)
        self.assertIn("OnActiveSec=1min", timer)
        self.assertNotIn("OnBootSec=", timer)
        self.assertIn("Persistent=true", timer)

    def test_profile_lock_rejects_an_overlapping_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "delivery.lock"
            with coordinator.exclusive_lock(path):
                with self.assertRaisesRegex(coordinator.DeliveryError, "already running"):
                    with coordinator.exclusive_lock(path):
                        pass

    def test_lost_final_response_recovers_from_central_terminal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = FakeClient()
            client.hide_terminal = True
            state_root = root / "state"
            instance = HermeticCoordinator(
                approved,
                client,
                FakeBackend(),
                state_root,
                counters={"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0},
            )
            paths = instance._paths("mission-a7-3")
            state = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "task_completed",
                "root_task_id": "task-1",
                "run_id": "7",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": True,
                "pr_url": "https://example.invalid/pr/39",
                "default_sha": "default-sha",
            }
            instance.backend.task.update(status="done", result="success")
            instance.backend.runs = [{
                "id": 7,
                "status": "done",
                "outcome": "completed",
                "summary": "Reviewed change merged, verified, and cleaned",
                "metadata": {"mission_events": instance._events(state, cleanup=True)},
            }]
            instance._save(paths, state)
            result = instance.tick()
            self.assertEqual("complete", result["action"])
            self.assertTrue(result["state"]["task_archived"])
            self.assertTrue(result["state"]["kanban_gc_ran"])
            self.assertEqual((1, 1), (instance.backend.archives, instance.backend.gcs))
            self.assertTrue(instance._task_completion_persisted(result["state"]))

    def test_completed_state_is_private_and_pruned_after_thirty_days(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state_root = root / "state"
            backend = FakeBackend()
            instance = coordinator.DeliveryCoordinator(
                profile(root), FakeClient(), backend, state_root
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": instance.profile["dispatch_profile"],
                "phase": "complete",
                "task_archived": True,
                "kanban_gc_ran": True,
            })
            old = time.time() - coordinator._COMPLETED_STATE_RETENTION_SECONDS - 1
            os.utime(paths["state"], (old, old))
            instance._prune_completed_states()
            self.assertFalse(paths["directory"].exists())
            self.assertEqual(1, backend.gcs)
            instance._prune_completed_states()
            if os.name == "posix":
                self.assertEqual(0o700, state_root.stat().st_mode & 0o777)

    def test_legacy_completed_state_enters_the_lifecycle_on_the_next_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            client = FakeClient()
            client.hide_terminal = True
            backend = FakeBackend()
            instance = coordinator.DeliveryCoordinator(
                profile(root), client, backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": instance.profile["dispatch_profile"],
                "phase": "complete",
                "root_task_id": "task-1",
            })
            retained_at = time.time() - 60
            os.utime(paths["state"], (retained_at, retained_at))

            self.assertIsNone(instance.tick())

            state = coordinator.mission_adapter._read_json(paths["state"])
            self.assertTrue(state["task_archived"])
            self.assertTrue(state["kanban_gc_ran"])
            self.assertEqual((1, 1), (backend.archives, backend.gcs))
            self.assertEqual(retained_at, paths["state"].stat().st_mtime)
            self.assertIsNone(instance.tick())
            self.assertEqual((1, 1), (backend.archives, backend.gcs))

    def test_completed_state_deletion_resumes_after_state_file_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state_root = root / "state"
            instance = coordinator.DeliveryCoordinator(
                profile(root), FakeClient(), FakeBackend(), state_root
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": instance.profile["dispatch_profile"],
                "phase": "complete",
                "task_archived": True,
                "kanban_gc_ran": True,
            })
            artifact = paths["directory"] / "author-1.jsonl"
            artifact.write_text("private evidence", encoding="utf-8")
            old = time.time() - coordinator._COMPLETED_STATE_RETENTION_SECONDS - 1
            os.utime(paths["state"], (old, old))
            def remove_state_then_crash(target):
                target = pathlib.Path(target)
                (target / "delivery-state.json").unlink()
                raise OSError("simulated crash during directory deletion")

            with mock.patch.object(
                coordinator.shutil, "rmtree", side_effect=remove_state_then_crash
            ):
                with self.assertRaisesRegex(OSError, "during directory deletion"):
                    instance._prune_completed_states()

            pending = state_root / f".prune-{paths['directory'].name}"
            self.assertFalse(paths["directory"].exists())
            self.assertTrue((pending / artifact.name).exists())
            self.assertFalse((pending / "delivery-state.json").exists())
            instance._prune_completed_states()
            self.assertFalse(pending.exists())


    def test_deferred_gc_does_not_extend_completed_state_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = pathlib.Path(directory) / "state"
            instance = HermeticCoordinator(
                profile(pathlib.Path(directory)), FakeClient(), FakeBackend(), state_root,
                counters={"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0},
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": instance.profile["dispatch_profile"],
                "phase": "complete",
                "task_archived": True,
                "kanban_gc_ran": False,
            })
            old = time.time() - coordinator._COMPLETED_STATE_RETENTION_SECONDS - 1
            os.utime(paths["state"], (old, old))
            instance.backend.gc = mock.Mock(side_effect=(False, True, True))

            instance._prune_completed_states()
            self.assertTrue(paths["state"].exists())
            self.assertEqual(old, paths["state"].stat().st_mtime)
            real_replace = coordinator.mission_adapter.os.replace

            def replace_then_crash(source, target):
                real_replace(source, target)
                raise OSError("simulated crash after atomic state replace")

            with mock.patch.object(
                coordinator.mission_adapter.os,
                "replace",
                side_effect=replace_then_crash,
            ):
                with self.assertRaisesRegex(OSError, "after atomic state replace"):
                    instance._prune_completed_states()
            self.assertTrue(
                coordinator.mission_adapter._read_json(paths["state"])["kanban_gc_ran"]
            )
            self.assertEqual(old, paths["state"].stat().st_mtime)
            instance._prune_completed_states()
            self.assertFalse(paths["directory"].exists())
            self.assertEqual(3, instance.backend.gc.call_count)

    def test_restart_reuses_task_run_worktree_and_author_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            client = FakeClient()
            backend = FakeBackend()
            counters = {"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0}
            approved = profile(root)
            state_root = root / "state"
            handoff = {
                "root_task_id": "task-1",
                "mission_id": "mission-a7-3",
                "action": "dispatched",
            }
            with mock.patch.object(coordinator.mission_adapter, "coordinator_tick", return_value=handoff):
                first = HermeticCoordinator(
                    approved, client, backend, state_root, counters=counters
                )
                with self.assertRaisesRegex(coordinator.InjectedCrash, "durable author commit"):
                    first.tick()

                client.mission["tasks"] = [{"task_id": "task-1", "status": "running"}]
                restarted = HermeticCoordinator(
                    approved, client, backend, state_root, counters=counters
                )
                result = restarted.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual(1, counters["authors"])
            self.assertEqual(1, counters["reviews"])
            self.assertEqual(1, counters["worktrees"])
            self.assertEqual(1, counters["cleanups"])
            self.assertEqual(1, backend.claims)
            self.assertEqual("7", result["state"]["run_id"])
            self.assertEqual("candidate-sha", result["state"]["candidate_sha"])
            self.assertTrue(result["state"]["crash_injected"])

    def test_cycle_eight_accepts_or_terminates_without_a_ninth_tick_review(self):
        for verdict in ("accept", "reject"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                approved = profile(root)
                approved.update(
                    codex_bin="codex", codex_home=str(root / "codex"), max_review_cycles=7
                )
                client = FakeClient() if verdict == "accept" else RejectionClient()
                client.mission["tasks"] = [{"task_id": "task-1"}]
                backend = FakeBackend() if verdict == "accept" else RejectionBackend()
                if isinstance(backend, RejectionBackend):
                    backend.fail_after_complete_once = False
                backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
                counters = {"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0}
                review_calls = 0

                def runner(command, **_kwargs):
                    nonlocal review_calls
                    review_calls += 1
                    last = pathlib.Path(
                        command[command.index("--output-last-message") + 1]
                    )
                    last.write_text(
                        json.dumps({"verdict": verdict, "findings": [] if verdict == "accept" else ["still broken"]}),
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout='{"type":"thread.started","thread_id":"review-session"}\n',
                        stderr="",
                    )

                instance = TickReviewCoordinator(
                    approved, client, backend, root / "state", counters=counters, runner=runner
                )
                paths = instance._paths("mission-a7-3")
                paths["review"].mkdir(parents=True)
                instance._save(paths, {
                    "schema_version": 1,
                    "mission_id": "mission-a7-3",
                    "dispatch_profile": approved["dispatch_profile"],
                    "phase": "author_committed",
                    "branch": "codex/a7-3-vpnrouter-deadbeef",
                    "review_cycle": 8,
                    "prior_review_rejections": 7,
                    "prior_ci_failures": 0,
                    "prior_author_failures": 0,
                    "route_decisions": {},
                    "crash_injected": True,
                    "candidate_sha": "candidate-sha",
                    "root_task_id": "task-1",
                    "run_id": "7",
                    "author_summary": {},
                    "author_telemetry": {},
                })
                telemetry = {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "session_id": "review-session",
                }
                with (
                    mock.patch.object(instance, "_checks", return_value=[]),
                    mock.patch.object(instance, "_rollout", return_value=root / "rollout.jsonl"),
                    mock.patch.object(
                        coordinator.flow_contract,
                        "source_attestation",
                        return_value={"sha256": "source-sha"},
                    ),
                    mock.patch.object(
                        coordinator.flow_contract,
                        "summarize_codex_events",
                        return_value=telemetry,
                    ),
                ):
                    result = instance.tick()

                self.assertEqual("complete", result["action"])
                self.assertEqual(1, review_calls)
                self.assertEqual(0, counters["authors"])
                self.assertEqual(8, result["state"]["review_cycle"])
                if verdict == "accept":
                    self.assertEqual("completed", client.get_mission("mission-a7-3")["status"])
                else:
                    self.assertEqual("review_rejected", result["state"]["outcome"])
                with mock.patch.object(instance, "_review", side_effect=AssertionError("ninth review")):
                    repeated = instance.tick()
                if verdict == "accept":
                    self.assertEqual("complete", repeated["action"])
                else:
                    self.assertIsNone(repeated)

    def test_failed_author_checks_checkpoint_one_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            paths["author"].mkdir(parents=True)
            paths["directory"].mkdir(parents=True)
            (paths["directory"] / "author-1.jsonl").write_text(
                '{"type":"turn.completed"}\n', encoding="utf-8"
            )
            state = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "claimed",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": False,
                "root_task_id": "task-1",
                "run_id": "7",
                "base_sha": "base-sha",
            }
            failure = "compile failed: " + ("x" * 5000)
            with (
                mock.patch.object(instance, "_changed_files", return_value=set(approved["required_files"])),
                mock.patch.object(instance, "_candidate_fingerprint", return_value="candidate-v1"),
                mock.patch.object(
                    instance, "_checks", side_effect=coordinator.DeliveryError(failure)
                ),
            ):
                self.assertTrue(instance._recover_author_commit(state, paths))

            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual("needs_fix", persisted["phase"])
            self.assertEqual(2, persisted["review_cycle"])
            self.assertEqual(1, persisted["prior_author_failures"])
            self.assertLessEqual(
                len(persisted["review_findings"][0]), coordinator._MAX_CHECK_FAILURE_CHARS
            )
            self.assertIn("[REDACTED]", persisted["review_findings"][0])
            with mock.patch.object(
                instance, "_changed_files", return_value=set(approved["required_files"])
            ), mock.patch.object(
                instance, "_candidate_fingerprint", return_value="candidate-v1"
            ):
                self.assertFalse(instance._recover_author_commit(persisted, paths))

    def test_repeated_author_check_failures_escalate_the_next_author(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            paths = instance._paths("mission-author-escalation")
            state = {
                "schema_version": 1,
                "mission_id": "mission-author-escalation",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "claimed",
                "review_cycle": 1,
                "prior_review_rejections": 0,
                "prior_ci_failures": 0,
                "route_decisions": {},
            }

            instance._record_author_check_failure(
                state, paths, coordinator.DeliveryError("first gate failure")
            )
            self.assertEqual("complex", instance._ensure_route(state, paths)["route"])
            instance._record_author_check_failure(
                state, paths, coordinator.DeliveryError("second gate failure")
            )
            escalated = instance._ensure_route(state, paths)

            self.assertEqual(2, state["prior_author_failures"])
            self.assertEqual("escalated", escalated["route"])
            self.assertEqual("gpt-5.6-terra", escalated["author"]["model"])
            self.assertEqual("gpt-5.6-sol", escalated["reviewer"]["model"])

    def test_author_check_mutation_fails_without_reusing_the_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["codex_home"] = str(root / "codex")
            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), FakeBackend(), root / "state"
            )
            paths = instance._paths("mission-a7-3")
            base_sha = dirty_git_checkout(
                paths["author"], approved["required_files"], "codex/a7-3-vpnrouter-deadbeef"
            )
            paths["directory"].mkdir(parents=True)
            (paths["directory"] / "author-1.jsonl").write_text(
                '{"type":"turn.completed"}\n', encoding="utf-8"
            )
            state = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "claimed",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": False,
                "root_task_id": "task-1",
                "run_id": "7",
                "base_sha": base_sha,
            }

            def mutating_check(*_args):
                target = paths["author"] / approved["required_files"][0]
                target.write_text(target.read_text(encoding="utf-8") + "check mutation\n", encoding="utf-8")
                raise coordinator.DeliveryError("compile failed")

            with mock.patch.object(instance, "_checks", side_effect=mutating_check):
                self.assertTrue(instance._recover_author_commit(state, paths))

            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual("author_checks_failed", persisted["phase"])
            self.assertEqual("author_checks", persisted["failure_kind"])
            self.assertEqual("author checks mutated the exact candidate", persisted["failure_error"])

    def test_dirty_claimed_restart_uses_one_retry_then_stays_model_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(
                author_checks=[["fail-check"]],
                codex_bin="codex",
                codex_home=str(root / "codex"),
                max_review_cycles=1,
            )
            client = RejectionClient()
            backend = RejectionBackend()
            backend.fail_after_complete_once = False
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            state_root = root / "state"
            author_calls = 0

            def runner(command, **kwargs):
                nonlocal author_calls
                if command[0] == "codex":
                    author_calls += 1
                    self.assertIn("--strict-config", command)
                    self.assertIn('model_reasoning_effort="xhigh"', command)
                    checkout = pathlib.Path(kwargs["cwd"])
                    for name in approved["required_files"]:
                        path = checkout / name
                        path.write_text(path.read_text(encoding="utf-8") + "retry\n", encoding="utf-8")
                    last = pathlib.Path(command[command.index("--output-last-message") + 1])
                    last.write_text("retry complete", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            '{"type":"thread.started","thread_id":"author-retry"}\n'
                            '{"type":"turn.completed"}\n'
                        ),
                        stderr="",
                    )
                if command[0] == "fail-check":
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="compile failed")
                return subprocess.run(command, **kwargs)

            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, state_root, runner=runner
            )
            paths = instance._paths("mission-a7-3")
            base_sha = dirty_git_checkout(
                paths["author"], approved["required_files"], "codex/a7-3-vpnrouter-deadbeef"
            )
            paths["directory"].mkdir(parents=True)
            (paths["directory"] / "author-1.jsonl").write_text(
                '{"type":"turn.completed"}\n', encoding="utf-8"
            )
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "claimed",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": False,
                "root_task_id": "task-1",
                "run_id": "7",
                "base_sha": base_sha,
            })

            with mock.patch.object(instance, "_ensure_worktree"):
                first = instance.tick()
                second = instance.tick()

            self.assertEqual("needs_fix", first["action"])
            self.assertEqual("author_checks_failed", second["action"])
            self.assertEqual(1, author_calls)

            restarted = coordinator.DeliveryCoordinator(
                approved, client, backend, state_root, runner=runner
            )
            with mock.patch.object(restarted, "_cleanup") as cleanup:
                terminal = restarted.tick()
                self.assertIsNone(restarted.tick())

            self.assertEqual("complete", terminal["action"])
            self.assertEqual("author_checks_failed", terminal["state"]["outcome"])
            self.assertEqual(1, author_calls)
            self.assertEqual(1, cleanup.call_count)

    def test_exhausted_author_checks_use_terminal_failure_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = RejectionClient()
            backend = RejectionBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "author_checks_failed",
                "failure_kind": "author_checks",
                "failure_error": "compile failed",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 2,
                "crash_injected": False,
                "root_task_id": "task-1",
                "run_id": "7",
            })

            with mock.patch.object(instance, "_cleanup") as cleanup:
                with self.assertRaisesRegex(
                    coordinator.mission_adapter.AdapterError, "lost completion response"
                ):
                    instance.tick()
                result = instance.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual("author_checks_failed", result["state"]["outcome"])
            self.assertEqual("failed", client.mission["status"])
            self.assertEqual(1, cleanup.call_count)
            self.assertEqual(
                instance._failure_contract(result["state"])[2],
                backend.runs[0]["metadata"]["mission_events"],
            )

    def test_lost_native_completion_response_recovers_without_manual_state_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = FakeClient()
            backend = LostCompleteResponseBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            counters = {"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0}
            instance = HermeticCoordinator(
                approved, client, backend, root / "state", counters=counters
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "verified",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": True,
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_url": "https://example.invalid/pr/39",
                "default_sha": "default-sha",
            })

            with self.assertRaisesRegex(
                coordinator.mission_adapter.AdapterError, "lost completion response"
            ):
                instance.tick()
            self.assertFalse(paths["author"].exists())
            self.assertEqual("cleaned", coordinator.mission_adapter._read_json(paths["state"])["phase"])
            result = instance.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual(1, backend.claims)
            self.assertEqual(0, counters["authors"])
            self.assertEqual(1, counters["cleanups"])
            self.assertIn(
                {"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}},
                backend.runs[0]["metadata"]["mission_events"],
            )

    def test_rejected_review_cleans_and_converges_after_lost_completion_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            client = RejectionClient()
            backend = RejectionBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "review_rejected",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 2,
                "crash_injected": True,
                "root_task_id": "task-1",
                "run_id": "7",
            })

            with mock.patch.object(instance, "_cleanup") as cleanup:
                with self.assertRaisesRegex(
                    coordinator.mission_adapter.AdapterError, "lost completion response"
                ):
                    instance.tick()
                self.assertEqual(
                    "rejection_cleaned",
                    coordinator.mission_adapter._read_json(paths["state"])["phase"],
                )
                result = instance.tick()

            self.assertEqual("complete", result["action"])
            self.assertEqual("review_rejected", result["state"]["outcome"])
            self.assertEqual("failed", client.mission["status"])
            self.assertEqual(1, cleanup.call_count)
            self.assertEqual(
                instance._rejection_events(),
                backend.runs[0]["metadata"]["mission_events"],
            )
            with mock.patch.object(instance, "_review", side_effect=AssertionError("model rerun")):
                self.assertIsNone(instance.tick())

    def test_post_verify_repair_is_idempotent_and_resumes_parent_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["post_verify_repair"] = {
                "dispatch_profile": "build1-vpnrouter-repair",
                "goal": "Repair the exact post-verify failure",
            }
            client = RepairClient()
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])
            counters = {"authors": 0, "reviews": 0, "worktrees": 0, "cleanups": 0}
            instance = RepairCoordinator(
                approved, client, backend, root / "state", counters=counters
            )
            paths = instance._paths("mission-a7-3")
            instance._save(paths, {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "merged",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 1,
                "crash_injected": True,
                "root_task_id": "task-1",
                "run_id": "7",
                "candidate_sha": "candidate-sha",
                "pr_url": "https://example.invalid/pr/39",
            })

            with self.assertRaisesRegex(
                coordinator.mission_adapter.AdapterError, "lost child accept response"
            ):
                instance.tick()
            pending = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual("post_verify_repair_pending", pending["phase"])
            child_id = pending["repair_mission_id"]
            self.assertEqual(1, len(client.children))
            self.assertNotIn("super-secret", pending["post_verify_failure"])

            waiting = instance.tick()
            self.assertEqual("post_verify_repair_waiting", waiting["action"])
            self.assertEqual(2, client.accept_calls)
            self.assertEqual(1, len(client.children))
            self.assertEqual("post_verify_repair_waiting", instance.tick()["action"])
            self.assertEqual(1, counters["post_verify"])

            repair_profile = profile(root)
            repair_profile.update(
                dispatch_profile="build1-vpnrouter-repair",
                goal="Repair the exact post-verify failure",
            )
            child_instance = coordinator.DeliveryCoordinator(
                repair_profile, client, backend, root / "state"
            )
            child_paths = child_instance._paths(child_id)
            child_state = child_instance._load_state(child_id, child_paths)
            self.assertEqual("mission-a7-3", child_state["parent_mission_id"])
            self.assertEqual(["windows post-verify [REDACTED] failed"], child_state["review_findings"])

            client.children[child_id]["status"] = "completed"
            result = instance.tick()
            self.assertEqual("complete", result["action"])
            self.assertEqual(2, counters["post_verify"])
            self.assertEqual(0, counters["authors"])
            self.assertEqual("repaired-default-sha", result["state"]["default_sha"])
            self.assertEqual(1, counters["cleanups"])

    def test_failed_repair_cannot_spawn_recursively_and_preserves_merged_pr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved["post_verify_repair"] = {
                "dispatch_profile": "build1-vpnrouter-repair",
                "goal": "Repair the exact post-verify failure",
            }
            client = RepairClient()
            client.lose_first_accept_response = False
            child_id = coordinator.DeliveryCoordinator._repair_mission_id("mission-a7-3")
            client.children[child_id] = {
                "mission_id": child_id,
                "goal": "Repair the exact post-verify failure",
                "dispatch_profile": "build1-vpnrouter-repair",
                "parent_mission_id": "mission-a7-3",
                "status": "failed",
                "error": "repair exhausted",
            }
            instance = coordinator.DeliveryCoordinator(
                approved, client, FakeBackend(), root / "state"
            )
            paths = instance._paths("mission-a7-3")
            state = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "post_verify_repair_waiting",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 3,
                "crash_injected": True,
                "root_task_id": "task-1",
                "run_id": "7",
                "pr_url": "https://example.invalid/pr/39",
                "repair_mission_id": child_id,
                "failed_default_sha": "failed-default-sha",
            }
            self.assertIsNone(instance._observe_post_verify_repair(state, paths))
            self.assertEqual("post_verify_failed", state["phase"])
            self.assertEqual("post_verify", state["failure_kind"])
            result, summary, events = instance._failure_contract(state)
            self.assertEqual("post_verify_failed", result)
            self.assertIn("Post-verify failed", summary)
            self.assertIn(
                {
                    "type": "delivery.upsert",
                    "payload": {
                        "kind": "pull_request",
                        "status": "merged",
                        "url": "https://example.invalid/pr/39",
                    },
                },
                events,
            )
            self.assertNotIn(
                {"type": "delivery.upsert", "payload": {"kind": "pull_request", "status": "failed"}},
                events,
            )
            before = state["repair_mission_id"]
            instance._record_post_verify_failure(
                state, paths, coordinator.PostVerifyFailed("second failure")
            )
            self.assertEqual(before, state["repair_mission_id"])
            self.assertEqual("post_verify_failed", state["phase"])


if __name__ == "__main__":
    unittest.main()
