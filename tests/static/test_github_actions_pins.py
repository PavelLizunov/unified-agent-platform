#!/usr/bin/env python3
"""Require immutable refs for every remote action used by CI workflows."""

from __future__ import annotations

import pathlib
import re
import tomllib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
USES = re.compile(r"^\s*uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)

# The hermes v0.19 readiness fixture allowlist, exactly as it must appear in
# .gitleaks.toml: scoped to the one fixture path, permitting only its known
# SHA-256-bearing lines (the "sha256" field + overlay_files' 7 fingerprinted
# upstream paths). Mirrored here so the structural test below can assert the
# generic-api-key rule carries precisely the two narrow allowlists, no more.
HERMES_V019_ALLOWLIST = {
    "description": "Hermes v0.19 readiness fixture stores one-way upstream source SHA-256 fingerprints, not credentials",
    "condition": "AND",
    "regexTarget": "line",
    "paths": [r"^tests/fixtures/hermes-v019-readiness\.json$"],
    "regexes": [
        r'^\s*"sha256"\s*:\s*"[0-9a-f]{64}"\s*,?\s*$',
        r'^\s*"(gateway/(platforms/api_server|run)\.py|hermes_cli/(commands|kanban_db|kanban|main)\.py|plugins/platforms/telegram/adapter\.py)"\s*:\s*"[0-9a-f]{64}"\s*,?\s*$',
    ],
}


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
        workflow_text = (ROOT / ".github" / "workflows" / "attest-completion-evidence.yml").read_text(
            encoding="utf-8"
        )
        workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
        self.assertEqual(
            {
                "push": {
                    "branches": ["master"],
                    "paths": [
                        "docs/evidence/completion/*.json",
                        "docs/evidence/onboarding/*.json",
                    ],
                }
            },
            workflow["on"],
        )
        self.assertEqual({}, workflow["permissions"])
        self.assertEqual({"attest"}, set(workflow["jobs"]))
        self.assertEqual(
            {"contents": "read", "id-token": "write", "attestations": "write"},
            workflow["jobs"]["attest"]["permissions"],
        )
        self.assertNotIn("secrets.", workflow_text)

    def test_completion_evidence_gitleaks_allowlist_is_narrow(self) -> None:
        config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
        allowlist = {
            "description": "Completion evidence stores a one-way source identity digest, not a credential",
            "condition": "AND",
            "regexTarget": "line",
            "paths": [r"^docs/evidence/completion/[^/]+\.json$"],
            "regexes": [r'^\s*"source_key_sha256"\s*:\s*"[0-9a-f]{64}"\s*,?\s*$'],
        }
        # The generic-api-key rule must carry EXACTLY these two narrow allowlists
        # (completion evidence + hermes v0.19 readiness fixture) and nothing else --
        # this is the guard against a broad/unaccounted allowlist sneaking in.
        self.assertEqual(
            [{"id": "generic-api-key", "allowlists": [allowlist, HERMES_V019_ALLOWLIST]}],
            config["rules"],
        )

        digest = "0123456789abcdef" * 4
        line = re.compile(allowlist["regexes"][0])
        path = re.compile(allowlist["paths"][0])
        self.assertIsNotNone(line.search(f'  "source_key_sha256": "{digest}",'))
        self.assertIsNone(
            line.search(f'{{"source_key_sha256":"{digest}","api_key":"{digest}"}}')
        )
        self.assertIsNotNone(path.search("docs/evidence/completion/evidence.json"))
        self.assertIsNone(path.search("docs/evidence/completion/nested/evidence.json"))

    def test_hermes_v019_fixture_gitleaks_allowlist_is_narrow(self) -> None:
        allowlist = HERMES_V019_ALLOWLIST
        digest = "0123456789abcdef" * 4
        sha_field = re.compile(allowlist["regexes"][0])
        path_key = re.compile(allowlist["regexes"][1])
        path = re.compile(allowlist["paths"][0])
        # POSITIVE: the fixture's known SHA-256-bearing lines ARE allowlisted.
        self.assertIsNotNone(sha_field.search(f'          "sha256": "{digest}",'))
        self.assertIsNotNone(path_key.search(f'    "gateway/run.py": "{digest}",'))
        self.assertIsNotNone(path_key.search(f'    "gateway/platforms/api_server.py": "{digest}",'))
        self.assertIsNotNone(path_key.search(f'    "hermes_cli/kanban_db.py": "{digest}",'))
        self.assertIsNotNone(
            path_key.search(f'    "plugins/platforms/telegram/adapter.py": "{digest}",')
        )
        # NEGATIVE: an unrelated secret-like 64-hex is NOT allowlisted (still flagged).
        for bad in (
            f'  "openai_api_key": "{digest}",',
            f'  "telegram_bot_token": "{digest}",',
            f'  "api_secret": "{digest}",',
            f'  "source_key_sha256": "{digest}",',
        ):
            self.assertIsNone(sha_field.search(bad), bad)
            self.assertIsNone(path_key.search(bad), bad)
        # Path scope is exactly the readiness fixture, not sibling fixtures.
        self.assertIsNotNone(path.search("tests/fixtures/hermes-v019-readiness.json"))
        self.assertIsNone(path.search("tests/fixtures/some-other-fixture.json"))


if __name__ == "__main__":
    unittest.main()
