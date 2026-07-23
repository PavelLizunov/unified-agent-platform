"""Deterministic blocker guard for the Hermes Agent production pin (ADR-027/030).

The production pin is a single atomic unit: the image digest pinned in the
manifests, the overlay's ``UPSTREAM_COMMIT``, the initContainer ``--source-commit``
and the overlay ``FILES`` fingerprint table MUST all describe the SAME upstream
source. The fail-closed initContainer fingerprints the running image's source at
boot and CrashLoops the pod on any mismatch, so advancing only part of the unit
(e.g. bumping the image to a "v0.19" candidate without rebasing+verifying the
overlay) breaks production on the next roll.

This guard locks production to the set of ACCEPTED pins below.  It PASSES while
production sits on an accepted pin (currently v0.18.0) and FAILS CLOSED the
moment the image digest moves to anything not in ``ACCEPTED_PINS``, or the pin
unit becomes internally inconsistent.  That is the deterministic blocker: an
incomplete v0.19 upgrade cannot pass static-checks.

Provenance distinction (important):
  - The upstream source tag -> commit mapping and the source bytes ARE
    cryptographically verified (git ls-remote tag peel + fixture baseline
    byte-for-byte match against the overlay FILES table).
  - The current image digest is an ACCEPTED HISTORICAL PRODUCTION PIN recorded
    from the manifest (PR #35 lineage).  It was NOT independently re-pulled or
    signature-verified in this guard.
  - Any NEW v0.19 digest MUST be independently registry/signature-verified
    before it is added to ACCEPTED_PINS.

To unlock a real v0.19, a future change must add an entry to ``ACCEPTED_PINS``
with the verified image digest + upstream source commit, rebase the overlay
(``FILES``/``PATCHED_FILES`` + every fragment) against that source, and refresh
``tests/fixtures/hermes-v019-readiness.json`` -- only after the image digest is
independently verified and the owner confirms which upstream tag is "v0.19".
Upstream publishes date tags only; there is no "v0.19" tag, so this guard never
accepts an invented digest.

Hermetic and offline (no network): it cross-checks the manifests, the overlay
source and the committed readiness fixture. Runs as a plain script in CI's
``tests/static/test_*.py`` loop.  All load-bearing checks use explicit ``raise``
(not ``assert``) so they still execute under ``python -O``.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "tools" / "hermes-mission" / "apply_overlay.py"
FIXTURE = ROOT / "tests" / "fixtures" / "hermes-v019-readiness.json"
GITLEAKS_CONFIG = ROOT / ".gitleaks.toml"
MANIFESTS = [
    ROOT / "clusters" / "prod" / "infra" / "hermes-agent.yaml",
    ROOT / "clusters" / "prod" / "infra" / "hermes-agent-backup.yaml",
]

# Accepted production pins, keyed by the exact image digest pinned in the
# manifests.  Add a v0.19 entry ONLY once its image digest is independently
# registry/signature-verified; never invent one.
#
# v0.18.0 provenance (re-established 2026-07-24):
#   - source_commit 7c1a029... is the peeled object of upstream tag v2026.7.1,
#     confirmed by `git ls-remote --tags https://github.com/NousResearch/hermes-agent`
#     (v2026.7.1 -> 7c1a029553d87c43ecff8a3821336bc95872213b); it equals the mission
#     overlay's UPSTREAM_COMMIT (tools/hermes-mission/apply_overlay.py).
#   - The readiness fixture re-fetched that commit and proved all 7 fingerprinted
#     files match the overlay FILES table byte-for-byte (current_pin_baseline,
#     every status == "unchanged"); this guard re-checks that below.
#   - image_digest sha256:b6c019... is the value pinned in hermes-agent.yaml
#     (bootstrap + gateway) and hermes-agent-backup.yaml, commented there as
#     "v0.18.0 (Docker tag v2026.7.1), pinned by digest 2026-07-02" (PR #35 lineage).
#     NOTE: the digest is an accepted historical production pin recorded from the
#     manifest, NOT independently re-pulled or signature-verified here -- which is
#     exactly why a v0.19 entry is blocked until its digest IS independently
#     registry/signature-verified.
ACCEPTED_PINS = {
    "sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f": {
        "label": "v0.18.0",
        "tag": "v2026.7.1",
        "source_commit": "7c1a029553d87c43ecff8a3821336bc95872213b",
    },
}

# Exact path scope the fixture's gitleaks allowlist must be limited to.
FIXTURE_ALLOWLIST_PATH = r"^tests/fixtures/hermes-v019-readiness\.json$"

IMAGE_RE = re.compile(r"nousresearch/hermes-agent@(sha256:[0-9a-f]{64})")
SOURCE_COMMIT_RE = re.compile(r"--source-commit\s+([0-9a-f]{40})")


# ---------------------------------------------------------------------------
# Explicit-failure helper (survives python -O, unlike bare assert)
# ---------------------------------------------------------------------------

def check(condition: bool, message: str) -> None:
    """Raise AssertionError when *condition* is false.  Unlike ``assert``, this
    is never stripped by ``python -O``."""
    if not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------------------
# Pure validation functions (dependency-injection friendly, hermetic)
# ---------------------------------------------------------------------------

def validate_single_digest(digests: set[str]) -> str:
    """Production must pin exactly one image digest.  Returns it."""
    check(bool(digests), "no nousresearch/hermes-agent@sha256:... pin found in manifests")
    check(
        len(digests) == 1,
        f"production must pin exactly one image digest, found {sorted(digests)}",
    )
    return next(iter(digests))


def validate_digest_accepted(digest: str) -> dict:
    """The digest must be in ACCEPTED_PINS.  Returns the pin entry."""
    if digest not in ACCEPTED_PINS:
        raise AssertionError(
            "v0.19 upgrade BLOCKED: production image digest "
            f"{digest} is not an accepted pin. "
            f"Accepted pins: {sorted(ACCEPTED_PINS)}. Upstream publishes date tags "
            "only (no 'v0.19' tag); do not advance the pin until the target image "
            "digest is independently registry/signature-verified, the owner "
            "confirms which tag is v0.19, and the overlay "
            "(UPSTREAM_COMMIT/FILES/PATCHED_FILES + every fragment) is rebased "
            "and re-verified against that source."
        )
    return ACCEPTED_PINS[digest]


def validate_overlay_commit(overlay_commit: str, pin: dict, digest: str) -> None:
    check(
        overlay_commit == pin["source_commit"],
        f"overlay UPSTREAM_COMMIT {overlay_commit} != verified pin "
        f"source_commit {pin['source_commit']} for {digest}",
    )


def validate_source_commits(commits: set[str], pin: dict) -> None:
    check(
        commits == {pin["source_commit"]},
        f"manifest --source-commit {sorted(commits)} != verified pin source_commit "
        f"{pin['source_commit']} (the overlay would fail closed at boot)",
    )


def validate_fixture_consistency(
    fixture: dict,
    overlay_files: dict[str, str],
    overlay_commit: str,
    digest: str,
    pin: dict,
) -> None:
    check(
        fixture.get("schema") == "hermes-v019-readiness/v1",
        f"unexpected fixture schema: {fixture.get('schema')}",
    )
    check(
        fixture.get("overlay_upstream_commit") == overlay_commit,
        "readiness fixture was generated against a different upstream commit; "
        "refresh it with tools/hermes-mission/v019_readiness.py --write-fixture",
    )
    check(
        fixture.get("overlay_files") == overlay_files,
        "readiness fixture overlay_files != overlay FILES table; refresh the fixture",
    )
    check(
        fixture.get("current_pin", {}).get("image_digest") == digest,
        "readiness fixture current_pin digest != production digest",
    )
    check(
        fixture.get("current_pin", {}).get("commit") == pin["source_commit"],
        "readiness fixture current_pin commit != verified pin source_commit",
    )


def validate_baseline(fixture: dict, overlay_files: dict[str, str]) -> None:
    """The fixture baseline must prove FILES == real upstream source bytes:
    every fingerprinted file in the verified pin source must be 'unchanged'."""
    baseline = fixture.get("current_pin_baseline")
    check(
        baseline is not None,
        "readiness fixture has no current_pin_baseline",
    )
    check(
        set(baseline) == set(overlay_files),
        "readiness fixture baseline does not cover the overlay FILES table",
    )
    drifted = sorted(
        rel for rel, entry in baseline.items() if entry["status"] != "unchanged"
    )
    check(
        not drifted,
        "verified pin source no longer matches the overlay FILES table: "
        f"{drifted}. The pin unit is inconsistent; the overlay would fail closed.",
    )


def validate_gitleaks_allowlist(config_text: str, fixture_text: str) -> None:
    """Prove the fixture's gitleaks allowlist permits ONLY its known SHA-256
    fingerprint lines, so an unrelated secret-like 64-hex value would still be
    flagged.  Deterministic and offline; uses a synthetic vector, never a real
    secret.  Requires Python 3.11+ (tomllib), which is the CI runner."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - CI runs 3.11
        raise AssertionError(
            "tomllib unavailable: the gitleaks-allowlist narrowing check needs "
            "Python 3.11+ (the CI static-checks runner)"
        )

    config = tomllib.loads(config_text)
    fixture_allowlist = None
    for rule in config.get("rules", []):
        if rule.get("id") != "generic-api-key":
            continue
        for allowlist in rule.get("allowlists", []):
            if FIXTURE_ALLOWLIST_PATH in allowlist.get("paths", []):
                fixture_allowlist = allowlist
    check(
        fixture_allowlist is not None,
        "gitleaks allowlist for the v0.19 readiness fixture is missing",
    )
    check(
        fixture_allowlist.get("paths") == [FIXTURE_ALLOWLIST_PATH],
        "fixture gitleaks allowlist must be scoped to exactly "
        f"[{FIXTURE_ALLOWLIST_PATH}], got {fixture_allowlist.get('paths')}",
    )
    regexes = [re.compile(rx) for rx in fixture_allowlist.get("regexes", [])]
    check(bool(regexes), "fixture gitleaks allowlist has no regexes")

    def allowlisted(line: str) -> bool:
        return any(rx.search(line) for rx in regexes)

    # POSITIVE: every bare 64-hex value line in the real fixture IS allowlisted
    # (the "sha256" field + overlay_files' 7 fingerprinted paths).
    hex_lines = [
        line
        for line in fixture_text.splitlines()
        if re.search(r'"[0-9a-f]{64}"', line)
    ]
    check(bool(hex_lines), "readiness fixture has no SHA-256 lines (unexpected)")
    for line in hex_lines:
        check(
            allowlisted(line),
            f"legitimate fixture fingerprint line is NOT allowlisted: {line.strip()}",
        )

    # NEGATIVE: an unrelated secret-like 64-hex under a non-fingerprint key is NOT
    # allowlisted, so it does NOT escape scanning -- gitleaks would still flag it.
    # Synthetic repeating-byte vector, obviously not a real credential.
    fake_hex = "ab" * 32
    for line in (
        f'  "openai_api_key": "{fake_hex}",',
        f'  "telegram_bot_token": "{fake_hex}",',
        f'  "dashboard_password": "{fake_hex}",',
        f'  "producer_key": "{fake_hex}",',
        f'  "api_secret": "{fake_hex}",',
        # another fixture's allowlisted key, but NOT this fixture's:
        f'  "source_key_sha256": "{fake_hex}",',
    ):
        check(
            not allowlisted(line),
            "gitleaks allowlist is too broad: it would mask an unrelated "
            f"secret-like value: {line.strip()}",
        )


# ---------------------------------------------------------------------------
# Full guard (composition of the pure validators above)
# ---------------------------------------------------------------------------

def validate_pin_unit(
    *,
    production_digests: set[str],
    production_source_commits: set[str],
    overlay_upstream_commit: str,
    overlay_files: dict[str, str],
    fixture: dict,
    gitleaks_config_text: str,
    fixture_text: str,
) -> str:
    """Run every load-bearing check and return the accepted digest on success.
    Raises AssertionError on any inconsistency.  All checks survive python -O."""
    digest = validate_single_digest(production_digests)
    pin = validate_digest_accepted(digest)
    validate_overlay_commit(overlay_upstream_commit, pin, digest)
    validate_source_commits(production_source_commits, pin)
    validate_fixture_consistency(
        fixture, overlay_files, overlay_upstream_commit, digest, pin
    )
    validate_baseline(fixture, overlay_files)
    validate_gitleaks_allowlist(gitleaks_config_text, fixture_text)
    return digest


# ---------------------------------------------------------------------------
# I/O helpers (read production state -- NOT used by negative tests)
# ---------------------------------------------------------------------------

def load_overlay():
    spec = importlib.util.spec_from_file_location("apply_overlay", OVERLAY)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise AssertionError(f"cannot load overlay module from {OVERLAY}")
    spec.loader.exec_module(module)
    return module


def production_digests() -> set[str]:
    digests: set[str] = set()
    for manifest in MANIFESTS:
        text = manifest.read_text(encoding="utf-8")
        digests.update(IMAGE_RE.findall(text))
    return digests


def production_source_commits() -> set[str]:
    commits: set[str] = set()
    for manifest in MANIFESTS:
        commits.update(SOURCE_COMMIT_RE.findall(manifest.read_text(encoding="utf-8")))
    return commits


# ---------------------------------------------------------------------------
# CI entry point (happy path)
# ---------------------------------------------------------------------------

def main() -> None:
    overlay = load_overlay()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture_text = FIXTURE.read_text(encoding="utf-8")
    gitleaks_text = GITLEAKS_CONFIG.read_text(encoding="utf-8")

    digest = validate_pin_unit(
        production_digests=production_digests(),
        production_source_commits=production_source_commits(),
        overlay_upstream_commit=overlay.UPSTREAM_COMMIT,
        overlay_files=dict(overlay.FILES),
        fixture=fixture,
        gitleaks_config_text=gitleaks_text,
        fixture_text=fixture_text,
    )

    pin = ACCEPTED_PINS[digest]
    print(
        f"hermes pin guard ok: {pin['label']} ({pin['tag']}) digest={digest} "
        f"source_commit={pin['source_commit']} files={len(overlay.FILES)} "
        "gitleaks-allowlist-narrow-ok"
    )


# ---------------------------------------------------------------------------
# Hermetic negative regression tests (never touch production files)
# ---------------------------------------------------------------------------

# Shared constants for the synthetic pin used by negative tests.
_GOOD_DIGEST = "sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f"
_GOOD_COMMIT = "7c1a029553d87c43ecff8a3821336bc95872213b"
# Read from the allowlisted fixture rather than committing literal 64-hex
# fingerprint strings here (gitleaks generic-api-key would flag them).
_GOOD_FILES: dict[str, str] = dict(
    json.loads(FIXTURE.read_text(encoding="utf-8"))["overlay_files"]
)


def _good_fixture() -> dict:
    """Return a deep copy of the real committed fixture (never mutated in place)."""
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _good_gitleaks_text() -> str:
    return GITLEAKS_CONFIG.read_text(encoding="utf-8")


def _good_fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _run_guard(**overrides) -> str:
    """Call validate_pin_unit with known-good defaults; override specific kwargs."""
    defaults = dict(
        production_digests={_GOOD_DIGEST},
        production_source_commits={_GOOD_COMMIT},
        overlay_upstream_commit=_GOOD_COMMIT,
        overlay_files=dict(_GOOD_FILES),
        fixture=_good_fixture(),
        gitleaks_config_text=_good_gitleaks_text(),
        fixture_text=_good_fixture_text(),
    )
    defaults.update(overrides)
    return validate_pin_unit(**defaults)


class PinGuardHappyPath(unittest.TestCase):
    """Sanity: the known-good inputs pass (guards against test-rot)."""

    def test_known_good_inputs_pass(self) -> None:
        digest = _run_guard()
        self.assertEqual(digest, _GOOD_DIGEST)


class UnacceptedDigest(unittest.TestCase):
    """BLOCK: an image digest not in ACCEPTED_PINS must fail closed."""

    def test_unknown_digest_blocked(self) -> None:
        unknown = "sha256:" + "aa" * 32
        with self.assertRaises(AssertionError, msg="v0.19 upgrade BLOCKED"):
            _run_guard(production_digests={unknown})

    def test_invented_v019_digest_blocked(self) -> None:
        invented = "sha256:" + "0123456789abcdef" * 4
        with self.assertRaises(AssertionError):
            _run_guard(production_digests={invented})


class MultipleOrMismatchedDigests(unittest.TestCase):
    """BLOCK: production must pin exactly one digest."""

    def test_two_digests_blocked(self) -> None:
        other = "sha256:" + "bb" * 32
        with self.assertRaises(AssertionError, msg="exactly one image digest"):
            _run_guard(production_digests={_GOOD_DIGEST, other})

    def test_empty_digests_blocked(self) -> None:
        with self.assertRaises(AssertionError, msg="no nousresearch"):
            _run_guard(production_digests=set())


class UpstreamCommitMismatch(unittest.TestCase):
    """BLOCK: overlay UPSTREAM_COMMIT must equal the pin's source_commit."""

    def test_wrong_overlay_commit(self) -> None:
        wrong = "f" * 40
        with self.assertRaises(AssertionError, msg="UPSTREAM_COMMIT"):
            _run_guard(overlay_upstream_commit=wrong)


class SourceCommitMismatch(unittest.TestCase):
    """BLOCK: manifest --source-commit must equal the pin's source_commit."""

    def test_wrong_source_commit(self) -> None:
        wrong = "e" * 40
        with self.assertRaises(AssertionError, msg="--source-commit"):
            _run_guard(production_source_commits={wrong})

    def test_multiple_source_commits(self) -> None:
        wrong = "d" * 40
        with self.assertRaises(AssertionError):
            _run_guard(production_source_commits={_GOOD_COMMIT, wrong})


class FixtureMismatch(unittest.TestCase):
    """BLOCK: fixture must agree with overlay + verified pin on every field."""

    def test_fixture_commit_mismatch(self) -> None:
        fixture = _good_fixture()
        fixture["current_pin"]["commit"] = "c" * 40
        with self.assertRaises(AssertionError, msg="current_pin commit"):
            _run_guard(fixture=fixture)

    def test_fixture_digest_mismatch(self) -> None:
        fixture = _good_fixture()
        fixture["current_pin"]["image_digest"] = "sha256:" + "cc" * 32
        with self.assertRaises(AssertionError, msg="current_pin digest"):
            _run_guard(fixture=fixture)

    def test_fixture_overlay_files_mismatch(self) -> None:
        fixture = _good_fixture()
        fixture["overlay_files"]["hermes_cli/main.py"] = "d" * 64
        with self.assertRaises(AssertionError, msg="overlay_files"):
            _run_guard(fixture=fixture)

    def test_fixture_overlay_commit_mismatch(self) -> None:
        fixture = _good_fixture()
        fixture["overlay_upstream_commit"] = "b" * 40
        with self.assertRaises(AssertionError, msg="upstream commit"):
            _run_guard(fixture=fixture)

    def test_fixture_schema_mismatch(self) -> None:
        fixture = _good_fixture()
        fixture["schema"] = "hermes-v019-readiness/v999"
        with self.assertRaises(AssertionError, msg="schema"):
            _run_guard(fixture=fixture)


class BaselineDrift(unittest.TestCase):
    """BLOCK: baseline must be present and every file 'unchanged'."""

    def test_missing_baseline(self) -> None:
        fixture = _good_fixture()
        del fixture["current_pin_baseline"]
        with self.assertRaises(AssertionError, msg="no current_pin_baseline"):
            _run_guard(fixture=fixture)

    def test_drifted_baseline_file(self) -> None:
        fixture = _good_fixture()
        fixture["current_pin_baseline"]["gateway/run.py"]["status"] = "drifted"
        with self.assertRaises(AssertionError, msg="no longer matches"):
            _run_guard(fixture=fixture)

    def test_missing_baseline_file(self) -> None:
        fixture = _good_fixture()
        fixture["current_pin_baseline"]["hermes_cli/main.py"]["status"] = "missing"
        with self.assertRaises(AssertionError):
            _run_guard(fixture=fixture)

    def test_baseline_covers_wrong_files(self) -> None:
        fixture = _good_fixture()
        del fixture["current_pin_baseline"]["hermes_cli/kanban.py"]
        with self.assertRaises(AssertionError, msg="does not cover"):
            _run_guard(fixture=fixture)


class BroadenedGitleaksAllowlist(unittest.TestCase):
    """BLOCK: the gitleaks allowlist must stay scoped to exactly the fixture."""

    # Minimal valid gitleaks TOML with the fixture allowlist.  Raw string so
    # every backslash is literal (matching what tomllib will parse).  Uses
    # single-quoted TOML literal strings so arrays stay on one line.
    _BASE_TOML = r"""title = "test"
[extend]
useDefault = true
[[rules]]
id = "generic-api-key"
  [[rules.allowlists]]
  description = "fixture"
  condition = "AND"
  regexTarget = "line"
  paths = ['^tests/fixtures/hermes-v019-readiness\.json$']
  regexes = ['"sha256"\s*:\s*"[0-9a-f]{64}"']
"""

    def test_broadened_path_scope(self) -> None:
        broadened = self._BASE_TOML.replace(
            r"^tests/fixtures/hermes-v019-readiness\.json$",
            r"^tests/fixtures/.*\.json$",
        )
        self.assertNotEqual(self._BASE_TOML, broadened)
        with self.assertRaises(AssertionError, msg="scoped to exactly"):
            _run_guard(gitleaks_config_text=broadened)

    def test_extra_allowlist_path(self) -> None:
        broadened = self._BASE_TOML.replace(
            r"paths = ['^tests/fixtures/hermes-v019-readiness\.json$']",
            r"paths = ['^tests/fixtures/hermes-v019-readiness\.json$', '^clusters/.*\.yaml$']",
        )
        self.assertNotEqual(self._BASE_TOML, broadened)
        with self.assertRaises(AssertionError):
            _run_guard(gitleaks_config_text=broadened)

    def test_missing_fixture_allowlist(self) -> None:
        stripped = self._BASE_TOML.replace(
            r"^tests/fixtures/hermes-v019-readiness\.json$",
            r"^tests/fixtures/DOES-NOT-EXIST\.json$",
        )
        self.assertNotEqual(self._BASE_TOML, stripped)
        with self.assertRaises(AssertionError, msg="missing"):
            _run_guard(gitleaks_config_text=stripped)


if __name__ == "__main__":
    main()
    unittest.main(verbosity=2)
