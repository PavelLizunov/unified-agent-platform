#!/usr/bin/env python3
"""Diff-aware CI fast path classifier (stdlib-only, fail-open).

Decides which *expensive* `static-checks` step groups a `pull_request` may skip
based on the exact base/head diff. Security gates (secret_scan, gitleaks) are
deliberately NOT modelled here: the workflow runs them unconditionally, so this
classifier can never skip them.

Fail-open guarantee: every ambiguity resolves to RUN ALL CHECKS. A group is only
skipped when the event is a `pull_request`, both SHAs are exact and present, the
diff parses cleanly (NUL-terminated, no empty/surplus fields), every change has
exactly a one-character ``A`` or ``M`` status (multi-character codes like ``AA``,
``AU``, ``M100`` fail open), every path is a clean relative POSIX path of at least
two characters, and no changed path falls in that group's scope or in a fail-open
path.

The workflow consumes this via `skip_<group>` outputs and gates each step on
`if: ${{ steps.classify.outputs.skip_<group> != 'true' }}`. Because an unset or
`false` output runs the step, any classifier failure (crash, no output, error)
also fails open to running the step.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# Expensive step groups that may be skipped. Security is intentionally absent.
GROUPS = ("iac", "healthcheck", "hermes", "static", "tools")

# Closed scopes: a group runs when any changed path starts with one of these prefixes.
SCOPE_PREFIXES = {
    "iac": ("clusters/", "infra/"),          # IaC static validation + kustomize build
    "healthcheck": ("infra/",),              # ops healthcheck parser self-test (infra/ops)
    "hermes": ("hermes/",),                  # hermes unit tests (hermes runtime/overlays)
    "static": ("tests/", "tools/", "clusters/", "infra/"),  # contract guards also validate deployed IaC
    "tools": ("tools/",),                    # tools unit tests
}

# Any change under these prefixes forces RUN ALL (workflow/CI-tool/config surface).
FAIL_OPEN_PREFIXES = (".github/",)

# Any change to these exact files forces RUN ALL (dependencies, repo config, this classifier).
FAIL_OPEN_FILES = frozenset(
    {
        "requirements-dev.txt",
        ".gitleaks.toml",
        ".sops.yaml",
        ".gitattributes",
        ".gitignore",
        ".ragignore",
        "tests/static/ci_diff_classifier.py",
    }
)

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Entry:
    status: str
    path: str
    old: str | None = None


@dataclass(frozen=True)
class Decision:
    run_all: bool
    run: dict  # group -> bool (True = run the group)
    reason: str
    triggered: list = field(default_factory=list)


def valid_sha(sha: str | None) -> bool:
    return bool(sha) and bool(_SHA.match(sha))


def is_clean_path(path: str) -> bool:
    """Reject anything but a plain relative POSIX path (path traversal / weird names fail open)."""
    if not path:
        return False
    if len(path) < 2:
        return False
    if path.startswith(("/", "-")):
        return False
    if "\\" in path:
        return False
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return False
    if ".." in path.split("/"):
        return False
    return True


def is_fail_open_path(path: str) -> bool:
    if path in FAIL_OPEN_FILES:
        return True
    return path.startswith(FAIL_OPEN_PREFIXES)


def parse_name_status(raw: str) -> list[Entry]:
    """Parse `git diff --name-status -z` output (NUL-separated, rename/copy carry two paths).

    Structural validation (any violation raises ValueError → caller fails open):
    - A truly empty diff (``raw == ""``) returns ``[]`` (safe scoped empty).
    - Non-empty payloads must be NUL-terminated (real git ``-z`` always is).
    - No empty fields except the implicit trailing one from the final NUL.
    - Every field must be consumed by exactly one record (no surplus).
    """
    if raw == "":
        return []

    if not raw.endswith("\0"):
        raise ValueError("payload is not NUL-terminated")

    parts = raw.split("\0")
    if any(p == "" for p in parts[:-1]):
        raise ValueError("empty field in NUL-delimited payload")

    entries: list[Entry] = []
    i = 0
    n = len(parts) - 1  # exclude the trailing empty element
    while i < n:
        status = parts[i]
        i += 1
        letter = status[0]
        if letter in ("R", "C"):
            if i + 1 >= n:
                raise ValueError(f"truncated rename/copy record near {status!r}")
            old, new = parts[i], parts[i + 1]
            i += 2
            entries.append(Entry(status, new, old))
        else:
            if i >= n:
                raise ValueError(f"truncated record near {status!r}")
            entries.append(Entry(status, parts[i]))
            i += 1

    if i != n:
        raise ValueError("surplus fields after last record")

    return entries


def decide(event_name: str, base_sha: str, head_sha: str, name_status_z: str | None) -> Decision:
    """Pure decision function. `name_status_z` is the raw -z diff output, or None if unavailable."""
    run_everything = {g: True for g in GROUPS}

    if event_name != "pull_request":
        return Decision(True, run_everything, f"non-pull_request event {event_name!r}")

    if not valid_sha(base_sha) or not valid_sha(head_sha):
        return Decision(True, run_everything, "unknown/missing base or head SHA")

    if name_status_z is None:
        return Decision(True, run_everything, "base/head diff unavailable")

    try:
        entries = parse_name_status(name_status_z)
    except Exception as exc:  # noqa: BLE001 - any parse error fails open
        return Decision(True, run_everything, f"diff parse error: {exc}")

    triggered: set[str] = set()
    for entry in entries:
        if entry.status not in ("A", "M"):
            return Decision(True, run_everything, f"ambiguous change status {entry.status!r} (not exactly A or M)")
        if not is_clean_path(entry.path):
            return Decision(True, run_everything, f"unsafe path {entry.path!r}")
        if is_fail_open_path(entry.path):
            return Decision(True, run_everything, f"workflow/CI/dependency/config/classifier path {entry.path!r}")
        for group in GROUPS:
            if entry.path.startswith(SCOPE_PREFIXES[group]):
                triggered.add(group)

    run = {g: (g in triggered) for g in GROUPS}
    return Decision(False, run, "scoped diff", sorted(triggered))


def _git_name_status(base: str, head: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", base, head],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def _emit(decision: Decision) -> None:
    skipped = [g for g in GROUPS if not decision.run_all and not decision.run[g]]
    running = [g for g in GROUPS if decision.run_all or decision.run[g]]

    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        lines = [
            f"skip_{g}={'true' if g in skipped else 'false'}"
            for g in GROUPS
        ]
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    print(f"ci-diff-classifier: run_all={decision.run_all} reason={decision.reason}")
    print(f"  RUN groups:     {', '.join(running) if running else '(none beyond security)'}")
    print(f"  SKIPPED groups: {', '.join(skipped) if skipped else '(none)'}")
    print("  ALWAYS RUN:     secret_scan, gitleaks (security gates are never skipped)")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("## CI diff-aware routing\n\n")
            fh.write(f"- **Decision:** {'RUN ALL CHECKS' if decision.run_all else 'scoped fast path'}\n")
            fh.write(f"- **Reason:** {decision.reason}\n")
            fh.write(f"- **Running groups:** {', '.join(running) if running else '(none beyond security)'}\n")
            fh.write(f"- **SKIPPED groups:** {', '.join(skipped) if skipped else '(none)'}\n")
            fh.write("- **Always run (never skipped):** secret_scan, gitleaks\n")


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    base_sha = os.environ.get("UAP_DIFF_BASE_SHA", "")
    head_sha = os.environ.get("UAP_DIFF_HEAD_SHA", "")

    name_status_z = None
    if event_name == "pull_request" and valid_sha(base_sha) and valid_sha(head_sha):
        try:
            name_status_z = _git_name_status(base_sha, head_sha)
        except Exception:  # noqa: BLE001 - diff retrieval failure fails open
            name_status_z = None

    try:
        decision = decide(event_name, base_sha, head_sha, name_status_z)
    except Exception as exc:  # noqa: BLE001 - ultimate fail-open guard
        decision = Decision(True, {g: True for g in GROUPS}, f"classifier error: {exc}")

    _emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
