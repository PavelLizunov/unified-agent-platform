#!/usr/bin/env python3
"""Require immutable refs for every remote action used by CI workflows."""

from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
USES = re.compile(r"^\s*uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)


class GitHubActionsPinsTests(unittest.TestCase):
    def test_remote_actions_use_exact_commit_shas(self) -> None:
        remote_refs: list[tuple[pathlib.Path, str]] = []
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            for target in USES.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("./", "docker://")):
                    continue
                remote_refs.append((path, target))
                _action, separator, revision = target.rpartition("@")
                self.assertEqual(separator, "@", f"missing action revision in {path}: {target}")
                self.assertRegex(revision, COMMIT, f"action is not SHA-pinned in {path}: {target}")
                self.assertEqual(len(revision), 40, f"action ref is not an exact commit in {path}: {target}")
        self.assertTrue(remote_refs, "no remote GitHub Actions refs were inspected")

    def test_completion_attestation_has_only_approved_write_permissions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "attest-completion-evidence.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissions: {}", workflow)
        self.assertIn(
            "    permissions:\n"
            "      contents: read\n"
            "      id-token: write\n"
            "      attestations: write\n",
            workflow,
        )
        self.assertEqual(1, workflow.count("id-token: write"))
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("packages: write", workflow)


if __name__ == "__main__":
    unittest.main()
