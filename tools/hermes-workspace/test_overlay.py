#!/usr/bin/env python3
"""Stdlib-only integration checks for the external Workspace overlay."""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import tempfile

TOOL = pathlib.Path(__file__).with_name("apply_overlay.py")
REPO_ROOT = TOOL.parents[2]
COMMIT = "c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c"
LEGACY_UAP_COMMIT = "9cd5040cfe6215cccef74a7f883099b1db8edd80"
PREVIOUS_UAP_COMMIT = "6bf941356dd00b41c34b12681abf4d5296c0f2f6"
CURSOR_REPLAY_COMMIT = "037af9a7a090d6ae41ee5d0d59e89315f0ef87bb"
PREVIOUS_PROGRESS_COMMIT = "9ef15aa750e40ef3d70cc578bdcf66e84c002187"
PREVIOUS_PROJECTS_COMMIT = "35c79703c4f3401d09ce7bcc3d936a4b062d96d9"
PREVIOUS_PERMISSIONS_COMMIT = "fd33c10d4949c2a63b01ea1d2c1c85a161e3fb1e"
PREVIOUS_PROJECT_CATALOG_UI_COMMIT = "95343b3ba3891c15dd80d9b911c66c013dcada69"
PREVIOUS_HIDE_COMMIT = "99a55da4c93b4d861241237b12bda05a8916ecf2"
PREVIOUS_SETUP_BINDING_COMMIT = "f60af5edd278e0886b7b0d531c189f78b698838a"
PREVIOUS_SETUP_KICKOFF_COMMIT = "8648040e9748f005986be9a87eee3c4d52a13b8e"
UPSTREAM = "https://github.com/outsourc-e/hermes-workspace"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), *map(str, args)],
        text=True,
        capture_output=True,
    )


def downgrade_legacy(relative: str, text: str) -> str:
    if relative == "src/server/gateway-capabilities.ts":
        text = text.replace(
            "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'\n"
            "const _initialOverrides = CENTRAL_ONLY ? {} : readOverrides()",
            "const _initialOverrides = readOverrides()",
            1,
        )
        text = text.replace(
            "  if (CENTRAL_ONLY) throw new Error('Gateway URL is environment-managed in central-only mode')\n",
            "",
            1,
        )
        text = text.replace(
            "  if (CENTRAL_ONLY) throw new Error('Dashboard URL is environment-managed in central-only mode')\n",
            "",
            1,
        )
        return text.replace(
            "  const overrides = CENTRAL_ONLY ? {} : readOverrides()",
            "  const overrides = readOverrides()",
            1,
        )
    if relative == "src/server/profiles-browser.ts":
        text = text.replace(
            "import { dashboardFetch } from './gateway-capabilities'\n\n"
            "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'",
            "import { dashboardFetch } from './gateway-capabilities'",
            1,
        )
        text = text.replace(
            "  if (CENTRAL_ONLY) throw new Error('Central profile source unavailable')\n",
            "",
            1,
        )
        return text.replace(
            "  if (CENTRAL_ONLY) throw new Error('Central profile not found or unavailable')\n\n",
            "",
            1,
        )
    raise AssertionError(relative)


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

        previous_script = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_PROJECTS_COMMIT}:tools/hermes-workspace/apply_overlay.py",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        )
        previous_namespace = {
            "__name__": "previous_workspace_overlay",
            "__file__": str(TOOL),
        }
        exec(compile(previous_script, "previous_workspace_overlay.py", "exec"), previous_namespace)
        previous_outputs = {}
        for relative in (
            "src/routes/api/send-stream.ts",
            "src/server/claude-api.ts",
        ):
            upstream_text = subprocess.check_output(
                ["git", "show", f"{COMMIT}:{relative}"],
                cwd=clone,
                text=True,
                encoding="utf-8",
            )
            previous_text = previous_namespace["transform"](relative, upstream_text)
            previous_outputs[relative] = previous_text
            (clone / relative).write_text(previous_text, encoding="utf-8")
        previous_check = run(clone, "--check")
        assert previous_check.returncode == 0
        assert previous_check.stdout.count("previous-needs-overlay") == 2
        previous_upgrade = run(clone)
        assert previous_upgrade.returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        for relative in (
            "src/routes/api/mission-projects.ts",
            "src/components/settings/project-permissions.tsx",
        ):
            previous_asset = subprocess.check_output(
                ["git", "show", f"{PREVIOUS_PERMISSIONS_COMMIT}:tools/hermes-workspace/files/{relative}"],
                cwd=REPO_ROOT,
            )
            (clone / relative).write_bytes(previous_asset)
        previous_permissions_check = run(clone, "--check")
        assert previous_permissions_check.returncode == 0
        assert previous_permissions_check.stdout.count("previous-needs-overlay") == 2
        previous_permissions_upgrade = run(clone)
        assert previous_permissions_upgrade.returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        previous_project_ui = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_PROJECT_CATALOG_UI_COMMIT}:tools/hermes-workspace/files/"
                "src/components/settings/project-permissions.tsx",
            ],
            cwd=REPO_ROOT,
        )
        previous_project_ui_path = (
            clone / "src/components/settings/project-permissions.tsx"
        )
        previous_project_ui_path.write_bytes(previous_project_ui)
        previous_project_ui_check = run(clone, "--check")
        assert previous_project_ui_check.returncode == 0
        assert (
            "src/components/settings/project-permissions.tsx: previous-needs-overlay"
            in previous_project_ui_check.stdout
        )
        previous_project_ui_upgrade = run(clone)
        assert previous_project_ui_upgrade.returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        production_setup_ui = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_SETUP_KICKOFF_COMMIT}:tools/hermes-workspace/files/"
                "src/components/settings/project-permissions.tsx",
            ],
            cwd=REPO_ROOT,
        )
        previous_project_ui_path.write_bytes(production_setup_ui)
        assert hashlib.sha256(production_setup_ui).hexdigest() == (
            "1d368904c3ee2fababb105b42cfa0539666bf7ddbe5580592c777d568f0194a0"
        )
        production_setup_check = run(clone, "--check")
        assert production_setup_check.returncode == 0
        assert "src/components/settings/project-permissions.tsx: previous-needs-overlay" in (
            production_setup_check.stdout
        )
        production_setup_upgrade = run(clone)
        assert production_setup_upgrade.returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

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
        blocked_routes = (
            "/playground", "/hermes-world", "/world", "/reserve", "/reserve/confirm",
            "/early-access", "/files", "/terminal", "/jobs", "/tasks", "/conductor",
            "/operations", "/agents", "/swarm", "/swarm2",
        )
        # Every experimental/non-authoritative route redirects direct navigation to /dashboard.
        assert "CENTRAL_ONLY_BLOCKED_PATHS = new Set([" in root_source
        assert all(f"'{path}'" in root_source for path in blocked_routes)
        assert "redirectBlockedRoute" in root_source
        assert "<Navigate to=\"/dashboard\" replace />" in root_source
        # HermesWorld and Update Center are fail-closed: only an explicit build-time
        # =1 enables them, so an undefined flag leaves both disabled.
        assert "import.meta.env.VITE_HERMESWORLD_ENABLED === '1'" in root_source
        assert "import.meta.env.VITE_UPDATE_CENTER_ENABLED === '1'" in root_source
        assert "!== '0'" not in root_source
        assert "{UPDATE_CENTER_ENABLED && !isHermesWorldLandingRoute ? <UpdateCenterNotifier />" in root_source
        for endpoint in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
            endpoint_source = (clone / endpoint).read_text()
            assert "import.meta.env.VITE_HERMESWORLD_ENABLED === '1'" in endpoint_source
            assert "process.env.VITE_HERMESWORLD_ENABLED" not in endpoint_source
            assert "!== '0'" not in endpoint_source
            assert "if (!HERMESWORLD_ENABLED) return json" in endpoint_source
        # Blocked entries are filtered out of the desktop sidebar.
        sidebar_source = (clone / "src/screens/chat/components/chat-sidebar.tsx").read_text()
        assert "CENTRAL_ONLY_BLOCKED_NAV_PATHS = new Set([" in sidebar_source
        assert ".filter((item) => !(item.kind === 'link' && item.to && CENTRAL_ONLY_BLOCKED_NAV_PATHS.has(item.to)))" in sidebar_source
        for path in ("/files", "/terminal", "/jobs", "/tasks", "/conductor", "/operations", "/swarm"):
            assert f"'{path}'" in sidebar_source
        for path in ("/dashboard", "/chat", "/memory", "/skills", "/mcp", "/profiles"):
            assert f"to: '{path}'" in sidebar_source
        # Blocked entries are filtered out of mobile navigation (hamburger + tab bar).
        hamburger_source = (clone / "src/components/mobile-hamburger-menu.tsx").read_text()
        assert "CENTRAL_ONLY_BLOCKED_NAV_IDS = new Set([" in hamburger_source
        assert "!CENTRAL_ONLY_BLOCKED_NAV_IDS.has(item.id)" in hamburger_source
        for nav_id in ("playground", "terminal", "jobs", "conductor", "operations", "swarm"):
            assert f"'{nav_id}'" in hamburger_source
        tab_bar_source = (clone / "src/components/mobile-tab-bar.tsx").read_text()
        assert "VISIBLE_NAV_TABS = MOBILE_NAV_TABS.filter((tab) => !CENTRAL_ONLY_BLOCKED_TAB_IDS.has(tab.id))" in tab_bar_source
        assert "{VISIBLE_NAV_TABS.map((tab, idx) => {" in tab_bar_source
        assert "MOBILE_NAV_TABS.map" not in tab_bar_source
        assert "MOBILE_NAV_TABS.findIndex" not in tab_bar_source
        for nav_id in ("playground", "files", "terminal", "jobs", "swarm"):
            assert f"'{nav_id}'" in tab_bar_source
        # Blocked entries are filtered out of the command palette; allowed screens remain.
        palette_source = (clone / "src/components/command-palette.tsx").read_text()
        assert "CENTRAL_ONLY_BLOCKED_SCREEN_IDS = new Set(['screen-files', 'screen-terminal'])" in palette_source
        assert ".filter((action) => !CENTRAL_ONLY_BLOCKED_SCREEN_IDS.has(action.id))" in palette_source
        for screen_id in ("screen-chat", "screen-memory", "screen-skills", "screen-mcp", "screen-settings"):
            assert f"id: '{screen_id}'" in palette_source
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
        assert sessions.count("SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503") == 1
        assert (
            "if (!CENTRAL_ONLY && capabilities.dashboard.available && "
            "!capabilities.enhancedChat)"
        ) in sessions
        assert "if (!CENTRAL_ONLY && localSession)" in sessions
        assert "if (!CENTRAL_ONLY && getLocalSession(sessionKey))" in sessions
        assert "setup_project_id: setupProjectId || undefined" in sessions
        assert "uap_project_setup=" in sessions

        chat_screen = (clone / "src/screens/chat/chat-screen.tsx").read_text()
        new_chat = chat_screen[chat_screen.index("if (isNewChat) {") :]
        create_first = new_chat.index("createSessionForMessage(threadId)")
        send_first = new_chat.index("sendMessage(", create_first)
        assert create_first < send_first
        assert ".then(({ sessionKey, friendlyId }) => {" in new_chat[create_first:send_first]
        assert "Central session identity mismatch" in new_chat
        assert "setPendingGeneration(false)" in new_chat
        assert "if (statusQuery.data?.ok !== true) return" in chat_screen
        assert "[runPaletteSlashCommand, statusQuery.data?.ok]" in chat_screen

        chat_screen_path = clone / "src/screens/chat/chat-screen.tsx"
        previous_chat_screen = chat_screen.replace(
            """  useEffect(() => {
    if (statusQuery.data?.ok !== true) return
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand, statusQuery.data?.ok])""",
            """  useEffect(() => {
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand])""",
            1,
        )
        chat_screen_path.write_text(previous_chat_screen, encoding="utf-8")
        assert hashlib.sha256(chat_screen_path.read_bytes()).hexdigest() == (
            "d20725179b11de51faebd0f35a54b6716d0343d094c87e65e30da5680469c9da"
        )
        previous_chat_check = run(clone, "--check")
        assert previous_chat_check.returncode == 0
        assert "src/screens/chat/chat-screen.tsx: previous-needs-overlay" in (
            previous_chat_check.stdout
        )
        assert run(clone).returncode == 0
        assert hashlib.sha256(chat_screen_path.read_bytes()).hexdigest() == (
            "7b9e6a3bb701d43b25f2c766296c66ba70c90469ea39ff607886cc471098cf77"
        )

        sessions_path = clone / "src/routes/api/sessions.ts"
        previous_sessions = sessions.replace(
            """          if (!CENTRAL_ONLY && capabilities.dashboard.available && !capabilities.enhancedChat) {
            return json({""",
            """          if (capabilities.dashboard.available && !capabilities.enhancedChat) {
            if (CENTRAL_ONLY) {
              return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503 })
            }
            return json({""",
            1,
        )
        sessions_path.write_text(previous_sessions, encoding="utf-8")
        assert hashlib.sha256(sessions_path.read_bytes()).hexdigest() == (
            "75f30477f71b088646364aac40ed8d6654da5f98d7f429dd714546c69364e5ce"
        )
        previous_sessions_check = run(clone, "--check")
        assert previous_sessions_check.returncode == 0
        assert "src/routes/api/sessions.ts: previous-needs-overlay" in previous_sessions_check.stdout
        previous_sessions_upgrade = run(clone)
        assert previous_sessions_upgrade.returncode == 0, previous_sessions_upgrade.stderr
        previous_sessions_checked = run(clone, "--check")
        assert previous_sessions_checked.returncode == 0
        assert "src/routes/api/sessions.ts: exact-patched" in previous_sessions_checked.stdout

        production_previous_script = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_SETUP_BINDING_COMMIT}:tools/hermes-workspace/apply_overlay.py",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        )
        production_previous_namespace = {
            "__name__": "production_previous_workspace_overlay",
            "__file__": str(TOOL),
        }
        exec(
            compile(production_previous_script, "production_previous_workspace_overlay.py", "exec"),
            production_previous_namespace,
        )
        upstream_sessions = subprocess.check_output(
            ["git", "show", f"{COMMIT}:src/routes/api/sessions.ts"],
            cwd=clone,
            text=True,
            encoding="utf-8",
        )
        production_previous_sessions = production_previous_namespace["transform"](
            "src/routes/api/sessions.ts",
            upstream_sessions,
        )
        sessions_path.write_text(production_previous_sessions, encoding="utf-8")
        production_previous_hash = hashlib.sha256(sessions_path.read_bytes()).hexdigest()
        assert production_previous_hash == (
            "f1fa702405ce65cbf937a8883c5f7f13bc19c681b5e7fae10cdf15122328267c"
        ), production_previous_hash
        production_previous_upgrade = run(clone)
        assert production_previous_upgrade.returncode == 0, production_previous_upgrade.stderr
        assert "src/routes/api/sessions.ts: exact-patched" in run(clone, "--check").stdout

        send_stream = (clone / "src/routes/api/send-stream.ts").read_text()
        central_stream = send_stream.index("if (CENTRAL_ONLY) {\n          chatMode = 'enhanced-claude'")
        portable_session = send_stream.index("if (chatMode === 'portable' && sessionKey === 'new')")
        assert central_stream < portable_session
        assert "Central session stream unavailable" not in send_stream
        assert "message identity required" in send_stream
        assert "message: CENTRAL_ONLY ? message : scopedMessage" in send_stream
        assert "source_message_id: CENTRAL_ONLY ? sourceMessageId : undefined" in send_stream
        assert "project_id: CENTRAL_ONLY && projectId ? projectId : undefined" in send_stream
        assert "setup_project_id: CENTRAL_ONLY && setupProjectId ? setupProjectId : undefined" in send_stream
        assert "Выберите проект в Настройки → Проекты и доступы" not in send_stream

        project_api = (clone / "src/routes/api/mission-projects.ts").read_text()
        assert "gatewayFetch('/api/mission-projects?platform=workspace'" in project_api
        assert "Проект не зарегистрирован" in project_api
        assert "project.status !== 'ready'" in project_api
        assert "body?.mode === 'setup'" in project_api
        assert "uap_project_setup" in project_api
        assert "HttpOnly; SameSite=Strict" in project_api
        onboarding_api = (
            clone / "src/routes/api/project-onboarding.ts"
        ).read_text()
        assert "createFileRoute('/api/project-onboarding')" in onboarding_api
        assert "gatewayFetch(path" in onboarding_api
        assert "central('/api/project-onboarding'" in onboarding_api
        assert "const PRESETS = new Set(['rust', 'go', 'python', 'web'])" in onboarding_api
        assert "PROJECT_NAME.test(body.name)" in onboarding_api
        assert "uap_project_onboarding" in onboarding_api
        assert "uap_mission_project" in onboarding_api
        assert "process.env.HERMES_MISSION_OWNER_KEY?.trim()" in onboarding_api
        assert "'X-Hermes-Mission-Owner-Key': ownerKey" in onboarding_api
        assert onboarding_api.count("HttpOnly; SameSite=Strict") == 3
        assert all(field not in onboarding_api for field in (
            "shell_command", "source_checkout", "dispatch_profile", "model_id",
        ))
        project_settings = (
            clone / "src/components/settings/project-permissions.tsx"
        ).read_text()
        assert "Платформа может менять код" in project_settings
        assert "Проверки:" in project_settings
        assert "После слияния: автоматический деплой и проверка production" in project_settings
        assert "vpnctl production" in project_settings
        assert "Control-plane, Proxmox и ops-сервер" in project_settings
        assert "project.status === 'ready'" in project_settings
        assert "Создать и подготовить" in project_settings
        assert "Дополнительных подтверждений не потребуется" in project_settings
        assert "GitHub macOS" in project_settings
        assert "window.setInterval" in project_settings
        assert "onboarding.progress_percent" in project_settings
        assert "Настроить в чате" in project_settings
        assert "CHAT_PENDING_COMMAND_STORAGE_KEY" in project_settings
        assert "/discuss Задай 3–5 коротких вопросов" in project_settings
        assert "Не используй инструменты" in project_settings
        assert "window.location.assign('/chat/new')" in project_settings
        status_position = project_settings.index(
            "{statusLabels[project.status] || project.status}"
        )
        primary_project_position = project_settings.index(
            "project.category === 'active-maintained'", status_position
        )
        test_targets_position = project_settings.index(
            "{project.test_targets.length", primary_project_position
        )
        assert "Основной проект" in project_settings[
            primary_project_position:test_targets_position
        ]
        settings_sidebar = (
            clone / "src/components/settings/settings-sidebar.tsx"
        ).read_text()
        assert "{ id: 'projects', label: 'Проекты и доступы' }" in settings_sidebar
        settings_page = (clone / "src/routes/settings/index.tsx").read_text()
        assert "<ProjectPermissions />" in settings_page
        claude_api = (clone / "src/server/claude-api.ts").read_text()
        assert "source_message_id?: string" in claude_api
        assert "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'" in claude_api
        assert "project_id?: string" in claude_api
        assert "setup_project_id?: string" in claude_api
        create_session = claude_api[
            claude_api.index("export async function createSession"):
            claude_api.index("export async function updateSession")
        ]
        assert "setup_project_id?: string" in create_session
        create_session_start = claude_api.index("export async function createSession")
        update_session = claude_api.index("export async function updateSession")
        assert "if (!CENTRAL_ONLY && getCapabilities().dashboard.available)" in (
            claude_api[create_session_start:update_session]
        )

        send_stream_path = clone / "src/routes/api/send-stream.ts"
        previous_send_stream = previous_outputs["src/routes/api/send-stream.ts"].replace("""        if (CENTRAL_ONLY) {
          chatMode = 'enhanced-claude'
        }""", """        if (CENTRAL_ONLY && chatMode === 'portable') {
          return new Response(JSON.stringify({ ok: false, error: 'Central session stream unavailable' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }""", 1)
        send_stream_path.write_text(previous_send_stream, encoding="utf-8")
        assert hashlib.sha256(send_stream_path.read_bytes()).hexdigest() == (
            "8cdcb90478dbd7c41839e6f4229b83bf5e5c5526f06528b2fdbd82700c3b54de"
        )
        previous = run(clone, "--check")
        assert previous.returncode == 0 and "previous-needs-overlay" in previous.stdout
        previous_upgrade = run(clone)
        assert previous_upgrade.returncode == 0, previous_upgrade.stderr
        previous_checked = run(clone, "--check")
        assert previous_checked.returncode == 0
        assert "previous-needs-overlay" not in previous_checked.stdout
        assert "src/routes/api/send-stream.ts: exact-patched" in previous_checked.stdout

        claude_api_path = clone / "src/server/claude-api.ts"
        previous_claude_api = previous_outputs["src/server/claude-api.ts"].replace(
            "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'\n",
            "",
            1,
        ).replace(
            "if (!CENTRAL_ONLY && getCapabilities().dashboard.available)",
            "if (getCapabilities().dashboard.available)",
            1,
        )
        claude_api_path.write_text(previous_claude_api, encoding="utf-8")
        assert hashlib.sha256(claude_api_path.read_bytes()).hexdigest() == (
            "15edfd328c3757fba773af30329959bf345347daab3a93d6abdb7e533ce6dc92"
        )
        previous_api = run(clone, "--check")
        assert previous_api.returncode == 0
        assert "src/server/claude-api.ts: previous-needs-overlay" in previous_api.stdout
        previous_api_upgrade = run(clone)
        assert previous_api_upgrade.returncode == 0, previous_api_upgrade.stderr
        previous_api_checked = run(clone, "--check")
        assert previous_api_checked.returncode == 0
        assert "src/server/claude-api.ts: exact-patched" in previous_api_checked.stdout

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
        assert "mission_id" in mission_route
        assert "after=${after}" in mission_route
        assert "Invalid mission replay request" in mission_route
        assert "POST: async ({ request })" in mission_route
        assert "/answer`" in mission_route
        assert "JSON.stringify({ question_id: questionId, text })" in mission_route
        assert "HERMES_MISSION_OWNER_KEY" in mission_route
        assert "X-Hermes-Mission-Owner-Key" in mission_route
        mission_card = (
            clone / "src/screens/dashboard/components/mission-overview-card.tsx"
        ).read_text()
        assert "refetchInterval: 2_000" in mission_card
        assert "mergeMissionReplay" in mission_card
        assert "Mission event sequence gap" in mission_card
        assert "Mission replay cursor mismatch" in mission_card
        assert "previous?.cursor ?? 0" in mission_card
        assert "const missionEvents = replayQuery.data?.events ?? []" in mission_card
        assert "replayRef.current.events" not in mission_card
        assert "Хронология" in mission_card
        assert "От вас ничего не требуется." in mission_card
        assert "Следующая автоматическая попытка" in mission_card
        assert "Последнее обновление" in mission_card
        assert "updated_at" in mission_card
        assert "item.project_label || item.project_repository?.split('/').pop()" in mission_card
        assert ".replace(/\\s+/g, ' ').slice(0, 48)" in mission_card
        assert "item.mission_id.slice(-8)" in mission_card
        assert "mission.projection_id" in mission_card
        assert "mission.terminal" in mission_card
        assert "Подробнее о задаче" in mission_card
        assert "missionIdFromLocation" in mission_card
        assert "selectMissionInLocation" in mission_card
        assert "missionDeepLink" in mission_card
        assert "Ссылка на эту задачу" in mission_card
        assert "new URL('/dashboard', window.location.origin)" in mission_card
        assert "runningTaskTitle" in mission_card
        assert "waitLabels" in mission_card
        assert "checkpointLabels" in mission_card
        assert "costUnattested" in mission_card
        # Unknown stage falls back to the localized generic label, never raw.
        assert "const stageLabel = stageLabels[mission.stage] || 'Выполнение'" in mission_card
        assert "stageLabels[mission.stage] || mission.stage || 'Выполнение'" not in mission_card
        # Running task title is whitespace-normalized AND trimmed.
        assert ".replace(/\\s+/g, ' ').trim().slice(0, 120)" in mission_card
        assert "Сейчас: {currentOperation}" in mission_card
        assert "Контрольная точка: {checkpoint}" in mission_card
        assert "durable-событие ${mission.sequence}" in mission_card
        assert "Ждёт: {waitingFor}" in mission_card
        assert "причина ожидания ещё не записана" in mission_card
        assert "Нужно ваше действие: {ownerActionRequired ? 'да' : 'нет'}" in mission_card
        assert "runtime-кэш (подтверждено runtime, не биллинг)" in mission_card
        assert "checkpoint ${mission.notice.phase}" not in mission_card
        assert "Накопительный расход выбранной задачи" in mission_card
        assert "Последние сохранённые прогоны" in mission_card
        assert "eventPresentation" in mission_card
        assert "число запросов не сохранено" in mission_card
        assert "данные о кэше не сохранены" in mission_card
        assert "Открыть текущий PR или результат" in mission_card
        assert "предыдущих или отброшенных прогонов не входят в сумму" in mission_card
        assert "whitespace-pre-wrap leading-relaxed" in mission_card
        assert "project_repository" in mission_card
        assert 'aria-label="Ответ"' in mission_card
        assert "question_id: question.question_id" in mission_card

        previous_added = {
            "src/routes/api/missions.ts":
                "082ffe7f4d100d8a5a64fbde40893cfba1f98a1774c914acb2495ce1a857a243",
            "src/screens/dashboard/components/mission-overview-card.tsx":
                "990eb901032d2f2784eece487bc462b02b0672c1feb9f0c1bef403e1019e6b5b",
        }
        for relative, expected in previous_added.items():
            previous_asset = subprocess.check_output(
                [
                    "git", "show",
                    f"{PREVIOUS_UAP_COMMIT}:tools/hermes-workspace/files/{relative}",
                ],
                cwd=REPO_ROOT,
            )
            path = clone / relative
            path.write_bytes(previous_asset)
            assert hashlib.sha256(previous_asset).hexdigest() == expected
        previous_added_check = run(clone, "--check")
        assert previous_added_check.returncode == 0
        assert previous_added_check.stdout.count("previous-needs-overlay") == 2
        previous_added_upgrade = run(clone)
        assert previous_added_upgrade.returncode == 0
        assert "overlay applied" in previous_added_upgrade.stdout
        previous_added_final = run(clone, "--check")
        assert previous_added_final.returncode == 0
        assert "previous-needs-overlay" not in previous_added_final.stdout

        vulnerable_card = subprocess.check_output(
            [
                "git", "show",
                f"{CURSOR_REPLAY_COMMIT}:tools/hermes-workspace/files/"
                "src/screens/dashboard/components/mission-overview-card.tsx",
            ],
            cwd=REPO_ROOT,
        )
        vulnerable_card_path = (
            clone / "src/screens/dashboard/components/mission-overview-card.tsx"
        )
        vulnerable_card_path.write_bytes(vulnerable_card)
        assert hashlib.sha256(vulnerable_card).hexdigest() == (
            "8fc9a10f19a40df929f57695e3efaf44c2ae1f8fdd19df80212f7161d195be89"
        )
        vulnerable_check = run(clone, "--check")
        assert vulnerable_check.returncode == 0
        assert vulnerable_check.stdout.count("previous-needs-overlay") == 1
        vulnerable_upgrade = run(clone)
        assert vulnerable_upgrade.returncode == 0
        assert "overlay applied" in vulnerable_upgrade.stdout
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        current_card = subprocess.check_output(
            [
                "git", "show",
                "ce231273a5786ed032ef3c1777de762c421330bb:"
                "tools/hermes-workspace/files/src/screens/dashboard/components/"
                "mission-overview-card.tsx",
            ],
            cwd=REPO_ROOT,
        )
        vulnerable_card_path.write_bytes(current_card)
        assert hashlib.sha256(current_card).hexdigest() == (
            "486df3f1451ce7cbc4e80dbce70dd3105d39b78b64b5c61d2a2a6e91fd0b532d"
        )
        current_check = run(clone, "--check")
        assert current_check.returncode == 0
        assert current_check.stdout.count("previous-needs-overlay") == 1
        assert run(clone).returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        previous_progress_card = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_PROGRESS_COMMIT}:tools/hermes-workspace/files/"
                "src/screens/dashboard/components/mission-overview-card.tsx",
            ],
            cwd=REPO_ROOT,
        )
        vulnerable_card_path.write_bytes(previous_progress_card)
        assert hashlib.sha256(previous_progress_card).hexdigest() == (
            "3b0fe465c716052bc8b3c094d5c3d8a28613a9bf7a2ab2e8e103aa186a46398b"
        )
        previous_progress_check = run(clone, "--check")
        assert previous_progress_check.returncode == 0
        assert previous_progress_check.stdout.count("previous-needs-overlay") == 1
        assert run(clone).returncode == 0
        assert "previous-needs-overlay" not in run(clone, "--check").stdout

        for relative, expected in (
            (
                "src/server/gateway-capabilities.ts",
                "d599c442441be9763e0d6d3c4fb999783e326ad61ea7261064d79337cac840e5",
            ),
            (
                "src/server/profiles-browser.ts",
                "e5b84d509ad2960f2a0a57d785d3602110fdaf6e4dffa0da4211858d74d86385",
            ),
        ):
            path = clone / relative
            path.write_text(downgrade_legacy(relative, path.read_text()), encoding="utf-8")
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        legacy = run(clone, "--check")
        assert legacy.returncode == 0 and legacy.stdout.count("legacy-needs-overlay") == 2
        upgraded = run(clone)
        assert upgraded.returncode == 0 and "overlay applied" in upgraded.stdout
        upgraded_check = run(clone, "--check")
        assert upgraded_check.returncode == 0 and "legacy-needs-overlay" not in upgraded_check.stdout

        legacy_added = {
            "src/routes/api/missions.ts":
                "e92e59ee7556741adac03a0850b1166234e582ba7cdaaa16379a4347797c84ac",
            "src/screens/dashboard/components/mission-overview-card.tsx":
                "7ab5ceff84f8b8a6eefd8acf694dfd27047b57ac25d73956707fbf2ea9088c45",
        }
        for relative, expected in legacy_added.items():
            previous_asset = subprocess.check_output(
                [
                    "git", "show",
                    f"{LEGACY_UAP_COMMIT}:tools/hermes-workspace/files/{relative}",
                ],
                cwd=REPO_ROOT,
            )
            path = clone / relative
            path.write_bytes(previous_asset)
            assert hashlib.sha256(previous_asset).hexdigest() == expected
        legacy_added_check = run(clone, "--check")
        assert legacy_added_check.returncode == 0
        assert legacy_added_check.stdout.count("legacy-needs-overlay") == 2
        legacy_added_upgrade = run(clone)
        assert legacy_added_upgrade.returncode == 0 and "overlay applied" in legacy_added_upgrade.stdout
        final_check = run(clone, "--check")
        assert final_check.returncode == 0 and "legacy-needs-overlay" not in final_check.stdout

        hide_script = subprocess.check_output(
            [
                "git", "show",
                f"{PREVIOUS_HIDE_COMMIT}:tools/hermes-workspace/apply_overlay.py",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        )
        hide_namespace = {
            "__name__": "hide_workspace_overlay",
            "__file__": str(TOOL),
        }
        exec(compile(hide_script, "hide_workspace_overlay.py", "exec"), hide_namespace)
        hide_files = (
            "src/components/mobile-hamburger-menu.tsx",
            "src/components/mobile-tab-bar.tsx",
            "src/routes/__root.tsx",
            "src/routes/api/playground-admin.ts",
            "src/routes/api/playground-npc.ts",
        )
        hide_expected = {
            "src/components/mobile-hamburger-menu.tsx":
                "9f6bd64d1b5bdf6e8913c2d87e870be5767a8ec606ecf777740d6d4602f15deb",
            "src/components/mobile-tab-bar.tsx":
                "8e699f2c2fe547001a3d0c42bcaf0c9b737bb681fe2817d689865d6110b1c08c",
            "src/routes/__root.tsx":
                "c61251c233f325a6a9871bc153b89e0aa91baac2cd1c4aa03f54422f366907fc",
            "src/routes/api/playground-admin.ts":
                "c99380cd813bad4e7d210e1654211bb571751cbb9de553cdd00f501febf13a27",
            "src/routes/api/playground-npc.ts":
                "652135b9afb2ae8cabcf0ae4d4f9d993cee1f335a72482dbd07bba51914098f7",
        }
        for relative in hide_files:
            upstream_text = subprocess.check_output(
                ["git", "show", f"{COMMIT}:{relative}"],
                cwd=clone,
                text=True,
                encoding="utf-8",
            )
            old_patched = hide_namespace["transform"](relative, upstream_text)
            (clone / relative).write_text(old_patched, encoding="utf-8")
            assert hashlib.sha256((clone / relative).read_bytes()).hexdigest() == hide_expected[relative]
        hide_check = run(clone, "--check")
        assert hide_check.returncode == 0
        assert hide_check.stdout.count("previous-needs-overlay") == 5
        hide_upgrade = run(clone)
        assert hide_upgrade.returncode == 0, hide_upgrade.stderr
        assert "overlay applied" in hide_upgrade.stdout
        hide_final = run(clone, "--check")
        assert hide_final.returncode == 0
        assert "previous-needs-overlay" not in hide_final.stdout
        assert hide_final.stdout.count("exact-patched") == len(hide_final.stdout.strip().splitlines())
        hide_idempotent = run(clone)
        assert hide_idempotent.returncode == 0
        assert "overlay already applied" in hide_idempotent.stdout

        target = clone / "src/server/gateway-capabilities.ts"
        target.write_bytes(target.read_bytes() + b"\n// tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr

    print("workspace overlay checks passed")


if __name__ == "__main__":
    main()
