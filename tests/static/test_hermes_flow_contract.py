#!/usr/bin/env python3
import importlib.util
import hashlib
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "swarm" / "flow_contract.py"
SPEC = importlib.util.spec_from_file_location("flow_contract", MODULE_PATH)
flow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(flow)

INSTALLER_PATH = ROOT / "tools" / "swarm" / "install_flow_v2.py"
INSTALLER_SPEC = importlib.util.spec_from_file_location("install_flow_v2", INSTALLER_PATH)
installer = importlib.util.module_from_spec(INSTALLER_SPEC)
assert INSTALLER_SPEC.loader
INSTALLER_SPEC.loader.exec_module(installer)


def artifact(engine_family, model, sha, *, reviewer=False):
    base = {
        "schema_version": 1,
        "engine_family": engine_family,
        "model": model,
        "reasoning_effort": "xhigh",
        "session_id": "review-session" if reviewer else "author-session",
        "checks": [{"command": "python -m unittest", "exit_code": 0}],
    }
    if reviewer:
        base.update({
            "reviewed_sha": sha, "verdict": "accept", "review_cycle": 1, "findings": [],
            "review_mode": "cross_family",
        })
    else:
        base.update({
            "repo": "PavelLizunov/hermes-flow-pilot", "branch": "agent/pilot", "head_sha": sha,
            "task_class": "standard_code",
            "changed_files": ["src/lib.rs"],
        })
    return base


def telemetry(value, component, sandbox):
    return {
        "schema_version": 1,
        "component": component,
        "engine": "codex",
        "engine_family": value["engine_family"],
        "model": value["model"],
        "model_attestation": "codex_rollout_turn_context",
        "reasoning_effort": value["reasoning_effort"],
        "reasoning_effort_attestation": "codex_rollout_turn_context",
        "sandbox": sandbox,
        "sandbox_attestation": "codex_rollout_turn_context",
        "session_id": value["session_id"],
        "status": "completed",
        "head_sha": value["reviewed_sha" if component == "reviewer" else "head_sha"],
        "tree_sha": "tree-sha",
        "repo_attestation": (
            "codex_rollout_prompt_sha256" if component == "reviewer" else "post_turn_clean_head"
        ),
        "source_attestation_sha256": "source-sha" if component == "reviewer" else None,
        "worktree_clean": True,
    }


def validate_review(summary, verification, **kwargs):
    return flow.validate_review(
        summary,
        verification,
        telemetry(summary, "author", "workspace-write"),
        telemetry(verification, "reviewer", "read-only"),
        **kwargs,
    )


class FlowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((ROOT / "tools" / "swarm" / "flow-policy.json").read_text())

    def test_quota_blocked_claude_is_not_selected(self):
        quota = {
            "schema_version": 1,
            "engines": {
                "codex": {"state": "available"},
                "claude": {"state": "quota_blocked"},
                "ornith": {"state": "available"},
                "qwen": {"state": "available"},
            },
        }
        routed = flow.choose_route(self.policy, quota, "standard_code")
        self.assertEqual("ready", routed["status"])
        self.assertEqual("codex", routed["author"]["engine"])
        self.assertEqual("gpt-5.6-sol", routed["reviewer"]["model"])
        self.assertEqual("same_provider_degraded", routed["review_mode"])
        self.assertEqual(
            [
                {"engine": "claude", "reason": "quota_blocked"},
            ],
            routed["skipped"]["reviewers"],
        )

        local = flow.choose_route(self.policy, quota, "low_risk_local")
        self.assertEqual("author_blocked", local["status"])
        local = flow.choose_route(self.policy, quota, "low_risk_local", allow_local=True)
        self.assertEqual("ready", local["status"])
        self.assertEqual("ornith", local["author"]["engine"])
        self.assertEqual("qwen", local["reviewer"]["engine"])

    def test_stale_or_same_family_review_is_rejected(self):
        summary = artifact("openai", "gpt-5.3-codex-spark", "aaa")
        verification = artifact("anthropic", "claude-sonnet-4-6", "aaa", reviewer=True)
        with self.assertRaisesRegex(flow.ContractError, "stale review"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="bbb", ci_green=True
            )
        verification["reviewed_sha"] = "aaa"
        verification["engine_family"] = "openai"
        with self.assertRaisesRegex(flow.ContractError, "different engine families"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True
            )

    def test_same_provider_degraded_review_requires_distinct_model_and_session(self):
        summary = artifact("openai", "gpt-5.6-luna", "aaa")
        verification = artifact("openai", "gpt-5.6-sol", "aaa", reviewer=True)
        verification["review_mode"] = "same_provider_degraded"
        with self.assertRaisesRegex(flow.ContractError, "different engine families"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True
            )
        validate_review(
            summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True,
            allow_same_provider_review=True,
        )
        verification["model"] = summary["model"]
        with self.assertRaisesRegex(flow.ContractError, "different exact models"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )
        verification["model"] = "gpt-5.6-sol"
        verification["session_id"] = summary["session_id"]
        with self.assertRaisesRegex(flow.ContractError, "different sessions"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )

    def test_high_risk_route_stays_blocked_without_cross_family_reviewer(self):
        quota = {"schema_version": 1, "engines": {
            "codex": {"state": "available"}, "claude": {"state": "quota_blocked"}
        }}
        routed = flow.choose_route(self.policy, quota, "complex_rust")
        self.assertEqual("review_blocked", routed["status"])
        self.assertIsNone(routed["reviewer"])

    def test_delivery_policy_uses_the_approved_standard_route(self):
        decision = flow.choose_delivery_route(
            self.policy,
            {
                "schema_version": 1,
                "changed_files": 3,
                "prior_review_rejections": 0,
                "flags": [],
            },
            {"schema_version": 1, "engines": {
                "codex": {"state": "available"}, "claude": {"state": "quota_blocked"},
            }},
        )
        self.assertEqual("ready", decision["status"])
        self.assertEqual("standard", decision["route"])
        self.assertEqual("gpt-5.6-luna", decision["author"]["model"])
        self.assertEqual("medium", decision["author"]["reasoning_effort"])
        self.assertEqual("gpt-5.6-sol", decision["reviewer"]["model"])
        self.assertEqual("low", decision["reviewer"]["reasoning_effort"])
        self.assertEqual("same_provider_degraded", decision["review_mode"])
        self.assertEqual(64, len(decision["quota_sha256"]))
        self.assertEqual(["default:standard"], decision["reasons"])

    def test_delivery_policy_prefers_available_cross_family_review(self):
        decision = flow.choose_delivery_route(
            self.policy,
            {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
            {"schema_version": 1, "engines": {
                "codex": {"state": "available"}, "claude": {"state": "available"},
            }},
            model_overrides={"claude": "claude-sonnet-4-6"},
        )
        self.assertEqual("ready", decision["status"])
        self.assertEqual("gpt-5.6-luna", decision["author"]["model"])
        self.assertEqual("claude-sonnet-4-6", decision["reviewer"]["model"])
        self.assertEqual("cross_family", decision["review_mode"])
        with self.assertRaisesRegex(flow.ContractError, "exact model ID required"):
            flow.choose_delivery_route(
                self.policy,
                {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
                {"schema_version": 1, "engines": {
                    "codex": {"state": "available"}, "claude": {"state": "available"},
                }},
                model_overrides={"claude": "default"},
            )

    def test_delivery_policy_does_not_degrade_without_proved_quota_block(self):
        decision = flow.choose_delivery_route(
            self.policy,
            {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
            {"schema_version": 1, "engines": {
                "codex": {"state": "available"}, "claude": {"state": "available"},
            }},
        )
        self.assertEqual("review_blocked", decision["status"])
        self.assertIsNone(decision["author"])
        self.assertIsNone(decision["reviewer"])
        with self.assertRaisesRegex(flow.ContractError, "quota: schema_version 1"):
            flow.choose_delivery_route(
                self.policy,
                {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
                {"schema_version": True, "engines": {
                    "codex": {"state": "available"}, "claude": {"state": "quota_blocked"},
                }},
            )
        with self.assertRaisesRegex(flow.ContractError, "quota.engines.codex: expected an object"):
            flow.choose_delivery_route(
                self.policy,
                {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
                {"schema_version": 1, "engines": {
                    "codex": [], "claude": {"state": "quota_blocked"},
                }},
            )
        with self.assertRaisesRegex(flow.ContractError, "quota.engines.claude.blocked_until"):
            flow.choose_delivery_route(
                self.policy,
                {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
                {"schema_version": 1, "engines": {
                    "codex": {"state": "available"},
                    "claude": {"state": "quota_blocked", "blocked_until": 1},
                }},
            )
        with self.assertRaisesRegex(flow.ContractError, "quota.engines.claude.state: invalid state"):
            flow.choose_delivery_route(
                self.policy,
                {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []},
                {"schema_version": 1, "engines": {
                    "codex": {"state": "available"}, "claude": {"state": []},
                }},
            )

    def test_delivery_policy_standard_identity_binds_quota_state(self):
        signals = {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []}
        blocked = {"schema_version": 1, "engines": {
            "codex": {"state": "available"}, "claude": {"state": "quota_blocked"},
        }}
        available = {"schema_version": 1, "engines": {
            "codex": {"state": "available"}, "claude": {"state": "available"},
        }}
        first = flow.choose_delivery_route(self.policy, signals, blocked)
        second = flow.choose_delivery_route(
            self.policy, signals, available, model_overrides={"claude": "claude-sonnet-4-6"}
        )
        self.assertNotEqual(first["quota_sha256"], second["quota_sha256"])
        self.assertNotEqual(first["decision_id"], second["decision_id"])

    def test_delivery_policy_proposes_but_does_not_run_a_complex_route(self):
        decision = flow.choose_delivery_route(self.policy, {
            "schema_version": 1,
            "changed_files": 6,
            "prior_review_rejections": 0,
            "flags": ["cross_process", "multi_platform"],
        })
        self.assertEqual("owner_approval_required", decision["status"])
        self.assertEqual("complex", decision["route"])
        self.assertIsNone(decision["author"])
        self.assertIsNone(decision["reviewer"])
        self.assertEqual("gpt-5.6-sol", decision["proposed_route"]["author"]["model"])
        self.assertEqual("gpt-5.6-terra", decision["proposed_route"]["reviewer"]["model"])
        self.assertEqual(
            ["flag:cross_process", "flag:multi_platform", "changed_files>=6"],
            decision["reasons"],
        )

    def test_delivery_policy_escalates_repeated_rejection_without_model_authority(self):
        signals = {
            "schema_version": 1,
            "changed_files": 6,
            "prior_review_rejections": 5,
            "flags": ["cross_process", "durable_state", "multi_platform"],
        }
        first = flow.choose_delivery_route(self.policy, signals)
        second = flow.choose_delivery_route(self.policy, signals)
        self.assertEqual(first, second)
        self.assertEqual("owner_approval_required", first["status"])
        self.assertEqual("escalated", first["route"])
        self.assertEqual(["prior_review_rejections>=2"], first["reasons"])
        self.assertEqual("gpt-5.6-terra", first["proposed_route"]["author"]["model"])
        self.assertEqual("gpt-5.6-sol", first["proposed_route"]["reviewer"]["model"])
        self.assertEqual(64, len(first["decision_id"]))

    def test_delivery_policy_identity_is_semantic_and_binds_the_exact_policy(self):
        signals = {
            "schema_version": 1,
            "changed_files": 1,
            "prior_review_rejections": 0,
            "flags": ["concurrency", "cross_process"],
        }
        first = flow.choose_delivery_route(self.policy, signals)
        reordered = flow.choose_delivery_route(
            self.policy, {**signals, "flags": list(reversed(signals["flags"]))}
        )
        self.assertEqual(first, reordered)
        changed = json.loads(json.dumps(self.policy))
        changed["delivery_model_policy"]["routes"]["complex"]["author"]["model"] = (
            "gpt-5.6-terra"
        )
        changed["delivery_model_policy"]["routes"]["complex"]["reviewer"]["model"] = (
            "gpt-5.6-sol"
        )
        second = flow.choose_delivery_route(changed, signals)
        self.assertNotEqual(first["policy_sha256"], second["policy_sha256"])
        self.assertNotEqual(first["decision_id"], second["decision_id"])
        changed = json.loads(json.dumps(self.policy))
        changed["engines"]["codex"]["capacity_label"] = "changed-capacity"
        second = flow.choose_delivery_route(changed, signals)
        self.assertNotEqual(first["policy_sha256"], second["policy_sha256"])
        self.assertNotEqual(first["decision_id"], second["decision_id"])

    def test_delivery_policy_v1_cannot_standing_approve_a_stronger_route(self):
        changed = json.loads(json.dumps(self.policy))
        changed["delivery_model_policy"]["routes"]["escalated"]["standing_approved"] = True
        with self.assertRaisesRegex(flow.ContractError, "never standing-approves stronger routes"):
            flow.choose_delivery_route(changed, {
                "schema_version": 1,
                "changed_files": 1,
                "prior_review_rejections": 0,
                "flags": [],
            })

        changed = json.loads(json.dumps(self.policy))
        changed["delivery_model_policy"]["routes"]["standard"]["standing_approved"] = False
        with self.assertRaisesRegex(flow.ContractError, "standard route to be standing-approved"):
            flow.choose_delivery_route(changed, {
                "schema_version": 1,
                "changed_files": 6,
                "prior_review_rejections": 0,
                "flags": ["cross_process"],
            })

    def test_delivery_policy_validates_nonselected_routes(self):
        changed = json.loads(json.dumps(self.policy))
        changed["delivery_model_policy"]["routes"]["complex"]["author"]["extra"] = "ignored"
        with self.assertRaisesRegex(flow.ContractError, "route.complex.author: unknown fields"):
            flow.choose_delivery_route(changed, {
                "schema_version": 1,
                "changed_files": 1,
                "prior_review_rejections": 0,
                "flags": [],
            })

        changed = json.loads(json.dumps(self.policy))
        changed["delivery_model_policy"]["routes"]["standard"]["task_class"] = "complex_rust"
        with self.assertRaisesRegex(flow.ContractError, "expected ADR-028 standard_code"):
            flow.choose_delivery_route(changed, {
                "schema_version": 1,
                "changed_files": 6,
                "prior_review_rejections": 0,
                "flags": ["cross_process"],
            })

        changed = json.loads(json.dumps(self.policy))
        changed["schema_version"] = True
        with self.assertRaisesRegex(flow.ContractError, "policy: schema_version 1"):
            flow.choose_delivery_route(changed, {
                "schema_version": 1,
                "changed_files": 6,
                "prior_review_rejections": 0,
                "flags": ["cross_process"],
            })

    def test_delivery_policy_pins_the_existing_standard_route(self):
        signals = {"schema_version": 1, "changed_files": 1, "prior_review_rejections": 0, "flags": []}
        quota = {"schema_version": 1, "engines": {
            "codex": {"state": "available"}, "claude": {"state": "quota_blocked"},
        }}
        changed = json.loads(json.dumps(self.policy))
        changed["routes"]["standard_code"]["risk"] = "high"
        with self.assertRaisesRegex(flow.ContractError, "invalid ADR-028 route"):
            flow.choose_delivery_route(changed, signals, quota)
        changed = json.loads(json.dumps(self.policy))
        changed["routes"]["standard_code"]["authors"][0]["model"] = "gpt-5.3-codex-spark"
        with self.assertRaisesRegex(flow.ContractError, "expected Codex Luna"):
            flow.choose_delivery_route(changed, signals, quota)
        changed = json.loads(json.dumps(self.policy))
        changed["engines"]["codex"]["family"] = "untrusted"
        with self.assertRaisesRegex(flow.ContractError, "unexpected standard-route boundary"):
            flow.choose_delivery_route(changed, signals, quota)

    def test_delivery_policy_rejects_boolean_schema_version(self):
        with self.assertRaisesRegex(flow.ContractError, "signals.schema_version: expected 1"):
            flow.choose_delivery_route(self.policy, {
                "schema_version": True,
                "changed_files": 1,
                "prior_review_rejections": 0,
                "flags": [],
            })

    def test_delivery_policy_fails_closed_on_unknown_or_privileged_signals(self):
        base = {
            "schema_version": 1,
            "changed_files": 1,
            "prior_review_rejections": 0,
            "flags": ["local_or_gpu"],
        }
        gated = flow.choose_delivery_route(self.policy, base)
        self.assertEqual("owner_approval_required", gated["status"])
        self.assertEqual(["flag:local_or_gpu"], gated["reasons"])
        with self.assertRaisesRegex(flow.ContractError, "unknown flags"):
            flow.choose_delivery_route(self.policy, {**base, "flags": ["model_guessed_this"]})

    def test_review_gate_rejects_mismatched_runtime_attestation(self):
        summary = artifact("openai", "gpt-5.6-luna", "aaa")
        verification = artifact("openai", "gpt-5.6-sol", "aaa", reviewer=True)
        verification["review_mode"] = "same_provider_degraded"
        author = telemetry(summary, "author", "workspace-write")
        reviewer = telemetry(verification, "reviewer", "read-only")
        author["model"] = "gpt-5.6-sol"
        with self.assertRaisesRegex(flow.ContractError, "runtime attestation mismatch"):
            flow.validate_review(
                summary, verification, author, reviewer,
                expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )
        author = telemetry(summary, "author", "workspace-write")
        reviewer["sandbox"] = "workspace-write"
        with self.assertRaisesRegex(flow.ContractError, "expected 'read-only'"):
            flow.validate_review(
                summary, verification, author, reviewer,
                expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )
        reviewer = telemetry(verification, "reviewer", "read-only")
        reviewer["head_sha"] = "bbb"
        with self.assertRaisesRegex(flow.ContractError, "clean exact-SHA"):
            flow.validate_review(
                summary, verification, author, reviewer,
                expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )
        reviewer = telemetry(verification, "reviewer", "read-only")
        reviewer.pop("reasoning_effort")
        with self.assertRaisesRegex(flow.ContractError, "reasoning_effort"):
            flow.validate_review(
                summary, verification, author, reviewer,
                expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )
        summary.pop("reasoning_effort")
        verification.pop("reasoning_effort")
        author = telemetry({**summary, "reasoning_effort": "xhigh"}, "author", "workspace-write")
        reviewer = telemetry(
            {**verification, "reasoning_effort": "xhigh"}, "reviewer", "read-only"
        )
        author.pop("reasoning_effort")
        reviewer.pop("reasoning_effort")
        with self.assertRaisesRegex(flow.ContractError, "reasoning_effort"):
            flow.validate_review(
                summary, verification, author, reviewer,
                expected_repo=summary["repo"], current_head="aaa", ci_green=True,
                allow_same_provider_review=True,
            )

    def test_review_cycles_and_terminal_lifecycle_are_bounded(self):
        summary = artifact("openai", "gpt-5.3-codex-spark", "aaa")
        verification = artifact("anthropic", "claude-sonnet-4-6", "aaa", reviewer=True)
        verification["review_cycle"] = 3
        with self.assertRaisesRegex(flow.ContractError, "review_cycle"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True
            )
        self.assertFalse(
            flow.terminal_complete(
                merged=True, main_contains_head=True, branch_deleted=True, worktree_removed=False
            )
        )
        self.assertTrue(
            flow.terminal_complete(
                merged=True, main_contains_head=True, branch_deleted=True, worktree_removed=True
            )
        )

    def test_merge_gate_requires_exact_models_accept_and_green_ci(self):
        summary = artifact("openai", "gpt-5.3-codex-spark", "aaa")
        verification = artifact("anthropic", "claude-sonnet-4-6", "aaa", reviewer=True)
        with self.assertRaisesRegex(flow.ContractError, "required CI"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=False
            )
        verification["verdict"] = "reject"
        with self.assertRaisesRegex(flow.ContractError, "verdict"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True
            )
        verification["verdict"] = "accept"
        verification["model"] = "default"
        with self.assertRaisesRegex(flow.ContractError, "exact model ID"):
            validate_review(
                summary, verification, expected_repo=summary["repo"], current_head="aaa", ci_green=True
            )

    def test_wrong_repo_remote_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "pilot"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin",
                 "https://github.com/PavelLizunov/unified-agent-platform.git"],
                check=True,
            )
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "flow-test"], check=True, capture_output=True)
            with self.assertRaisesRegex(flow.ContractError, "remote mismatch"):
                flow.guard_repo(
                    repo, "https://github.com/PavelLizunov/hermes-flow-pilot.git", "flow-test"
                )

    def test_primary_checkout_is_not_accepted_as_worker_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "pilot"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            remote = "https://github.com/PavelLizunov/hermes-flow-pilot.git"
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "flow-test"], check=True, capture_output=True)
            with self.assertRaisesRegex(flow.ContractError, "primary checkout"):
                flow.guard_repo(repo, remote, "flow-test")

    def test_codex_telemetry_is_attributed_to_exact_session_and_model(self):
        worktree = pathlib.Path(".").resolve()
        events = [
            {"type": "thread.started", "thread_id": "session-1"},
            {"type": "item.completed", "item": {"type": "file_change", "status": "completed"}},
            {"type": "item.completed", "item": {
                "type": "command_execution", "status": "failed", "aggregated_output": "boom"
            }},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
        ]
        rollout_events = [
            {"type": "session_meta", "payload": {
                "id": "session-1", "session_id": "session-1",
                "model_provider": "openai", "cli_version": "0.144.3",
                "cwd": str(worktree), "timestamp": "2026-07-15T08:00:00Z",
            }},
            {"type": "turn_context", "payload": {
                "model": "gpt-5.3-codex-spark",
                "effort": "xhigh",
                "sandbox_policy": {"type": "workspace-write", "network_access": False},
            }},
        ]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
            path = pathlib.Path(handle.name)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            for event in rollout_events:
                handle.write(json.dumps(event) + "\n")
            rollout = pathlib.Path(handle.name)
        try:
            with mock.patch.object(
                flow, "_repo_attestation",
                return_value={"head_sha": "aaa", "worktree_clean": True},
            ):
                result = flow.summarize_codex_events(
                    path, component="author", model="gpt-5.3-codex-spark",
                    reasoning_effort="xhigh",
                    rollout=rollout, sandbox="workspace-write", worktree=".", head="aaa",
                )
                with self.assertRaisesRegex(flow.ContractError, "runtime model mismatch"):
                    flow.summarize_codex_events(
                        path, component="author", model="gpt-5.6-luna",
                        reasoning_effort="xhigh",
                        rollout=rollout, sandbox="workspace-write", worktree=".", head="aaa",
                    )
                with self.assertRaisesRegex(flow.ContractError, "runtime sandbox mismatch"):
                    flow.summarize_codex_events(
                        path, component="author", model="gpt-5.3-codex-spark",
                        reasoning_effort="xhigh",
                        rollout=rollout, sandbox="read-only", worktree=".", head="aaa",
                    )
                with self.assertRaisesRegex(flow.ContractError, "runtime reasoning effort mismatch"):
                    flow.summarize_codex_events(
                        path, component="author", model="gpt-5.3-codex-spark",
                        reasoning_effort="high", rollout=rollout, sandbox="workspace-write",
                        worktree=".", head="aaa",
                    )
            rerouted_events = events[:-1] + [
                {"type": "item.completed", "item": {
                    "type": "error", "message": "model rerouted: a -> b (reason)",
                }},
                events[-1],
            ]
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                for event in rerouted_events:
                    handle.write(json.dumps(event) + "\n")
                rerouted_path = pathlib.Path(handle.name)
            try:
                with self.assertRaisesRegex(flow.ContractError, "model reroute"):
                    flow.summarize_codex_events(
                        rerouted_path, component="author", model="gpt-5.3-codex-spark",
                        reasoning_effort="xhigh",
                        rollout=rollout, sandbox="workspace-write", worktree=".", head="aaa",
                    )
            finally:
                rerouted_path.unlink()
        finally:
            path.unlink()
            rollout.unlink()
        self.assertEqual("session-1", result["session_id"])
        self.assertEqual("gpt-5.3-codex-spark", result["model"])
        self.assertEqual("openai", result["model_provider"])
        self.assertEqual("workspace-write", result["sandbox"])
        self.assertEqual("codex_rollout_turn_context", result["model_attestation"])
        self.assertEqual("xhigh", result["reasoning_effort"])
        self.assertEqual("codex_rollout_turn_context", result["reasoning_effort_attestation"])
        self.assertEqual("post_turn_clean_head", result["repo_attestation"])
        self.assertEqual({"file_change": 1, "command_execution": 1}, result["tool_calls"])
        self.assertEqual(1, result["failed_commands"])

    def test_reviewer_telemetry_is_bound_to_prompted_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            repo = root / "review"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "tracked.txt").write_text("review\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "candidate"], check=True, capture_output=True)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            source = flow.source_attestation(repo, head)
            source["created_at"] = "2026-07-15T08:00:00+00:00"
            unsigned = {key: value for key, value in source.items() if key != "sha256"}
            source["sha256"] = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            source_path = root / "source.json"
            flow.write_json(source_path, source)
            marker = f"UAP_SOURCE_ATTESTATION_SHA256={source['sha256']}"
            events_path = root / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(event) for event in (
                    {"type": "thread.started", "thread_id": "review-session"},
                    {"type": "turn.completed", "usage": {}},
                )) + "\n",
                encoding="utf-8",
            )
            rollout_path = root / "rollout.jsonl"

            def write_rollout(prompt):
                rollout_path.write_text(
                    "\n".join(json.dumps(event) for event in (
                        {"type": "session_meta", "payload": {
                            "id": "review-session", "session_id": "review-session",
                            "model_provider": "openai", "cli_version": "0.144.3",
                            "cwd": str(repo.resolve()), "timestamp": "2026-07-15T08:00:01Z",
                        }},
                        {"type": "response_item", "payload": {
                            "type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        }},
                        {"type": "turn_context", "payload": {
                            "model": "gpt-5.6-sol", "effort": "xhigh",
                            "sandbox_policy": {"type": "read-only"},
                        }},
                    )) + "\n",
                    encoding="utf-8",
                )

            write_rollout(f"Review exact candidate. {marker}")
            result = flow.summarize_codex_events(
                events_path, component="reviewer", model="gpt-5.6-sol",
                reasoning_effort="xhigh",
                rollout=rollout_path, sandbox="read-only", worktree=repo, head=head,
                source_attestation_path=source_path,
            )
            self.assertEqual("codex_rollout_prompt_sha256", result["repo_attestation"])
            self.assertEqual(source["tree_sha"], result["tree_sha"])

            write_rollout("Review exact candidate without the binding marker.")
            with self.assertRaisesRegex(flow.ContractError, "marker must appear exactly once"):
                flow.summarize_codex_events(
                    events_path, component="reviewer", model="gpt-5.6-sol",
                    reasoning_effort="xhigh",
                    rollout=rollout_path, sandbox="read-only", worktree=repo, head=head,
                    source_attestation_path=source_path,
                )

    def test_repo_attestation_requires_clean_exact_head(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "test"], check=True, capture_output=True)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(
                {
                    "worktree": str(repo.resolve()),
                    "head_sha": head,
                    "tree_sha": subprocess.run(
                        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
                        check=True, capture_output=True, text=True,
                    ).stdout.strip(),
                    "worktree_clean": True,
                },
                flow._repo_attestation(repo, head),
            )
            with self.assertRaisesRegex(flow.ContractError, "HEAD mismatch"):
                flow._repo_attestation(repo, "0" * 40)
            (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(flow.ContractError, "must be clean"):
                flow._repo_attestation(repo, head)

    def test_installer_is_idempotent_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory)
            installer.install(ROOT / "tools" / "swarm", home)
            installer.check(ROOT / "tools" / "swarm", home)
            installer.install(ROOT / "tools" / "swarm", home)
            installer.check(ROOT / "tools" / "swarm", home)
            (home / "swarm-bin" / "flow-policy.json").write_text("{}")
            with self.assertRaises(SystemExit):
                installer.check(ROOT / "tools" / "swarm", home)


if __name__ == "__main__":
    unittest.main()
