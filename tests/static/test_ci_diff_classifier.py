#!/usr/bin/env python3
"""Deterministic tests for the diff-aware CI fast-path classifier.

These never touch the network or a live repository: the pure `decide()` function
is fed canned `git diff --name-status -z` strings. A separate set of tests parses
the real `.github/workflows/ci.yml` to prove the load-bearing `static-checks`
context is preserved and that the security gates can never be skipped.
"""

from __future__ import annotations

import pathlib
import unittest

import yaml

import ci_diff_classifier as clf

ROOT = pathlib.Path(__file__).resolve().parents[2]
CI_YAML = ROOT / ".github" / "workflows" / "ci.yml"

BASE = "6dbe224606154db05ef877cea6f3beebcce761e5"
HEAD = "0d51be8a53a2076bfef727bc3846a411f41c5902"


def z(*records: str) -> str:
    """Build a `git diff --name-status -z` payload.

    Call sites pass tab-joined records for readability ("M\\tpath", "R100\\told\\tnew");
    real git emits the status and every path as separate NUL-delimited fields
    (verified: b"M\\x00path\\x00..."), so tabs are converted to NULs here.
    """
    return "".join(field + "\0" for rec in records for field in rec.split("\t"))


def decide_pr(payload: str | None, event: str = "pull_request") -> clf.Decision:
    return clf.decide(event, BASE, HEAD, payload)


def skipped(decision: clf.Decision) -> set[str]:
    return {g for g in clf.GROUPS if not decision.run_all and not decision.run[g]}


def running(decision: clf.Decision) -> set[str]:
    return {g for g in clf.GROUPS if decision.run_all or decision.run[g]}


# The exact GitHub status condition that forces a step to run after an earlier failure.
ALWAYS = "${{ always() }}"


def _steps() -> list:
    workflow = yaml.load(CI_YAML.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow["jobs"]["static-checks"]["steps"]


class ScopeTests(unittest.TestCase):
    def test_docs_only_skips_every_expensive_group(self) -> None:
        decision = decide_pr(z("M\tdocs/readme-note.md", "M\tREADME.md"))
        self.assertFalse(decision.run_all)
        self.assertEqual(set(clf.GROUPS), skipped(decision))
        self.assertEqual(set(), running(decision))

    def test_clusters_change_runs_iac_and_contract_guards(self) -> None:
        decision = decide_pr(z("M\tclusters/prod/infra/hermes-mission-runtime.yaml"))
        self.assertFalse(decision.run_all)
        self.assertEqual({"iac", "static"}, running(decision))
        # clusters/ is not infra/, so the ops healthcheck self-test stays skipped
        self.assertIn("healthcheck", skipped(decision))

    def test_infra_change_runs_iac_healthcheck_and_contract_guards(self) -> None:
        decision = decide_pr(z("M\tinfra/ops/uap-healthcheck.sh"))
        self.assertEqual({"iac", "healthcheck", "static"}, running(decision))

    def test_hermes_change_runs_only_hermes(self) -> None:
        decision = decide_pr(z("M\thermes/runtime/overlay.py"))
        self.assertEqual({"hermes"}, running(decision))

    def test_tools_change_runs_tools_and_static(self) -> None:
        decision = decide_pr(z("M\ttools/swarm/flow_contract.py"))
        self.assertEqual({"tools", "static"}, running(decision))

    def test_tests_change_runs_static(self) -> None:
        decision = decide_pr(z("M\ttests/static/validate_iac.py"))
        self.assertIn("static", running(decision))

    def test_mixed_diff_runs_union_of_touched_scopes(self) -> None:
        decision = decide_pr(
            z(
                "M\tdocs/plan.md",
                "M\tclusters/prod/infra/x.yaml",
                "A\thermes/tests/test_new.py",
            )
        )
        self.assertFalse(decision.run_all)
        self.assertEqual({"iac", "hermes", "static"}, running(decision))
        self.assertEqual({"healthcheck", "tools"}, skipped(decision))

    def test_added_file_is_classified_like_modify(self) -> None:
        decision = decide_pr(z("A\tdocs/brand-new.md"))
        self.assertFalse(decision.run_all)
        self.assertEqual(set(clf.GROUPS), skipped(decision))


class FailOpenTests(unittest.TestCase):
    def test_non_pull_request_event_runs_all(self) -> None:
        decision = decide_pr(z("M\tdocs/x.md"), event="push")
        self.assertTrue(decision.run_all)
        self.assertEqual(set(clf.GROUPS), running(decision))

    def test_missing_base_sha_runs_all(self) -> None:
        decision = clf.decide("pull_request", "", HEAD, z("M\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_missing_head_sha_runs_all(self) -> None:
        decision = clf.decide("pull_request", BASE, "", z("M\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_short_sha_runs_all(self) -> None:
        decision = clf.decide("pull_request", "6dbe224", HEAD, z("M\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_non_hex_sha_runs_all(self) -> None:
        decision = clf.decide("pull_request", "z" * 40, HEAD, z("M\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_unavailable_diff_runs_all(self) -> None:
        decision = decide_pr(None)
        self.assertTrue(decision.run_all)

    def test_workflow_change_runs_all(self) -> None:
        decision = decide_pr(z("M\t.github/workflows/ci.yml"))
        self.assertTrue(decision.run_all)

    def test_dependabot_config_change_runs_all(self) -> None:
        decision = decide_pr(z("M\t.github/dependabot.yml"))
        self.assertTrue(decision.run_all)

    def test_dependency_change_runs_all(self) -> None:
        decision = decide_pr(z("M\trequirements-dev.txt"))
        self.assertTrue(decision.run_all)

    def test_repo_config_change_runs_all(self) -> None:
        for path in (".gitleaks.toml", ".sops.yaml", ".gitattributes", ".gitignore"):
            with self.subTest(path=path):
                self.assertTrue(decide_pr(z(f"M\t{path}")).run_all)

    def test_changed_classifier_itself_runs_all(self) -> None:
        decision = decide_pr(z("M\ttests/static/ci_diff_classifier.py"))
        self.assertTrue(decision.run_all)

    def test_deletion_runs_all(self) -> None:
        decision = decide_pr(z("D\tdocs/obsolete.md"))
        self.assertTrue(decision.run_all)

    def test_rename_both_sides_runs_all(self) -> None:
        # rename records carry old + new path; any rename is ambiguous -> RUN ALL
        decision = decide_pr(z("R100\tdocs/old.md\tdocs/new.md"))
        self.assertTrue(decision.run_all)

    def test_rename_into_code_scope_still_runs_all(self) -> None:
        decision = decide_pr(z("R100\tdocs/old.md\tclusters/prod/moved.yaml"))
        self.assertTrue(decision.run_all)

    def test_typechange_runs_all(self) -> None:
        decision = decide_pr(z("T\tinfra/ops/uap-healthcheck.sh"))
        self.assertTrue(decision.run_all)

    def test_path_traversal_runs_all(self) -> None:
        decision = decide_pr(z("M\tdocs/../../clusters/prod/x.yaml"))
        self.assertTrue(decision.run_all)

    def test_absolute_path_runs_all(self) -> None:
        decision = decide_pr(z("M\t/etc/passwd"))
        self.assertTrue(decision.run_all)

    def test_backslash_path_runs_all(self) -> None:
        decision = decide_pr(z("M\tdocs\\..\\clusters\\x.yaml"))
        self.assertTrue(decision.run_all)

    def test_control_char_path_runs_all(self) -> None:
        decision = decide_pr(z("M\tdocs/bad\x01name.md"))
        self.assertTrue(decision.run_all)

    def test_mixed_docs_plus_deletion_runs_all(self) -> None:
        decision = decide_pr(z("M\tdocs/ok.md", "D\tclusters/prod/gone.yaml"))
        self.assertTrue(decision.run_all)

    def test_truncated_payload_runs_all(self) -> None:
        # status with no following path -> parse error -> fail open
        decision = decide_pr("M")
        self.assertTrue(decision.run_all)

    # --- finding 1: multi-character / unknown status codes must RUN ALL ---

    def test_multi_char_status_AA_runs_all(self) -> None:
        decision = decide_pr(z("AA\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_multi_char_status_AU_runs_all(self) -> None:
        decision = decide_pr(z("AU\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_multi_char_status_M100_runs_all(self) -> None:
        decision = decide_pr(z("M100\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    def test_multi_char_status_A100_runs_all(self) -> None:
        decision = decide_pr(z("A100\tdocs/x.md"))
        self.assertTrue(decision.run_all)

    # --- finding 2: malformed / degenerate NUL payloads must RUN ALL ---

    def test_all_nul_payload_runs_all(self) -> None:
        decision = decide_pr("\0\0\0")
        self.assertTrue(decision.run_all)

    def test_single_nul_runs_all(self) -> None:
        decision = decide_pr("\0")
        self.assertTrue(decision.run_all)

    def test_status_letter_as_path_runs_all(self) -> None:
        # "M\0M\0" — path is a single status-like character; degenerate
        decision = decide_pr("M\0M\0")
        self.assertTrue(decision.run_all)

    def test_single_char_path_runs_all(self) -> None:
        decision = decide_pr(z("M\ta"))
        self.assertTrue(decision.run_all)

    def test_not_nul_terminated_runs_all(self) -> None:
        decision = decide_pr("M\0docs/x.md")
        self.assertTrue(decision.run_all)

    def test_nul_terminated_but_no_path_runs_all(self) -> None:
        decision = decide_pr("M\0")
        self.assertTrue(decision.run_all)

    def test_surplus_trailing_nul_runs_all(self) -> None:
        decision = decide_pr("M\0docs/x.md\0\0")
        self.assertTrue(decision.run_all)

    def test_empty_path_field_runs_all(self) -> None:
        decision = decide_pr("M\0\0")
        self.assertTrue(decision.run_all)

    def test_surplus_field_after_record_runs_all(self) -> None:
        decision = decide_pr("M\0docs/x.md\0extra\0")
        self.assertTrue(decision.run_all)

    def test_valid_empty_diff_is_scoped_empty(self) -> None:
        # A truly empty git diff (no changed files) is safe: skip everything.
        decision = decide_pr("")
        self.assertFalse(decision.run_all)
        self.assertEqual(set(clf.GROUPS), skipped(decision))


class SecurityGateTests(unittest.TestCase):
    def test_decision_never_models_a_security_skip(self) -> None:
        # The classifier only ever emits skip flags for GROUPS; security is absent,
        # so no decision can ever mark a security gate skippable.
        for payload in (z("M\tdocs/x.md"), z("M\tclusters/prod/x.yaml"), None):
            decision = decide_pr(payload)
            for group in clf.GROUPS:
                self.assertIn(group, decision.run)
            self.assertNotIn("security", decision.run)
            self.assertNotIn("secret_scan", decision.run)
            self.assertNotIn("gitleaks", decision.run)

    def test_workflow_security_steps_use_always(self) -> None:
        # Security gates must be ATTEMPTED even after an earlier step fails. GitHub's implicit
        # success() would otherwise skip them, so each carries the exact always() condition. A scan
        # that itself fails still fails its step (and the required job) — always() only controls
        # whether the step is attempted, not whether its failure is reported.
        steps = _steps()

        secret_scan = next(s for s in steps if str(s.get("name", "")).startswith("Secret scan"))
        self.assertEqual(ALWAYS, secret_scan.get("if"), "secret_scan must run even after an earlier failure")

        gitleaks = next(s for s in steps if "gitleaks/gitleaks-action" in str(s.get("uses", "")))
        self.assertEqual(ALWAYS, gitleaks.get("if"), "gitleaks must run even after an earlier failure")

    def test_classify_is_the_only_continue_on_error_step(self) -> None:
        # Only the classifier may degrade softly (continue-on-error) so a crash fails open to RUN ALL.
        # Every other step must surface its failure normally so a real break turns the job red.
        steps = _steps()
        soft = [s for s in steps if str(s.get("continue-on-error", "")).lower() == "true"]
        self.assertEqual(1, len(soft), "exactly one step may hide failure via continue-on-error")
        self.assertEqual("classify", soft[0].get("id"), "only the classifier may degrade softly to RUN ALL")
        self.assertIn("ci_diff_classifier.py", str(soft[0].get("run", "")))

    def test_only_security_gates_use_always(self) -> None:
        # Ordinary test/IaC groups keep fail-fast red behavior: they use implicit success() (via the
        # classifier gate), never always(), so an earlier failure still fails the job fast. always()
        # is reserved for exactly the two security gates.
        steps = _steps()
        always_steps = [s for s in steps if s.get("if") == ALWAYS]
        self.assertEqual(2, len(always_steps), "exactly the two security gates may use always()")
        kinds = {
            "secret_scan"
            if str(s.get("name", "")).startswith("Secret scan")
            else "gitleaks"
            if "gitleaks/gitleaks-action" in str(s.get("uses", ""))
            else "other"
            for s in always_steps
        }
        self.assertEqual({"secret_scan", "gitleaks"}, kinds, "always() is reserved for the security gates")

    def test_classifier_failure_implies_run_all_via_output_defaults(self) -> None:
        # A classifier crash (continue-on-error) writes nothing to $GITHUB_OUTPUT, so every gated step
        # sees an UNSET output. The fail-open condition shape `<output> != 'true'` is true for an
        # unset/empty value, so every group RUNS. Assert every classifier-gated condition has that
        # fail-open shape (never `== 'true'`, never always()) — this is what makes a crash degrade to
        # RUN ALL rather than skipping groups.
        steps = _steps()
        gated = [s for s in steps if str(s.get("if", "")).startswith("${{ steps.classify.outputs.")]
        self.assertTrue(gated, "expected classifier-gated steps")
        for step in gated:
            cond = step["if"]
            self.assertTrue(
                cond.endswith("!= 'true' }}"),
                f"{step.get('name')!r}: condition must be fail-open (!= 'true'), got {cond!r}",
            )
            self.assertNotIn("always()", cond)
            self.assertNotIn("== 'true'", cond)

    def test_load_bearing_job_name_preserved(self) -> None:
        workflow = yaml.load(CI_YAML.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(["static-checks"], list(workflow["jobs"]))

    def test_every_skippable_step_gated_on_classifier_fail_open(self) -> None:
        workflow = yaml.load(CI_YAML.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        steps = workflow["jobs"]["static-checks"]["steps"]
        gated = {
            "IaC static validation": "skip_iac",
            "Ops healthcheck parser self-test": "skip_healthcheck",
            "Hermes unit tests": "skip_hermes",
            "Static fixture tests": "skip_static",
            "Tools unit tests": "skip_tools",
            "Install kustomize": "skip_iac",
            "Kustomize build": "skip_iac",
        }
        matched: set[str] = set()
        for step in steps:
            name = str(step.get("name", ""))
            for prefix, output in gated.items():
                if name.startswith(prefix):
                    matched.add(prefix)
                    self.assertEqual(
                        f"${{{{ steps.classify.outputs.{output} != 'true' }}}}",
                        step.get("if"),
                        f"{name} must fail open on {output}",
                    )
        self.assertEqual(set(gated), matched, "every gated step must be present in the workflow")
        # classify step exists and feeds the outputs
        classify = next(s for s in steps if s.get("id") == "classify")
        self.assertIn("ci_diff_classifier.py", str(classify.get("run", "")))

    def test_no_remote_action_added_by_fast_path(self) -> None:
        # The fast path must not introduce any new/unpinned action dependency.
        workflow_text = CI_YAML.read_text(encoding="utf-8")
        uses = [
            line.split("uses:", 1)[1].strip().split("#", 1)[0].strip().strip("'\"")
            for line in workflow_text.splitlines()
            if "uses:" in line
        ]
        self.assertEqual(
            [
                "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                "imranismail/setup-kustomize@2ba527d4d055ab63514ba50a99456fc35684947f",
                "gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7",
            ],
            uses,
        )


class ParserTests(unittest.TestCase):
    def test_parse_modify_and_add(self) -> None:
        entries = clf.parse_name_status(z("M\ta.md", "A\tb.md"))
        self.assertEqual([("M", "a.md"), ("A", "b.md")], [(e.status, e.path) for e in entries])

    def test_parse_rename_consumes_two_paths(self) -> None:
        entries = clf.parse_name_status(z("R100\told.md", "new.md", "M\tc.md"))
        self.assertEqual("R100", entries[0].status)
        self.assertEqual("new.md", entries[0].path)
        self.assertEqual("old.md", entries[0].old)
        self.assertEqual(("M", "c.md"), (entries[1].status, entries[1].path))

    def test_valid_sha(self) -> None:
        self.assertTrue(clf.valid_sha(BASE))
        self.assertFalse(clf.valid_sha(""))
        self.assertFalse(clf.valid_sha("abc"))
        self.assertFalse(clf.valid_sha("Z" * 40))


if __name__ == "__main__":
    unittest.main()
