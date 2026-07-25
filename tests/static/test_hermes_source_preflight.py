#!/usr/bin/env python3
"""Hermetic required-source preflight gate.

Proves the corrected source-preflight contract:

* a required source is a closed, immutable ``source_request`` parsed once at
  intake and replayed deterministically (never reparsed from the goal);
* authority is the selected target repository only — cross-repo sources fail
  closed before any author/reviewer turn or Git mutation/push/PR/CI/deploy;
* a same-target source is fetched through the mocked existing ``gh`` boundary,
  resolved to an immutable commit SHA, fetched by that SHA, and its bounded
  content is bound into BOTH the author and reviewer input;
* changed source content/provenance is rejected fail-closed and never adopted;
* malformed/untrusted refs and paths fail closed;
* restart and lost-response windows are stable/idempotent;
* completion evidence carries bounded source provenance.

No test contacts GitHub or any live service.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "swarm"))
source_preflight = importlib.import_module("source_preflight")
coordinator = importlib.import_module("delivery_coordinator")
mission_adapter = importlib.import_module("mission_adapter")
flow_contract = importlib.import_module("flow_contract")

# Intake parsing is owned by the MissionStore runtime (the coordinator only
# consumes the immutable source_request); load it to test the production parser.
_runtime_spec = importlib.util.spec_from_file_location(
    "source_preflight_runtime", ROOT / "tools" / "hermes-mission" / "runtime.py"
)
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


MISSION_ID = "mission-source-preflight"
TARGET_REPO = "PavelLizunov/VPNRouter"
SOURCE_CONTENT = b"exact handoff content\nline two\n"
CONTENT_SHA256 = hashlib.sha256(SOURCE_CONTENT).hexdigest()
RESOLVED_SHA = "a" * 40
BLOB_SHA = "b" * 40
SOURCE_REQUEST = {"repo": TARGET_REPO, "ref": "main", "path": "docs/spec.md"}


def fake_fetcher(
    content: bytes = SOURCE_CONTENT,
    resolved_ref: str = RESOLVED_SHA,
    blob_sha: str = BLOB_SHA,
):
    calls = []

    def fetcher(repo: str, ref: str, path: str) -> dict:
        calls.append((repo, ref, path))
        return {
            "resolved_ref": resolved_ref,
            "content": content,
            "blob_sha": blob_sha,
            "provenance": {
                "repo": repo,
                "ref": ref,
                "resolved_ref": resolved_ref,
                "path": path,
                "blob_sha": blob_sha,
                "public_url": f"https://github.com/{repo}/blob/{resolved_ref}/{path}",
            },
        }

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


class ParseSourceRequestTests(unittest.TestCase):
    def test_github_blob_url_parses_to_closed_request(self):
        request = runtime.parse_source_request(
            "Implement per https://github.com/PavelLizunov/VPNRouter/blob/main/docs/spec.md"
        )
        self.assertEqual(
            {"repo": "PavelLizunov/VPNRouter", "ref": "main", "path": "docs/spec.md"},
            request,
        )

    def test_sentence_punctuation_is_not_part_of_source_path(self):
        for suffix in (":", ",", ".", ";"):
            request = runtime.parse_source_request(
                "Implement per "
                "https://github.com/PavelLizunov/VPNRouter/blob/main/docs/spec.md"
                + suffix
            )
            self.assertEqual("docs/spec.md", request["path"], suffix)

    def test_commit_sha_ref_is_parsed(self):
        sha = "c" * 40
        request = runtime.parse_source_request(
            f"Implement per https://github.com/PavelLizunov/VPNRouter/blob/{sha}/spec.md"
        )
        self.assertEqual(sha, request["ref"])
        self.assertTrue(source_preflight.is_immutable_ref(request["ref"]))

    def test_unrepresentable_sources_yield_none(self):
        for goal in (
            "реализуй точно по handoff-файлу ~/handoff/plan.md с ops-1",
            "implement exactly per the design-doc from the vpnrouter repository",
            "Implement the plan from https://example.invalid/spec.md",
            "implement based on https://github.com/PavelLizunov/VPNRouter",
            "Fix issue 39",
        ):
            self.assertIsNone(runtime.parse_source_request(goal), goal)

    def test_malformed_ref_or_path_yield_none(self):
        self.assertIsNone(runtime.parse_source_request(
            "x https://github.com/PavelLizunov/VPNRouter/blob/main..evil/spec.md"
        ))
        self.assertIsNone(runtime.parse_source_request(
            "x https://github.com/PavelLizunov/VPNRouter/blob/main/../etc/passwd"
        ))


class ValidationTests(unittest.TestCase):
    def test_validate_source_request_closed_schema(self):
        self.assertEqual(SOURCE_REQUEST, source_preflight.validate_source_request(
            dict(SOURCE_REQUEST)
        ))
        for bad in (
            None, [], {}, {"repo": TARGET_REPO}, {"repo": TARGET_REPO, "ref": "main"},
            {"repo": TARGET_REPO, "ref": "main", "path": "p", "extra": "x"},
        ):
            with self.assertRaises(source_preflight.SourcePreflightError, msg=str(bad)):
                source_preflight.validate_source_request(bad)

    def test_refs(self):
        self.assertTrue(source_preflight.is_immutable_ref(RESOLVED_SHA))
        self.assertFalse(source_preflight.is_immutable_ref("main"))
        self.assertEqual(RESOLVED_SHA, source_preflight.validate_ref(RESOLVED_SHA))
        self.assertEqual("main", source_preflight.validate_ref("main"))
        for ref in (
            "", "main..evil", "main~1", "main^2", "-main", "/main", "ma in",
            "main\x00", "a" * 201, "main.lock", "main/", "@{upstream}", "main:x",
        ):
            with self.assertRaises(source_preflight.SourcePreflightError, msg=ref):
                source_preflight.validate_ref(ref)

    def test_paths(self):
        self.assertEqual("docs/spec.md", source_preflight.validate_path("docs/spec.md"))
        for path in ("", "../etc/passwd", "a/../b", "/abs", "~/x", "a\\b", "a//b", "."):
            with self.assertRaises(source_preflight.SourcePreflightError, msg=path):
                source_preflight.validate_path(path)


class ResolveAndVerifyTests(unittest.TestCase):
    def test_same_target_source_resolves_and_pins_immutable_sha(self):
        fetcher = fake_fetcher()
        binding, content = source_preflight.resolve_source(
            SOURCE_REQUEST, TARGET_REPO, fetcher, mission_id=MISSION_ID,
        )
        self.assertEqual(SOURCE_CONTENT, content)
        self.assertEqual(set(binding), source_preflight.BINDING_FIELDS)
        self.assertEqual(RESOLVED_SHA, binding["resolved_ref"])
        self.assertEqual(CONTENT_SHA256, binding["content_sha256"])
        self.assertEqual(len(SOURCE_CONTENT), binding["size_bytes"])
        self.assertEqual(
            source_preflight.source_request_identity(SOURCE_REQUEST),
            binding["source_request_sha256"],
        )
        # The fetch is pinned to the resolved immutable SHA in provenance.
        self.assertEqual(RESOLVED_SHA, binding["provenance"]["resolved_ref"])
        self.assertEqual([(TARGET_REPO, "main", "docs/spec.md")], fetcher.calls)

    def test_cross_repo_source_is_rejected(self):
        fetcher = fake_fetcher()
        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "cross-repo source is not authorized"
        ):
            source_preflight.resolve_source(
                {"repo": "PavelLizunov/local-llm-evaluation-lab", "ref": "main", "path": "x.md"},
                TARGET_REPO, fetcher, mission_id=MISSION_ID,
            )
        self.assertEqual([], fetcher.calls)

    def test_fetch_failure_fails_closed(self):
        def boom(_repo, _ref, _path):
            raise RuntimeError("network down")

        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "could not be fetched"
        ):
            source_preflight.resolve_source(
                SOURCE_REQUEST, TARGET_REPO, boom, mission_id=MISSION_ID,
            )

    def test_non_immutable_resolved_ref_is_rejected(self):
        def branchy(_repo, _ref, _path):
            return {
                "resolved_ref": "main",  # not a full SHA
                "content": SOURCE_CONTENT,
                "blob_sha": BLOB_SHA,
                "provenance": {"public_url": "https://github.com/x"},
            }

        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "immutable commit SHA"
        ):
            source_preflight.resolve_source(
                SOURCE_REQUEST, TARGET_REPO, branchy, mission_id=MISSION_ID,
            )

    def _binding(self):
        return source_preflight.resolve_source(
            SOURCE_REQUEST, TARGET_REPO, fake_fetcher(), mission_id=MISSION_ID,
        )[0]

    def test_unchanged_source_verifies_idempotently(self):
        binding = self._binding()
        for _ in range(3):
            verified, content = source_preflight.verify_binding(
                binding, fake_fetcher(), mission_id=MISSION_ID, source_request=SOURCE_REQUEST,
            )
            self.assertEqual(binding, verified)
            self.assertEqual(SOURCE_CONTENT, content)

    def test_changed_content_is_rejected_fail_closed(self):
        binding = self._binding()
        changed = fake_fetcher(content=b"tampered\n")
        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "changed after binding"
        ):
            source_preflight.verify_binding(
                binding, changed, mission_id=MISSION_ID, source_request=SOURCE_REQUEST,
            )

    def test_changed_revision_is_rejected_fail_closed(self):
        binding = self._binding()
        moved = fake_fetcher(resolved_ref="d" * 40)
        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "changed after binding"
        ):
            source_preflight.verify_binding(
                binding, moved, mission_id=MISSION_ID, source_request=SOURCE_REQUEST,
            )

    def test_binding_bound_to_request_identity(self):
        binding = self._binding()
        other = {"repo": TARGET_REPO, "ref": "release", "path": "docs/spec.md"}
        with self.assertRaises(source_preflight.SourcePreflightError):
            source_preflight.validate_binding(
                binding, mission_id=MISSION_ID, source_request=other,
            )

    def test_tampered_provenance_is_rejected(self):
        binding = self._binding()
        binding["provenance"]["public_url"] = "https://github.com/evil"
        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "provenance changed"
        ):
            source_preflight.validate_binding(
                binding, mission_id=MISSION_ID, source_request=SOURCE_REQUEST,
            )

    def test_secret_bearing_provenance_is_rejected(self):
        def leaky(_repo, _ref, _path):
            return {
                "resolved_ref": RESOLVED_SHA,
                "content": SOURCE_CONTENT,
                "blob_sha": BLOB_SHA,
                "provenance": {"public_url": "https://x/token=abc"},
            }

        with self.assertRaisesRegex(
            source_preflight.SourcePreflightError, "carries a secret"
        ):
            source_preflight.resolve_source(
                SOURCE_REQUEST, TARGET_REPO, leaky, mission_id=MISSION_ID,
            )

    def test_expected_question_is_deterministic(self):
        first = source_preflight.expected_question(
            SOURCE_REQUEST, mission_id=MISSION_ID, reason="cross-repo",
        )
        second = source_preflight.expected_question(
            SOURCE_REQUEST, mission_id=MISSION_ID, reason="cross-repo",
        )
        self.assertEqual(first, second)
        self.assertTrue(first["question_id"].startswith(source_preflight.QUESTION_PREFIX))
        other = source_preflight.expected_question(
            SOURCE_REQUEST, mission_id=MISSION_ID, reason="unavailable",
        )
        self.assertNotEqual(first["question_id"], other["question_id"])


def source_profile(root: pathlib.Path) -> dict:
    return {
        "schema_version": 3,
        "dispatch_profile": "build1-source-preflight",
        "goal": "Implement the bound source mission",
        "repo": TARGET_REPO,
        "remote": f"https://github.com/{TARGET_REPO}.git",
        "source_checkout": str(root / "source"),
        "default_branch": "main",
        "worktree_root": str(root / "worktrees"),
        "branch_prefix": "codex/source-preflight",
        "assignee": "coordinator-codex-luna-src",
        "required_files": ["spec.md"],
        "author_checks": [["true"]],
        "review_checks": [["true"]],
        "post_verify_checks": [["true"]],
        "required_ci_checks": ["test"],
        "commit_message": "fix: deliver source-bound mission",
        "pull_request_title": "fix: deliver source-bound mission",
        "pull_request_body": "Source-bound delivery.",
        "max_review_cycles": 3,
        "claim_ttl_seconds": 28800,
        "command_timeout_seconds": 900,
        "ci_timeout_seconds": 900,
        "crash_after_author_commit_once": True,
    }


class SourceQuestionClient:
    def __init__(self, *, source_request=None, source_required=None,
                 lose_question_response_once=False):
        self.mission = {
            "mission_id": MISSION_ID,
            "goal": "Implement the bound source mission",
            "dispatch_profile": "build1-source-preflight",
            "status": "active",
            "stage": "accepted",
            "tasks": [],
            "question": None,
            "answer": None,
            "source_request": source_request,
            "source_required": source_required,
        }
        self.events = {}
        self.lose_question_response_once = lose_question_response_once

    def list_missions(self, _profile, *, reconcile=False):
        has_tasks = bool(self.mission["tasks"])
        return [self.mission] if reconcile == has_tasks else []

    def publish(self, _mission_id, event):
        producer_id = event["correlation"]["producer_event_id"]
        previous = self.events.get(producer_id)
        if previous is not None:
            assert previous == event, "producer event changed across retry"
            return
        self.events[producer_id] = event
        if event["type"] == "task.upsert":
            self.mission["tasks"] = [dict(event["payload"])]
        elif event["type"] == "mission.question":
            self.mission.update(
                status="waiting_owner", question=dict(event["payload"]), answer=None,
            )
            if self.lose_question_response_once:
                self.lose_question_response_once = False
                raise mission_adapter.AdapterError(
                    "question committed before response loss"
                )

    def get_mission(self, _mission_id):
        return {**self.mission, "tasks": [dict(t) for t in self.mission["tasks"]]}


class SourceQuestionBackend:
    def __init__(self):
        self.task = None
        self.events = []
        self.runs = []

    def ensure_root(self, *, mission_id, goal, allow_dispatch, assignee, workspace):
        assert not allow_dispatch and assignee is None
        if self.task is None:
            self.task = {
                "id": "task-source",
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
            "events": [dict(e) for e in self.events],
            "runs": [dict(r) for r in self.runs],
        }

    def read_log(self, _task_id):
        return ""

    def resume_root_from_answer(self, task_id, *, assignee, workspace, question_id, answer_digest):
        assert self.task is not None and self.task["id"] == task_id
        assert question_id and answer_digest
        if self.task["status"] == "blocked":
            self.task.update(status="ready", assignee=assignee)
            self.events.append({"kind": "unblocked", "payload": {"reason": question_id}})
        return self.show(task_id)

    def claim(self, task_id, *, ttl_seconds, provenance=None):
        assert self.task is not None
        import time as _time
        expires = int(_time.time()) + ttl_seconds
        self.task.update(status="running", claim_expires=expires)
        run_id = max((int(r["id"]) for r in self.runs), default=6) + 1
        self.runs.append({
            "id": run_id, "status": "running",
            "profile": "coordinator-codex-luna-src",
            "claim_lock": provenance or f"fake-claim-{run_id}",
            "claim_expires": expires,
        })
        return self.show(task_id)

    def verify_claim(self, task_id, run_id, *, min_remaining_seconds=60, provenance=None):
        return self.show(task_id)

    def schedule(self, task_id, *, reason):
        self.task.update(status="scheduled", claim_expires=None)
        return self.show(task_id)

    def unblock(self, task_id, *, reason):
        self.task.update(status="ready", claim_expires=None)
        return self.show(task_id)


class GateIntegrationTests(unittest.TestCase):
    def _paths(self, instance):
        return instance._paths(MISSION_ID)

    def test_no_source_mission_is_unaffected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=None)
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(
                instance, "_fetch_source",
                side_effect=AssertionError("no source must be fetched"),
            ):
                self.assertIsNone(instance._ensure_source_preflight(state, client.mission, paths))
            self.assertNotIn("source_binding", state)

    def test_same_target_source_is_fetched_bound_and_author_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            counters = {"authors": 0}
            fetcher = fake_fetcher()

            class Gate(coordinator.DeliveryCoordinator):
                def _fetch_source(self, repo, ref, path):
                    return fetcher(repo, ref, path)

                def _ensure_worktree(self, state, paths):
                    state.setdefault("base_sha", "base-sha")

                def _git(self, _checkout, *arguments, **_kwargs):
                    if arguments[:2] == ("rev-parse", "HEAD"):
                        return "candidate-sha"
                    return ""

                def _author(self, state, paths):
                    counters["authors"] += 1
                    # The author input must carry the exact bound source.
                    block = self._source_prompt_block(state, paths)
                    assert "exact handoff content" in block
                    assert RESOLVED_SHA in block
                    assert CONTENT_SHA256 in block
                    state.update(
                        phase="author_committed", candidate_sha="candidate-sha",
                        author_summary={}, author_telemetry={},
                    )
                    self._save(paths, state)
                    return True

                def _recover_author_commit(self, state, paths):
                    return False

                def _ensure_claimed(self, state):
                    state.setdefault("run_id", "1")

                def _assert_claim(self, state, **_kwargs):
                    return None

                def _publish_stage(self, state, stage, progress):
                    return None

                def _check_disk_space(self):
                    # Hermetic: the real check calls shutil.disk_usage on the
                    # worktree_root parent, which varies by host (e.g. ops-1 /tmp
                    # has <40 GB free).  Return exactly the minimum so the gate
                    # passes deterministically on every platform.
                    return (
                        coordinator._DISK_SPACE_MIN_FREE_BYTES,
                        coordinator._DISK_SPACE_MIN_FREE_BYTES,
                    )

                def _reconcile_active(self, state):
                    return None

            instance = Gate(approved, client, backend, root / "state")
            with mock.patch.object(
                coordinator.mission_adapter, "coordinator_tick",
                return_value={"root_task_id": "task-source"},
            ):
                with self.assertRaisesRegex(
                    coordinator.InjectedCrash, "after durable author commit"
                ):
                    instance.tick()

            self.assertEqual(1, counters["authors"])
            self.assertEqual([(TARGET_REPO, "main", "docs/spec.md")], fetcher.calls)
            state = mission_adapter._read_json(self._paths(instance)["state"])
            binding = state["source_binding"]
            self.assertEqual(RESOLVED_SHA, binding["resolved_ref"])
            self.assertEqual(CONTENT_SHA256, binding["content_sha256"])
            # Bounded content artifact persisted privately.
            artifact = instance._source_artifact_path(self._paths(instance))
            self.assertEqual(SOURCE_CONTENT, artifact.read_bytes())
            # No owner question for an authorized same-target source.
            self.assertEqual(
                [], [e for e in client.events.values() if e["type"] == "mission.question"]
            )

    def test_author_and_reviewer_receive_the_same_exact_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                self.assertIsNone(instance._ensure_source_preflight(state, client.mission, paths))
            block = instance._source_prompt_block(state, paths)
            for expected in (
                "exact handoff content", RESOLVED_SHA, CONTENT_SHA256,
                "docs/spec.md", TARGET_REPO,
            ):
                self.assertIn(expected, block)

    def test_cross_repo_source_fails_closed_with_owner_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            cross = {"repo": "PavelLizunov/local-llm-evaluation-lab", "ref": "main", "path": "x.md"}
            client = SourceQuestionClient(source_request=cross)
            backend = SourceQuestionBackend()

            class Gate(coordinator.DeliveryCoordinator):
                def _author(self, state, paths):
                    raise AssertionError("author must not run for a cross-repo source")

                def _fetch_source(self, repo, ref, path):
                    raise AssertionError("cross-repo source must not be fetched")

            instance = Gate(approved, client, backend, root / "state")
            waiting = instance.tick()
            self.assertEqual("waiting_owner", waiting["action"])
            self.assertEqual("waiting_owner", client.mission["status"])
            self.assertEqual("blocked", backend.task["status"])
            self.assertEqual([], backend.runs)
            questions = [
                e for e in client.events.values() if e["type"] == "mission.question"
            ]
            self.assertEqual(1, len(questions))
            self.assertTrue(
                questions[0]["payload"]["question_id"].startswith("source-preflight:")
            )

    def test_changed_source_after_binding_fails_closed_before_author(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                self.assertIsNone(instance._ensure_source_preflight(state, client.mission, paths))
            self.assertIn("source_binding", state)
            changed = fake_fetcher(content=b"tampered\n")
            with mock.patch.object(instance, "_fetch_source", side_effect=changed):
                with self.assertRaisesRegex(
                    coordinator.DeliveryError, "changed after binding"
                ):
                    instance._ensure_source_preflight(state, client.mission, paths)

    def test_restart_after_binding_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            fetcher = fake_fetcher()
            with mock.patch.object(instance, "_fetch_source", side_effect=fetcher):
                instance._ensure_source_preflight(state, client.mission, paths)
            instance._save(paths, state)
            first_binding = state["source_binding"]
            self.assertEqual(1, len(fetcher.calls))

            restarted = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            reread = mission_adapter._read_json(paths["state"])
            verify_fetcher = fake_fetcher()
            with mock.patch.object(restarted, "_fetch_source", side_effect=verify_fetcher):
                self.assertIsNone(
                    restarted._ensure_source_preflight(reread, client.mission, paths)
                )
            self.assertEqual(first_binding, reread["source_binding"])
            # Re-verification fetches by the immutable resolved SHA only.
            self.assertEqual([(TARGET_REPO, RESOLVED_SHA, "docs/spec.md")], verify_fetcher.calls)

    def test_source_answer_resumes_same_mission_task_and_run(self):
        # A valid answer binds the immutable source to the SAME mission and the
        # coordinator resumes the same task/run, fetching by the answered SHA
        # before any model/Git; nothing executes before the valid answer.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=None, source_required=True)
            backend = SourceQuestionBackend()
            counters = {"authors": 0}
            fetcher = fake_fetcher()

            class Gate(coordinator.DeliveryCoordinator):
                def _fetch_source(self, repo, ref, path):
                    return fetcher(repo, ref, path)

                def _ensure_worktree(self, state, paths):
                    state.setdefault("base_sha", "base-sha")

                def _git(self, _checkout, *arguments, **_kwargs):
                    if arguments[:2] == ("rev-parse", "HEAD"):
                        return "candidate-sha"
                    return ""

                def _author(self, state, paths):
                    counters["authors"] += 1
                    state.update(
                        phase="author_committed", candidate_sha="candidate-sha",
                        author_summary={}, author_telemetry={},
                    )
                    self._save(paths, state)
                    return True

                def _recover_author_commit(self, state, paths):
                    return False

                def _ensure_claimed(self, state):
                    state.setdefault("run_id", "1")

                def _assert_claim(self, state, **_kwargs):
                    return None

                def _publish_stage(self, state, stage, progress):
                    return None

                def _check_disk_space(self):
                    # Hermetic: the real check calls shutil.disk_usage on the
                    # worktree_root parent, which varies by host (e.g. ops-1 /tmp
                    # has <40 GB free).  Return exactly the minimum so the gate
                    # passes deterministically on every platform.
                    return (
                        coordinator._DISK_SPACE_MIN_FREE_BYTES,
                        coordinator._DISK_SPACE_MIN_FREE_BYTES,
                    )

                def _reconcile_active(self, state):
                    return None

            instance = Gate(approved, client, backend, root / "state")
            waiting = instance.tick()
            self.assertEqual("waiting_owner", waiting["action"])
            self.assertEqual(0, counters["authors"])
            self.assertEqual([], fetcher.calls)  # zero fetch/model/Git before answer
            questions = [
                e for e in client.events.values() if e["type"] == "mission.question"
            ]
            self.assertEqual(1, len(questions))
            question_id = questions[0]["payload"]["question_id"]
            task_id = backend.task["id"]

            # Owner answers with a valid same-target source pinned to a full SHA;
            # Central has bound source.request, so the projection carries it.
            sha = "a" * 40
            client.mission.update(
                status="active", question=None,
                answer={
                    "question_id": question_id,
                    "text": f"https://github.com/{TARGET_REPO}/blob/{sha}/docs/spec.md",
                },
                source_request={"repo": TARGET_REPO, "ref": sha, "path": "docs/spec.md"},
                source_required=None,
            )
            restarted = Gate(approved, client, backend, root / "state")
            with mock.patch.object(
                coordinator.mission_adapter, "coordinator_tick",
                return_value={"root_task_id": task_id},
            ):
                with self.assertRaisesRegex(
                    coordinator.InjectedCrash, "after durable author commit"
                ):
                    restarted.tick()
            self.assertEqual(1, counters["authors"])
            # Fetched by the immutable answered SHA, same target repo/path.
            self.assertEqual([(TARGET_REPO, sha, "docs/spec.md")], fetcher.calls)
            self.assertEqual(task_id, backend.task["id"])  # same task, no new root
            state = mission_adapter._read_json(self._paths(restarted)["state"])
            self.assertEqual("answered", state["source_preflight"]["status"])
            self.assertEqual(sha, state["source_binding"]["resolved_ref"])
            self.assertEqual(
                state["source_binding"]["source_request_sha256"],
                source_preflight.source_request_identity(
                    {"repo": TARGET_REPO, "ref": sha, "path": "docs/spec.md"}
                ),
            )

    def test_source_answer_replay_is_idempotent_after_restart(self):
        # Replaying the same answered mission after restart does not re-fetch a
        # different source or duplicate execution: the durable binding holds.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            sha = "a" * 40
            source_request = {"repo": TARGET_REPO, "ref": sha, "path": "docs/spec.md"}
            client = SourceQuestionClient(source_request=None, source_required=True)
            backend = SourceQuestionBackend()
            fetcher = fake_fetcher()

            class Gate(coordinator.DeliveryCoordinator):
                def _fetch_source(self, repo, ref, path):
                    return fetcher(repo, ref, path)

            instance = Gate(approved, client, backend, root / "state")
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            # Bind as if the answered source.request were already projected.
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                instance._ensure_source_preflight(
                    state, {**client.mission, "source_request": source_request,
                            "source_required": None}, paths,
                )
            instance._save(paths, state)
            first_binding = state["source_binding"]
            # Restart re-verifies by the immutable SHA only (no re-resolve of ref).
            restarted = Gate(approved, client, backend, root / "state")
            reread = mission_adapter._read_json(paths["state"])
            verify_fetcher = fake_fetcher()
            with mock.patch.object(restarted, "_fetch_source", side_effect=verify_fetcher):
                restarted._ensure_source_preflight(
                    reread, {**client.mission, "source_request": source_request,
                             "source_required": None}, paths,
                )
            self.assertEqual(first_binding, reread["source_binding"])
            self.assertEqual([(TARGET_REPO, sha, "docs/spec.md")], verify_fetcher.calls)

    def test_source_question_survives_a_lost_response_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            cross = {"repo": "PavelLizunov/local-llm-evaluation-lab", "ref": "main", "path": "x.md"}
            client = SourceQuestionClient(
                source_request=cross, lose_question_response_once=True,
            )
            backend = SourceQuestionBackend()

            class Gate(coordinator.DeliveryCoordinator):
                def _author(self, state, paths):
                    raise AssertionError("author must not run for an unresolvable source")

            instance = Gate(approved, client, backend, root / "state")
            with self.assertRaisesRegex(
                mission_adapter.AdapterError, "question committed before response loss"
            ):
                instance.tick()
            self.assertEqual("waiting_owner", client.mission["status"])
            self.assertEqual(1, len([
                e for e in client.events.values() if e["type"] == "mission.question"
            ]))
            restarted = Gate(approved, client, backend, root / "state")
            waiting = restarted.tick()
            self.assertEqual("waiting_owner", waiting["action"])
            self.assertEqual(1, len([
                e for e in client.events.values() if e["type"] == "mission.question"
            ]))

    def test_unresolved_source_required_enters_idempotent_question(self):
        # P1-A: a goal that requires a source but has no exact parseable source
        # creates one durable mission (source_required=True, no source_request);
        # the coordinator enters the idempotent waiting_owner question before any
        # route/worktree/model/Git, and restart creates no duplicate question.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=None, source_required=True)
            backend = SourceQuestionBackend()

            class Gate(coordinator.DeliveryCoordinator):
                def _author(self, state, paths):
                    raise AssertionError("author must not run for an unresolved source")

                def _fetch_source(self, repo, ref, path):
                    raise AssertionError("unresolved source must not be fetched")

            instance = Gate(approved, client, backend, root / "state")
            waiting = instance.tick()
            self.assertEqual("waiting_owner", waiting["action"])
            self.assertEqual("waiting_owner", client.mission["status"])
            self.assertEqual("blocked", backend.task["status"])
            self.assertIsNone(backend.task["assignee"])
            self.assertEqual([], backend.runs)
            questions = [
                e for e in client.events.values() if e["type"] == "mission.question"
            ]
            self.assertEqual(1, len(questions))
            text = questions[0]["payload"]["text"]
            # Question requests an exact same-target commit SHA + path and states
            # cross-repo needs separately approved authority.
            self.assertIn("commit SHA", text)
            self.assertIn("path", text)
            self.assertIn("cross-repo", text)

            restarted = Gate(approved, client, backend, root / "state")
            waiting2 = restarted.tick()
            self.assertEqual("waiting_owner", waiting2["action"])
            self.assertEqual(1, len([
                e for e in client.events.values() if e["type"] == "mission.question"
            ]))

    def test_large_source_is_bound_and_prompted_in_full(self):
        # P1-B: content above the 4000-char diagnostic threshold is bound and
        # prompted in full (no tail truncation) and its SHA matches the binding.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            big = ("exact source line\n" * 400).encode("utf-8")  # ~7200 bytes
            self.assertGreater(len(big), 4000)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(
                instance, "_fetch_source", side_effect=fake_fetcher(content=big),
            ):
                self.assertIsNone(instance._ensure_source_preflight(state, client.mission, paths))
            block = instance._source_prompt_block(state, paths)
            decoded = big.decode("utf-8")
            self.assertIn(decoded, block)  # full content, not truncated
            self.assertIn(hashlib.sha256(big).hexdigest(), block)
            self.assertIn("BEGIN REQUIRED SOURCE CONTENT", block)
            self.assertIn("END REQUIRED SOURCE CONTENT", block)

    def test_tampered_artifact_fails_closed_before_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                instance._ensure_source_preflight(state, client.mission, paths)
            artifact = instance._source_artifact_path(paths)
            artifact.write_bytes(b"tampered content\n")
            with self.assertRaisesRegex(
                coordinator.DeliveryError, "changed before prompt"
            ):
                instance._source_prompt_block(state, paths)

    def test_missing_artifact_fails_closed_before_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                instance._ensure_source_preflight(state, client.mission, paths)
            instance._source_artifact_path(paths).unlink()
            with self.assertRaisesRegex(
                coordinator.DeliveryError, "missing before prompt"
            ):
                instance._source_prompt_block(state, paths)

    def test_source_artifact_is_private_and_retention_scoped(self):
        # P1-E: the raw artifact is written under the mission state directory
        # (so it shares the existing completed-state retention/cleanup), holds
        # the exact bound bytes, and is created with restrictive permissions on
        # POSIX (owner-only file in an owner-only parent).
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                instance._ensure_source_preflight(state, client.mission, paths)
            artifact = instance._source_artifact_path(paths)
            # Artifact lives inside the per-mission state directory.
            self.assertEqual(paths["directory"], artifact.parent)
            self.assertEqual(SOURCE_CONTENT, artifact.read_bytes())
            if os.name == "posix":
                import stat
                self.assertEqual(0o600, stat.S_IMODE(artifact.stat().st_mode))
                self.assertEqual(0o700, stat.S_IMODE(artifact.parent.stat().st_mode))

    def test_binding_publishes_owner_visible_source_upsert(self):
        # P1-D: binding publishes bounded provenance (no URL/token/body) to the
        # mission log so the owner-visible projection/terminal result carries it.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            approved = source_profile(root)
            client = SourceQuestionClient(source_request=dict(SOURCE_REQUEST))
            backend = SourceQuestionBackend()
            instance = coordinator.DeliveryCoordinator(
                approved, client, backend, root / "state"
            )
            paths = self._paths(instance)
            paths["directory"].mkdir(parents=True, exist_ok=True)
            state = {
                "schema_version": 1, "mission_id": MISSION_ID,
                "dispatch_profile": approved["dispatch_profile"], "phase": "new",
            }
            with mock.patch.object(instance, "_fetch_source", side_effect=fake_fetcher()):
                instance._ensure_source_preflight(state, client.mission, paths)
            upserts = [
                e for e in client.events.values() if e["type"] == "source.upsert"
            ]
            self.assertEqual(1, len(upserts))
            payload = upserts[0]["payload"]
            self.assertEqual({
                "repo": TARGET_REPO, "resolved_ref": RESOLVED_SHA,
                "path": "docs/spec.md", "content_sha256": CONTENT_SHA256,
            }, payload)
            serialized = json.dumps(payload)
            self.assertNotIn("http", serialized)
            self.assertNotIn("token", serialized)
            self.assertNotIn("exact handoff content", serialized)


class SecretContentTests(unittest.TestCase):
    def _resolve(self, content: bytes):
        return source_preflight.resolve_source(
            SOURCE_REQUEST, TARGET_REPO, fake_fetcher(content=content),
            mission_id=MISSION_ID,
        )

    def test_credential_bearing_source_is_rejected_fail_closed(self):
        gh_token = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        age_key = "AGE-SECRET-" + "KEY-ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        aws_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        pem_header = "-----BEGIN RSA " + "PRIVATE KEY-----"
        slack_token = "xoxb-" + "123456789012-abcdefABCDEF"
        for secret in (
            b"Authorization: Bearer abcdef0123456789\n",
            f'const token = "{gh_token}";\n'.encode(),
            b"access_token=deadbeefdeadbeef\n",
            b"clone from https://user:pass123@github.com/x/y.git\n",
            f"{age_key}\n".encode(),
            f"aws_access_key_id = {aws_key}\n".encode(),
            f"{pem_header}\nMIIE....\n-----END RSA PRIVATE KEY-----\n".encode(),
            f"SLACK_TOKEN={slack_token}\n".encode(),
        ):
            with self.assertRaisesRegex(
                source_preflight.SourcePreflightError, "carries a secret", msg=str(secret)
            ):
                self._resolve(secret)

    def test_benign_windows_path_source_is_accepted(self):
        benign = (
            b"Read the log at C:\\Users\\pavel\\logs\\app.log and\r\n"
            b"summarize the path D:\\data\\reports\\2026\\q3.txt\r\n"
        )
        binding, content = self._resolve(benign)
        self.assertEqual(benign, content)
        self.assertEqual(hashlib.sha256(benign).hexdigest(), binding["content_sha256"])

    def test_benign_prose_about_secrets_is_accepted(self):
        # Narrow guard must not false-positive on ordinary prose that merely
        # mentions credential concepts without a live-secret shape.
        benign = (
            b"Document how the authorization header and the api key are rotated.\n"
            b"Explain that a bearer token and a slack webhook expire, and that an\n"
            b"aws credential is stored in SOPS. No literal secret values here.\n"
        )
        binding, content = self._resolve(benign)
        self.assertEqual(benign, content)


class CompletionEvidenceTests(unittest.TestCase):
    def test_required_source_provenance_validates_in_evidence(self):
        provenance = {
            "repo": TARGET_REPO,
            "resolved_ref": RESOLVED_SHA,
            "path": "docs/spec.md",
            "content_sha256": CONTENT_SHA256,
        }
        bundle = _minimal_evidence_bundle()
        bundle["required_source"] = provenance
        bundle.pop("sha256", None)
        bundle["sha256"] = flow_contract.canonical_sha256(bundle)
        # A complete, valid delivery bundle with required_source passes cleanly.
        validated = flow_contract.validate_completion_evidence(bundle)
        self.assertEqual(provenance, validated["required_source"])

    def test_required_source_rejects_token_or_bad_fields(self):
        bundle = _minimal_evidence_bundle()
        bundle["required_source"] = {
            "repo": TARGET_REPO, "resolved_ref": "notasha",
            "path": "docs/spec.md", "content_sha256": CONTENT_SHA256,
        }
        bundle.pop("sha256", None)
        bundle["sha256"] = flow_contract.canonical_sha256(bundle)
        with self.assertRaisesRegex(
            flow_contract.ContractError, "required_source revision is invalid"
        ):
            flow_contract.validate_completion_evidence(bundle)


def _minimal_evidence_bundle() -> dict:
    """Build the smallest schema_version=1 bundle that passes validation."""
    sha = "0" * 64
    invocation = {
        "unit": "hermes-delivery-coordinator@test.service",
        "invocation_id": "0" * 32,
    }
    bundle = {
        "schema_version": 1,
        "mission": {
            "mission_id": "mission-x", "dispatch_profile": "build1-x",
            "goal_sha256": sha, "parent_mission_id": None,
            "owner_answer_sha256s": [],
        },
        "runtime": {
            "coordinator_sha256": sha, "profile_sha256": sha,
            "policy_sha256": sha,
            "invocations": {
                "count": 1, "first": invocation, "last": invocation,
                "chain_sha256": flow_contract.canonical_sha256(
                    {"previous": None, **invocation}
                ),
            },
        },
        "route": {
            "decision_id": sha, "policy_id": "openai-autonomy-v2",
            "policy_sha256": sha, "route": "standard",
            "author_model": "gpt-5.6-luna", "reviewer_model": "gpt-5.6-sol",
        },
        "execution": {"root_task_id": "task-1", "run_id": "1"},
        "source": {
            "repo": TARGET_REPO, "base_sha": sha, "candidate_sha": sha,
            "candidate_files": ["a.py"], "merge_sha": sha, "default_sha": sha,
            "candidate_ancestor_of_merge": True, "merge_ancestor_of_default": True,
        },
        "author": {
            "session_id": "author-session", "model": "gpt-5.6-luna",
            "reasoning_effort": "medium",
            "sandbox": "workspace-write", "head_sha": sha, "tree_sha": sha,
            "route_decision_id": sha,
        },
        "reviewer": {
            "session_id": "reviewer-session", "model": "gpt-5.6-sol",
            "reasoning_effort": "low",
            "sandbox": "read-only", "reviewed_sha": sha, "head_sha": sha,
            "tree_sha": sha, "route_decision_id": sha,
            "source_attestation_sha256": sha,
        },
        "delivery": {
            "mode": "none", "applicability": "not_applicable", "pr_number": 1,
            "pr_url": f"https://github.com/{TARGET_REPO}/pull/1",
            "pr_head_sha": sha,
            "pr_base_branch": "main", "ci_run_ids": [1],
        },
        "gates": {
            "required_ci_checks": ["test"],
            "pre_review_ci_checks": [{"name": "test", "outcome": "SUCCESS"}],
            "ci_checks": [{"name": "test", "outcome": "SUCCESS"}],
            "post_verify_checks": [{"command": "true", "exit_code": 0}],
        },
        "cleanup": {
            "worktrees_removed": True, "local_branch_deleted": True,
            "remote_branch_deleted": True, "task_archived": True, "kanban_gc_ran": True,
        },
        "central": {
            "status": "completed", "sequence": 1, "projection_id": "0" * 16,
            "result": "done",
        },
    }
    bundle["sha256"] = flow_contract.canonical_sha256(bundle)
    return bundle


if __name__ == "__main__":
    unittest.main(verbosity=2)
