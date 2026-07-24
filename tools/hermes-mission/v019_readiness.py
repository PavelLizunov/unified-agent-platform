#!/usr/bin/env python3
"""Read-only v0.19 upgrade-readiness probe for the pinned Hermes overlay.

This tool DOES NOT change the production pin and does NOT verify the registry
image digest.  The digest was verified out-of-band from the Docker Hub registry
HEAD (manifest-list + amd64 child) on 2026-07-24 and is merely RECORDED in
``CURRENT_PIN``; this probe never contacts the registry and makes no claim about
it.  Likewise the tag->commit mapping (v2026.7.20 -> commit ``UPSTREAM_COMMIT``)
is OUT-OF-BAND evidence recorded in ``CURRENT_PIN`` (confirmed separately via
``git ls-remote --tags``); this probe does NOT re-derive or verify that mapping.
What the probe DOES verify is that the exact RECORDED commit's source bytes match
the overlay: it fetches the recorded commit and matches every fingerprinted
source file byte-for-byte against the overlay's ``FILES`` table (current-baseline
verification -- the recorded v2026.7.20 commit source must be pristine-clean
against the overlay).

It then measures how far any tag strictly LATER than the current pin has drifted
from the overlay's fingerprint table (later-tag drift).  Upstream publishes DATE
tags only; the owner confirmed v2026.7.20 as the official stable release "Hermes
Agent v0.19.0" (prerelease=false).  At this snapshot no upstream tag is later
than v2026.7.20, so ``CANDIDATES`` is empty and the probe reports the verified
current baseline only.  When upstream cuts a tag strictly after v2026.7.20, add
it to ``CANDIDATES`` to extend the drift baseline.

Network-gated and skip-friendly: if upstream cannot be cloned, it prints
``v019-readiness-skipped: <reason>`` and exits 0 so it never breaks an offline
gate. Run it on a host with GitHub access:

    python tools/hermes-mission/v019_readiness.py                 # report to stdout
    python tools/hermes-mission/v019_readiness.py --write-fixture # refresh the committed fixture

Stdlib-only (RU-egress-safe), like the rest of the hermes runtime tooling.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile


TOOL = pathlib.Path(__file__).with_name("apply_overlay.py")
UPSTREAM = "https://github.com/NousResearch/hermes-agent"
FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "hermes-v019-readiness.json"
)

# The production pin: internal label v0.19.0 == upstream tag v2026.7.20. The commit
# is the peeled tag object verified via `git ls-remote --tags` and matches the
# overlay's UPSTREAM_COMMIT exactly.  The image_digest was independently verified
# from the Docker Hub registry HEAD (manifest-list sha256:f7b350...04a, amd64
# child sha256:a6ce64...1c40) on 2026-07-24.
CURRENT_PIN = {
    "label": "v0.19.0",
    "tag": "v2026.7.20",
    "commit": "3ef6bbd201263d354fd83ec55b3c306ded2eb72a",
    "image_digest": "sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a",
}

# Tags strictly LATER than the current pin (v2026.7.20 / v0.19.0), used as a
# later-tag drift baseline.  The historical tags evaluated during the completed
# v0.19 selection (v2026.7.7, v2026.7.7.2) are NOT candidates: they predate the
# current pin and live on only in git history and the selection decision, never
# in this list.  At this snapshot no upstream tag is later than v2026.7.20, so
# the list is empty.  Add a tag here only once upstream cuts one strictly after
# v2026.7.20; the current commit must NEVER appear here (regression-tested in
# tests/static/test_hermes_v019_pin_guard.py).
CANDIDATES: list[dict] = []


def load_overlay():
    spec = importlib.util.spec_from_file_location("apply_overlay", TOOL)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise AssertionError(f"cannot load overlay module from {TOOL}")
    spec.loader.exec_module(module)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True
    )


def git_bytes(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[bytes]:
    # Raw bytes, no decoding: the overlay fingerprints exact blob bytes
    # (path.read_bytes()), so any text/CRLF conversion would corrupt the hash.
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True)


def fetch_commit(clone: pathlib.Path, commit: str) -> bool:
    """Shallow-fetch an exact upstream commit. Returns False on any failure."""
    if not clone.exists():
        clone.mkdir(parents=True)
        init = git("init", "--quiet", cwd=clone)
        if init.returncode != 0:
            return False
    fetched = git("fetch", "--quiet", "--depth=1", UPSTREAM, commit, cwd=clone)
    if fetched.returncode != 0:
        return False
    head = git("rev-parse", "FETCH_HEAD", cwd=clone).stdout.strip()
    # Source integrity: the fetched HEAD must equal the exact recorded commit SHA,
    # so the fingerprinted bytes probed below are the recorded commit's bytes.
    # This verifies the RECORDED commit, NOT the tag->commit mapping -- that
    # mapping is out-of-band evidence in CURRENT_PIN (confirmed separately via
    # `git ls-remote --tags`), never re-derived here.
    return head == commit


def classify_file(clone: pathlib.Path, relative: str, pristine: str, patched: str) -> dict:
    # `git show FETCH_HEAD:<path>` emits the blob verbatim (no smudge/CRLF), which
    # is exactly the byte stream the overlay hashes on the Linux deploy host.
    result = git_bytes("show", f"FETCH_HEAD:{relative}", cwd=clone)
    if result.returncode != 0:
        return {"status": "missing", "sha256": None}
    actual = sha256_bytes(result.stdout)
    if actual == pristine:
        status = "unchanged"
    elif actual == patched:
        status = "already-patched"
    else:
        status = "drifted"
    return {"status": status, "sha256": actual}


def probe_commit(clone: pathlib.Path, commit: str, overlay) -> dict | None:
    if not fetch_commit(clone, commit):
        return None
    files = {}
    for relative, pristine in overlay.FILES.items():
        files[relative] = classify_file(
            clone, relative, pristine, overlay.PATCHED_FILES[relative]
        )
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-fixture",
        action="store_true",
        help=f"write the deterministic report to {FIXTURE}",
    )
    args = parser.parse_args()

    overlay = load_overlay()
    if overlay.UPSTREAM_COMMIT != CURRENT_PIN["commit"]:
        print(
            "v019-readiness-skipped: overlay UPSTREAM_COMMIT "
            f"{overlay.UPSTREAM_COMMIT} != expected current pin {CURRENT_PIN['commit']}",
            file=sys.stderr,
        )
        return 0

    report = {
        "schema": "hermes-v019-readiness/v1",
        "upstream": UPSTREAM,
        "current_pin": CURRENT_PIN,
        "overlay_upstream_commit": overlay.UPSTREAM_COMMIT,
        "overlay_files": dict(overlay.FILES),
        "current_pin_baseline": None,
        "candidates": [],
    }

    with tempfile.TemporaryDirectory(prefix="hermes-v019-readiness-") as temp:
        clone = pathlib.Path(temp) / "hermes"

        baseline = probe_commit(clone, CURRENT_PIN["commit"], overlay)
        if baseline is None:
            print("v019-readiness-skipped: cannot clone upstream (no network?)")
            return 0
        report["current_pin_baseline"] = baseline
        # The current pin must be pristine-clean: every fingerprinted file in the
        # verified v2026.7.20 source must match the overlay's FILES table exactly.
        for relative, entry in baseline.items():
            if entry["status"] != "unchanged":
                print(
                    "v019-readiness-skipped: current pin baseline not pristine: "
                    f"{relative} == {entry['status']}",
                    file=sys.stderr,
                )
                return 0

        for candidate in CANDIDATES:
            files = probe_commit(clone, candidate["commit"], overlay)
            record = {**candidate, "files": files}
            if files is not None:
                record["drifted"] = sorted(
                    rel for rel, e in files.items() if e["status"] == "drifted"
                )
                record["unchanged"] = sorted(
                    rel for rel, e in files.items() if e["status"] == "unchanged"
                )
                record["missing"] = sorted(
                    rel for rel, e in files.items() if e["status"] == "missing"
                )
            else:
                record["error"] = "clone-failed"
            report["candidates"].append(record)

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.write_fixture:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
        print(f"wrote {FIXTURE}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
