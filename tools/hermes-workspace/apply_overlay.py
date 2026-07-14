#!/usr/bin/env python3
"""Fail-closed overlay for the exact upstream Hermes Workspace checkout."""
from __future__ import annotations
import argparse, hashlib, pathlib, subprocess, sys

UPSTREAM_COMMIT = "c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c"
FILES = {
"src/server/gateway-capabilities.ts": "e943f28707c25875f03cb58355b4be8025e944236711ceabbb1500882d409a2f",
"src/server/kanban-dashboard-proxy.ts": "3aa2c969243f408bd5dd3894d56d97007adf6a7b760575ef6ae9e7404e428a9a",
"src/routes/api/claude-tasks-assignees.ts": "02787cf45c5d9b7f4dc9c4b0e92b6e23b9c4ef7295cb11674499cc6fbea5dc5c",
"src/server/profiles-browser.ts": "3e948bc92d894b79e381734c3e3e94157158650f415e0535feb5d82e0bded118",
"src/components/mobile-hamburger-menu.tsx": "6432922ae6aa8908bfbc1295cafbf0c7bd7bfb704f489962f55fa3afbde1d796",
"src/components/mobile-tab-bar.tsx": "cc2d5268157b3fc666a993406181398a3a7f23a41ab2012fb662dbeb678588de",
"src/routes/__root.tsx": "1a6b2ae761aa1500835c53f79bf61730796fe2a67163a7c21012c44b793ae081",
"src/routes/api/playground-admin.ts": "19b98cbed55f4ab874532e978484b4abebd14ec855d54461cb46ce965581113c",
"src/routes/api/playground-npc.ts": "7e90a3a801ac7dbb85c5a97f3d51500c23d0296809b2f7497a034bf3cc97df30",
}
PATCHED_FILES = {
"src/server/gateway-capabilities.ts": "d599c442441be9763e0d6d3c4fb999783e326ad61ea7261064d79337cac840e5",
"src/server/kanban-dashboard-proxy.ts": "ba981a50148a0d75b6a02d873646fd0371e116a266a907b56b4c5b4eb10ac6f7",
"src/routes/api/claude-tasks-assignees.ts": "001e870c6db2294ad73315de09b4a8f5337061a9bb179af63f01489d148fa0e9",
"src/server/profiles-browser.ts": "e5b84d509ad2960f2a0a57d785d3602110fdaf6e4dffa0da4211858d74d86385",
"src/components/mobile-hamburger-menu.tsx": "9f6bd64d1b5bdf6e8913c2d87e870be5767a8ec606ecf777740d6d4602f15deb",
"src/components/mobile-tab-bar.tsx": "8e699f2c2fe547001a3d0c42bcaf0c9b737bb681fe2817d689865d6110b1c08c",
"src/routes/__root.tsx": "c61251c233f325a6a9871bc153b89e0aa91baac2cd1c4aa03f54422f366907fc",
"src/routes/api/playground-admin.ts": "1f92db5976f9ac223ef9fce1fe31d22b37cc308557c95e1ae952e9dee5f06cc3",
"src/routes/api/playground-npc.ts": "55365b5826bf41b1bf407db0a51c72f383a20b75753d47f8a3ac429aa5e4586d",
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def replace(text, old, new, name):
    if old not in text: raise SystemExit(f"overlay fragment mismatch: {name}")
    return text.replace(old, new, 1)
def transform(rel, text):
    if rel == "src/server/gateway-capabilities.ts":
        text = replace(text, "let dashboardTokenPromise: Promise<string> | null = null\nlet dashboardTokenCache = ''",
"""let dashboardTokenPromise: Promise<string> | null = null
let dashboardTokenCache = ''
let dashboardCookiePromise: Promise<string> | null = null
let dashboardCookieCache = ''
const HAS_DASHBOARD_USERNAME = Boolean(process.env.HERMES_DASHBOARD_USERNAME)
const HAS_DASHBOARD_PASSWORD = Boolean(process.env.HERMES_DASHBOARD_PASSWORD)
if (HAS_DASHBOARD_USERNAME !== HAS_DASHBOARD_PASSWORD) {
  throw new Error('Dashboard password auth requires both username and password')
}
const REMOTE_PASSWORD_AUTH = HAS_DASHBOARD_USERNAME && HAS_DASHBOARD_PASSWORD

function cookieHeader(res: Response): string {
  const headers = res.headers as Headers & { getSetCookie?: () => string[] }
  const values = headers.getSetCookie?.() ?? (headers.get('set-cookie') ? [headers.get('set-cookie')!] : [])
  return values.map((value) => value.split(';', 1)[0]).filter(Boolean).join('; ')
}

async function fetchDashboardCookie(force = false): Promise<string> {
  if (!REMOTE_PASSWORD_AUTH) return ''
  if (!force && dashboardCookieCache) return dashboardCookieCache
  if (!force && dashboardCookiePromise) return dashboardCookiePromise
  dashboardCookiePromise = (async () => {
    const res = await fetch(`${CLAUDE_DASHBOARD_URL}/auth/password-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'basic', username: process.env.HERMES_DASHBOARD_USERNAME, password: process.env.HERMES_DASHBOARD_PASSWORD, next: '/' }),
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    })
    if (!res.ok) throw new Error(`Dashboard password login failed: ${res.status}`)
    const cookie = cookieHeader(res)
    if (!cookie) throw new Error('Dashboard password login returned no session cookie')
    dashboardCookieCache = cookie
    return cookie
  })()
  try { return await dashboardCookiePromise } finally { dashboardCookiePromise = null }
}""", "dashboard auth state")
        text = replace(text, """export async function dashboardAuthHeaders(options?: {
  force?: boolean
}): Promise<Record<string, string>> {
  const token = await getDashboardToken(options)
  return token ? { Authorization: `Bearer ${token}` } : {}
}""", """export async function dashboardAuthHeaders(options?: {
  force?: boolean
}): Promise<Record<string, string>> {
  if (REMOTE_PASSWORD_AUTH) {
    const cookie = await fetchDashboardCookie(options?.force === true)
    return cookie ? { Cookie: cookie } : {}
  }
  const token = await getDashboardToken(options)
  return token ? { Authorization: `Bearer ${token}` } : {}
}""", "dashboard auth headers")
        text = replace(text, "    dashboardTokenCache = ''\n    res = await doFetch(true)", "    dashboardTokenCache = ''\n    dashboardCookieCache = ''\n    res = await doFetch(true)", "dashboard retry")
    elif rel == "src/server/kanban-dashboard-proxy.ts":
        text = replace(text, """  CLAUDE_DASHBOARD_URL,
  fetchDashboardToken,""", """  CLAUDE_DASHBOARD_URL,
  dashboardFetch as authenticatedDashboardFetch,""", "kanban import")
        start, end = text.index("async function buildHeaders()"), text.index("\n}\n\nfunction dashboardUrl", text.index("async function buildHeaders()")) + 2
        text = text[:start] + """async function buildHeaders(): Promise<Record<string, string>> {
  return { 'Content-Type': 'application/json' }
}""" + text[end:]
        text = replace(text, """  const headers = await buildHeaders()
  const res = await fetch(dashboardUrl(path, params), {
    ...init,
    headers: { ...headers, ...(init.headers || {}) },
    signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
  })""", """  const url = dashboardUrl(path, params)
  const headers = await buildHeaders()
  const res = await authenticatedDashboardFetch(url, {
    ...init,
    headers: { ...headers, ...(init.headers || {}) },
    signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
  })""", "kanban fetch")
    elif rel == "src/routes/api/claude-tasks-assignees.ts":
        text = replace(text, "import { BEARER_TOKEN, CLAUDE_API, CLAUDE_DASHBOARD_URL } from '../../server/gateway-capabilities'", "import { CLAUDE_API, dashboardFetch, gatewayFetch } from '../../server/gateway-capabilities'", "assignee import")
        old = """function authHeaders(): Record<string, string> {
  return BEARER_TOKEN ? { Authorization: `Bearer ${BEARER_TOKEN}` } : {}
}

"""
        text = replace(text, old, "", "assignee bearer helper")
        text = replace(text, """    const res = await fetch(url, {
      signal: AbortSignal.timeout(2000),
      headers: authHeaders(),
    })""", """    const res = url.startsWith('http')
      ? await gatewayFetch(url, { signal: AbortSignal.timeout(2000) })
      : await dashboardFetch(url, { signal: AbortSignal.timeout(2000) })""", "assignee fetch")
        text = replace(text, "await fetchJson(`${CLAUDE_DASHBOARD_URL}/api/plugins/kanban/assignees`) ??", "await fetchJson('/api/plugins/kanban/assignees') ??", "assignee dashboard path")
    elif rel == "src/server/profiles-browser.ts":
        text = replace(text, "import YAML from 'yaml'", "import YAML from 'yaml'\nimport { dashboardFetch } from './gateway-capabilities'", "profiles dashboard import")
        token_start = text.index("function getDashboardToken(): string | undefined {")
        token_end = text.index("\n}\n\nasync function fetchDashboardProfiles", token_start) + 2
        text = text[:token_start] + text[token_end:]
        text = replace(text, """    const token = getDashboardToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    const response = await fetch(`${dashboardUrl}/api/profiles`, {
      headers,
      signal: AbortSignal.timeout(5000),
    })""", """    const response = await dashboardFetch('/api/profiles', {
      signal: AbortSignal.timeout(5000),
    })""", "profiles list dashboard fetch")
        start = text.index("export async function readProfileWithFallback(")
        end = text.index("\nexport function getActiveProfileName", start)
        replacement = """export async function readProfileWithFallback(
  name: string,
): Promise<ProfileDetail> {
  const normalized = name.trim() || 'default'
  const dashboardUrl = getDashboardUrl()

  // In split-host mode the central dashboard is authoritative. Only a remote
  // outage or a remote miss permits a local filesystem fallback.
  if (dashboardUrl) {
    try {
      const response = await dashboardFetch('/api/profiles', {
        signal: AbortSignal.timeout(5000),
      })
      if (response.ok) {
        const data = (await response.json()) as {
          profiles?: Array<{
            name: string
            model?: string
            provider?: string
            description?: string
            is_default?: boolean
          }>
        }
        const match = data.profiles?.find(
          (p) => p.name === normalized || (normalized === 'default' && p.is_default),
        )
        if (match) {
          return {
            name: match.name,
            path: match.is_default
              ? getClaudeRoot()
              : path.join(getProfilesRoot(), match.name),
            active: match.is_default === true,
            config: {
              ...(match.model ? { model: match.model } : {}),
              ...(match.provider ? { provider: match.provider } : {}),
            },
            description: match.description || '',
            systemPrompt: '',
            hasEnv: false,
          }
        }
      }
    } catch {
      // Dashboard unavailable — fall through to the local filesystem.
    }
  }

  const profilePath =
    normalized === 'default'
      ? getClaudeRoot()
      : path.join(getProfilesRoot(), validateProfileIdentifier(normalized))
  if (fs.existsSync(profilePath)) return readProfile(normalized)

  throw new Error('Profile not found')
}
"""
        text = text[:start] + replacement + text[end:]
    elif rel in ("src/components/mobile-hamburger-menu.tsx", "src/components/mobile-tab-bar.tsx"):
        is_h = "hamburger" in rel
        needle = "export const MOBILE_HAMBURGER_NAV_ITEMS = [" if is_h else "export const MOBILE_NAV_TABS: Array<TabItem> = ["
        text = replace(text, needle, "const HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'\n\n" + needle, "mobile flag")
        text = replace(text, "  {\n    id: 'playground',", "  ...(HERMESWORLD_ENABLED ? [{\n    id: 'playground',", "mobile game item")
        marker = "  },\n  {\n    id: 'terminal'," if is_h else "  },\n  {\n    id: 'files',"
        text = replace(text, marker, "  }] : []),\n  {\n    id: '" + ("terminal" if is_h else "files") + "',", "mobile game close")
    elif rel == "src/routes/__root.tsx":
        text = replace(text, "} from '@tanstack/react-router'", "  Navigate,\n} from '@tanstack/react-router'", "root Navigate import")
        text = replace(text, "import { LoginScreen } from '@/components/auth/login-screen'", "import { LoginScreen } from '@/components/auth/login-screen'\n\nconst HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'\nconst UPDATE_CENTER_ENABLED = import.meta.env.VITE_UPDATE_CENTER_ENABLED !== '0'\nconst DISABLED_GAME_PATHS = new Set(['/playground', '/hermes-world', '/world', '/reserve', '/reserve/confirm', '/early-access'])", "root flags")
        text = replace(text, "  const isGameSurfaceRoute = isHermesWorldLandingRoute || pathname === '/playground' || pathname.startsWith('/playground/')", "  const isGameSurfaceRoute = HERMESWORLD_ENABLED && (isHermesWorldLandingRoute || pathname === '/playground' || pathname.startsWith('/playground/'))\n  const redirectDisabledGame = !HERMESWORLD_ENABLED && DISABLED_GAME_PATHS.has(pathname)", "root game guard")
        text = replace(text, "{!isHermesWorldLandingRoute ? <UpdateCenterNotifier /> : null}", "{UPDATE_CENTER_ENABLED && !isHermesWorldLandingRoute ? <UpdateCenterNotifier /> : null}", "update flag")
        text = replace(text, "        <>\n          <GlobalShortcutListener />", "        <>\n          {redirectDisabledGame ? <Navigate to=\"/dashboard\" replace /> : null}\n          {!redirectDisabledGame ? <>\n          <GlobalShortcutListener />", "root redirect")
        text = replace(text, "          ) : null}\n        </>\n      ) : null", "          ) : null}\n          </> : null}\n        </>\n      ) : null", "root redirect close")
    elif rel in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
        text = replace(text, "export const Route = createFileRoute", "const HERMESWORLD_ENABLED = process.env.VITE_HERMESWORLD_ENABLED !== '0'\n\nexport const Route = createFileRoute", "game endpoint flag")
        if "GET: async ({ request }) => {" in text:
            text = replace(text, "GET: async ({ request }) => {", "GET: async ({ request }) => {\n        if (!HERMESWORLD_ENABLED) return json({ error: 'HermesWorld is disabled' }, { status: 404 })", "game GET guard")
        if "POST: async ({ request }) => {" in text:
            text = replace(text, "POST: async ({ request }) => {", "POST: async ({ request }) => {\n        if (!HERMESWORLD_ENABLED) return json({ error: 'HermesWorld is disabled' }, { status: 404 })", "game POST guard")
    return text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", type=pathlib.Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = args.workspace.resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != UPSTREAM_COMMIT:
        raise SystemExit("upstream commit fingerprint mismatch")
    changed = False
    statuses = []
    source_paths = []
    for rel, expected in FILES.items():
        path = root / rel
        actual = sha(path)
        if actual == expected:
            statuses.append(f"{rel}: source-needs-overlay")
            source_paths.append((rel, path))
        elif actual == PATCHED_FILES[rel]:
            statuses.append(f"{rel}: exact-patched")
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {rel}")
    if args.check:
        print("\n".join(statuses))
    else:
        for rel, path in source_paths:
            path.write_text(transform(rel, path.read_text()), encoding="utf-8")
            if sha(path) != PATCHED_FILES[rel]:
                raise SystemExit(f"overlay output fingerprint mismatch: {rel}")
            changed = True
        print("overlay applied" if changed else "overlay already applied")
if __name__ == "__main__":
    main()
