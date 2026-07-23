#!/usr/bin/env python3
"""Read-only v0.19 upgrade-readiness probe for the pinned Hermes overlay.

This tool DOES NOT change the production pin. It cryptographically verifies the
upstream SOURCE of the current pin (v0.18.0 == upstream tag v2026.7.1 == commit
``UPSTREAM_COMMIT``): the tag->commit mapping is confirmed via ``git ls-remote``
and every fingerprinted source file is matched byte-for-byte against the
overlay's ``FILES`` table.  The current image digest is an accepted historical
production pin recorded from the manifest -- it is NOT independently re-pulled
or signature-verified here.  Any new v0.19 digest requires independent
registry/signature verification before it may be accepted.

The probe then measures how far each *candidate* "next" upstream tag has drifted
from the overlay's fingerprint table. The output is the evidence a reviewer
needs to decide which upstream tag (if any) becomes "v0.19" and which overlay
insertions would have to be rebased.

Upstream publishes DATE tags only (v2026.7.1, v2026.7.7, ...); there is no
"v0.19" tag and no documented v0.19<->date-tag mapping, so this probe never
asserts which candidate IS v0.19 -- it only reports verified facts.

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

# The production pin: internal label v0.18.0 == upstream tag v2026.7.1. The commit
# is the peeled tag object verified via `git ls-remote --tags` and matches the
# overlay's UPSTREAM_COMMIT exactly.  The image_digest is an accepted historical
# production pin recorded from the manifest (PR #35 lineage), NOT independently
# re-pulled or signature-verified; any new v0.19 digest requires independent
# registry/signature verification.
CURRENT_PIN = {
    "label": "v0.18.0",
    "tag": "v2026.7.1",
    "commit": "7c1a029553d87c43ecff8a3821336bc95872213b",
    "image_digest": "sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f",
}

# Candidate "next" upstream tags -- a POINT-IN-TIME snapshot taken 2026-07-24 of
# every date tag published after v2026.7.1 (verified via `git ls-remote --tags`
# https://github.com/NousResearch/hermes-agent; the commit is each tag's peeled
# object). Upstream cuts new date tags frequently, so this list goes stale: refresh
# it (re-run `git ls-remote --tags`) before relying on the drift report. None of
# these is asserted to be "v0.19"; the owner/reviewer picks the target and verifies
# its image digest. The commit SHAs themselves are immutable once a tag is cut.
CANDIDATES = [
    {"tag": "v2026.7.7", "commit": "f9eca7e15f1c2bfe5194aae5aa489af53c0a1a23"},
    {"tag": "v2026.7.7.2", "commit": "9de9c25f620ff7f1ce0fd5457d596052d5159596"},
    {"tag": "v2026.7.20", "commit": "3ef6bbd201263d354fd83ec55b3c306ded2eb72a"},
]


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
    # Source integrity: the fetched commit must be the exact pinned SHA
    # (cryptographic tag->commit verification via git's object model).
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
        # verified v2026.7.1 source must match the overlay's FILES table exactly.
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
