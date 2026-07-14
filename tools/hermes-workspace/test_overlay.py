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
        assert "const _initialOverrides = CENTRAL_ONLY ? {} : readOverrides()" in capabilities
        assert capabilities.count("environment-managed in central-only mode") == 2
        root_source = (clone / "src/routes/__root.tsx").read_text()
        assert "DISABLED_GAME_PATHS" in root_source and "<Navigate to=\"/dashboard\" replace />" in root_source
        assert all(path in root_source for path in ("/reserve", "/reserve/confirm", "/early-access"))
        for endpoint in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
            endpoint_source = (clone / endpoint).read_text()
            assert "import.meta.env.VITE_HERMESWORLD_ENABLED" in endpoint_source
            assert "process.env.VITE_HERMESWORLD_ENABLED" not in endpoint_source
            assert "if (!HERMESWORLD_ENABLED) return json" in endpoint_source
        models_source = (clone / "src/routes/api/models.ts").read_text()
        central_only = models_source.index("process.env.HERMES_CENTRAL_ONLY === '1'")
        local_catalog = models_source.index("let models = readClaudeModelsJson()")
        assert central_only < local_catalog
        assert "source: 'hermes-agent'" in models_source[central_only:local_catalog]
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
        assert "Central profile source unavailable" in profiles
        assert "Central profile not found or unavailable" in profiles

        sessions = (clone / "src/routes/api/sessions.ts").read_text()
        assert "const localSessions = CENTRAL_ONLY ? [] : listLocalSessions()" in sessions
        assert sessions.count("SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503") == 2
        assert "if (!CENTRAL_ONLY && localSession)" in sessions
        assert "if (!CENTRAL_ONLY && getLocalSession(sessionKey))" in sessions

        send_stream = (clone / "src/routes/api/send-stream.ts").read_text()
        assert "if (CENTRAL_ONLY && chatMode === 'portable')" in send_stream
        assert "Central session stream unavailable" in send_stream

        kanban = (clone / "src/server/kanban-backend.ts").read_text()
        central_selection = kanban.index("if (CENTRAL_ONLY)", kanban.index("export function resolveKanbanBackend"))
        local_selection = kanban.index("if (preference === 'local')")
        assert central_selection < local_selection
        assert "Central Kanban unavailable in central-only mode" in kanban

        local_tasks = (clone / "src/routes/api/hermes-tasks.ts").read_text()
        assert local_tasks.count("Local task store disabled in central-only mode") == 2

        jobs = (clone / "src/routes/api/claude-jobs.ts").read_text()
        assert "const aggregateProfiles = !CENTRAL_ONLY" in jobs
        assert "Central jobs unavailable" in jobs
        assert "Local profile jobs disabled in central-only mode" in jobs

        conductor = (clone / "src/routes/api/conductor-spawn.ts").read_text()
        assert "const nativeMission = CENTRAL_ONLY ? null : getSwarmMission(missionId)" in conductor
        assert conductor.count("Central Conductor unavailable in central-only mode") == 2

        dashboard = (clone / "src/screens/dashboard/dashboard-screen.tsx").read_text()
        assert "import { MissionOverviewCard }" in dashboard
        assert "<MissionOverviewCard />" in dashboard
        mission_route = (clone / "src/routes/api/missions.ts").read_text()
        assert "gatewayFetch" in mission_route
        assert "Central mission API unavailable" in mission_route
        mission_card = (
            clone / "src/screens/dashboard/components/mission-overview-card.tsx"
        ).read_text()
        assert "refetchInterval: 2_000" in mission_card
        assert "mission.projection_id" in mission_card
        assert "mission.terminal" in mission_card

        target = clone / "src/server/gateway-capabilities.ts"
        target.write_bytes(target.read_bytes() + b"\n// tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr

    print("workspace overlay checks passed")


if __name__ == "__main__":
    main()
