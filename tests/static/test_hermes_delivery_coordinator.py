#!/usr/bin/env python3
"""Hermetic A7.3 delivery coordinator crash/restart gate."""

from __future__ import annotations

import importlib
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


def profile(root: pathlib.Path) -> dict:
    return {
        "schema_version": 1,
        "dispatch_profile": "build1-vpnrouter-a7-3",
        "goal": "Fix issue 39",
        "repo": "PavelLizunov/VPNRouter",
        "remote": "https://github.com/PavelLizunov/VPNRouter.git",
        "source_checkout": str(root / "source"),
        "default_branch": "main",
        "worktree_root": str(root / "worktrees"),
        "branch_prefix": "codex/a7-3-vpnrouter",
        "assignee": "coordinator-codex-luna-a7",
        "author_model": "gpt-5.6-luna",
        "reviewer_model": "gpt-5.6-sol",
        "required_files": ["Cli.cs", "Core.cs", "Tests.cs"],
        "author_checks": [["dotnet", "test"]],
        "review_checks": [["dotnet", "test"]],
        "post_verify_checks": [["dotnet", "test"], ["windows-brat", "status"]],
        "required_ci_checks": ["test"],
        "commit_message": "fix(cli): detect active runtime",
        "pull_request_title": "fix(cli): report active runtime",
        "pull_request_body": "Closes #39",
        "max_review_cycles": 2,
        "claim_ttl_seconds": 28800,
        "command_timeout_seconds": 900,
        "ci_timeout_seconds": 900,
        "crash_after_author_commit_once": True,
    }


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

    def edit_metadata(self, _task_id, **_kwargs):
        return self.show("task-1")

    def read_log(self, _task_id):
        return ""


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
        if gates == {"tests": "passed", "review": "failed", "cleanup": "passed"}:
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

    def _cleanup(self, state, paths):
        self.counters["cleanups"] += 1
        for name in ("author", "review", "verify"):
            if paths[name].exists():
                paths[name].rmdir()


class DeliveryCoordinatorTests(unittest.TestCase):
    def test_profile_is_closed_and_requires_distinct_exact_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "profile.json"
            value = profile(pathlib.Path(directory))
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = coordinator.load_profile(path)
            self.assertEqual("gpt-5.6-luna", loaded["author_model"])
            value["reviewer_model"] = value["author_model"]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "must differ"):
                coordinator.load_profile(path)

            value = profile(pathlib.Path(directory))
            value["assignee"] = "real-hermes-profile"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(coordinator.DeliveryError, "reserved non-routable"):
                coordinator.load_profile(path)

    def test_required_ci_check_must_exist_and_succeed(self):
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
                if command[1] == "api":
                    output = "candidate-sha\n"
                elif "state,mergedAt,mergeCommit,url" in command:
                    output = json.dumps({"state": "OPEN", "mergedAt": None, "mergeCommit": None})
                elif "statusCheckRollup" in command:
                    output = json.dumps({
                        "statusCheckRollup": [{"name": "test", "conclusion": "FAILURE"}]
                    })
                else:
                    raise AssertionError(command)
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            instance = coordinator.DeliveryCoordinator(
                approved, FakeClient(), backend, root / "state", runner=runner
            )
            state = {
                "root_task_id": "task-1",
                "run_id": "7",
                "candidate_sha": "candidate-sha",
                "pr_number": 39,
                "ci_checks": [{"name": "test", "conclusion": "SUCCESS"}],
            }
            with (
                mock.patch.object(instance, "_wait_ci"),
                mock.patch.object(instance, "_validate_review"),
            ):
                with self.assertRaisesRegex(coordinator.DeliveryError, "not green"):
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
        self.assertIn("OnUnitActiveSec=1min", timer)
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
            instance._save(
                paths,
                {
                    "schema_version": 1,
                    "mission_id": "mission-a7-3",
                    "dispatch_profile": approved["dispatch_profile"],
                    "phase": "task_completed",
                    "branch": "codex/a7-3-vpnrouter-deadbeef",
                    "review_cycle": 1,
                    "crash_injected": True,
                },
            )
            result = instance.tick()
            self.assertEqual("complete", result["action"])

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

    def test_final_review_rejection_checkpoint_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = profile(root)
            approved.update(codex_bin="codex", codex_home=str(root / "codex"))
            client = FakeClient()
            backend = FakeBackend()
            backend.claim("task-1", ttl_seconds=approved["claim_ttl_seconds"])

            def runner(command, **_kwargs):
                last = pathlib.Path(
                    command[command.index("--output-last-message") + 1]
                )
                last.write_text(
                    json.dumps({"verdict": "reject", "findings": ["still broken"]}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout='{"type":"thread.started","thread_id":"review-session"}\n',
                    stderr="",
                )

            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state", runner=runner
            )
            paths = instance._paths("mission-a7-3")
            paths["review"].mkdir(parents=True)
            state = {
                "schema_version": 1,
                "mission_id": "mission-a7-3",
                "dispatch_profile": approved["dispatch_profile"],
                "phase": "author_committed",
                "branch": "codex/a7-3-vpnrouter-deadbeef",
                "review_cycle": 2,
                "crash_injected": True,
                "candidate_sha": "candidate-sha",
                "root_task_id": "task-1",
                "run_id": "7",
            }
            telemetry = {"model": approved["reviewer_model"], "session_id": "review-session"}
            with (
                mock.patch.object(instance, "_assert_claim"),
                mock.patch.object(instance, "_remove_worktree"),
                mock.patch.object(instance, "_git"),
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
                self.assertFalse(instance._review(state, paths))

            persisted = coordinator.mission_adapter._read_json(paths["state"])
            self.assertEqual("review_rejected", persisted["phase"])
            self.assertEqual(["still broken"], persisted["review_findings"])
            self.assertEqual("reject", persisted["review_verification"]["verdict"])

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


if __name__ == "__main__":
    unittest.main()
