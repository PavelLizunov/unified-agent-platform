#!/usr/bin/env python3
"""Stdlib-only integration checks for the external Workspace overlay."""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import tempfile

TOOL = pathlib.Path(__file__).with_name("apply_overlay.py")
COMMIT = "c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c"
UPSTREAM = "https://github.com/outsourc-e/hermes-workspace"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), *map(str, args)],
        text=True,
        capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", nargs="?", type=pathlib.Path)
    args = parser.parse_args()
    source = args.checkout.resolve() if args.checkout else UPSTREAM
    with tempfile.TemporaryDirectory(prefix="hermes-workspace-overlay-") as temp:
        clone = pathlib.Path(temp) / "workspace"
        clone.mkdir()
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=clone,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "fetch", "--quiet", "--depth=1", str(source), COMMIT],
            cwd=clone,
            check=True,
        )
        subprocess.run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=clone, check=True, stdout=subprocess.DEVNULL)

        before = run(clone, "--check")
        assert before.returncode == 0, before.stderr
        assert "source-needs-overlay" in before.stdout

        first = run(clone)
        assert first.returncode == 0, first.stderr
        second = run(clone)
        assert second.returncode == 0 and "overlay already applied" in second.stdout
        checked = run(clone, "--check")
        assert checked.returncode == 0 and "exact-patched" in checked.stdout

        assignees = (clone / "src/routes/api/claude-tasks-assignees.ts").read_text()
        assert "? await gatewayFetch(url" in assignees
        assert ": await dashboardFetch(url" in assignees
        assert ": await fetch(url" not in assignees
        capabilities = (clone / "src/server/gateway-capabilities.ts").read_text()
        assert "HAS_DASHBOARD_USERNAME !== HAS_DASHBOARD_PASSWORD" in capabilities
        assert "Dashboard password auth requires both username and password" in capabilities
        root_source = (clone / "src/routes/__root.tsx").read_text()
        assert "DISABLED_GAME_PATHS" in root_source and "<Navigate to=\"/dashboard\" replace />" in root_source
        assert all(path in root_source for path in ("/reserve", "/reserve/confirm", "/early-access"))
        for endpoint in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
            assert "if (!HERMESWORLD_ENABLED) return json" in (clone / endpoint).read_text()
        profiles = (clone / "src/server/profiles-browser.ts").read_text()
        assert profiles.count("dashboardFetch('/api/profiles'") == 2
        assert "fetch(`${dashboardUrl}/api/profiles`" not in profiles
        assert "HERMES_API_TOKEN" not in profiles
        assert "CLAUDE_API_TOKEN" not in profiles
        assert "CLAUDE_DASHBOARD_TOKEN" not in profiles
        assert "function getDashboardToken" not in profiles
        read_start = profiles.index("export async function readProfileWithFallback")
        dashboard_pos = profiles.index("dashboardFetch('/api/profiles'", read_start)
        filesystem_pos = profiles.index("const profilePath", read_start)
        assert dashboard_pos < filesystem_pos
        assert "active: match.is_default === true" in profiles

        target = clone / "src/server/gateway-capabilities.ts"
        target.write_bytes(target.read_bytes() + b"\n// tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr

    print("workspace overlay checks passed")


if __name__ == "__main__":
    main()
