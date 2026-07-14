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
"src/routes/api/models.ts": "0a8a94a277b3fe654c85d11def4283c9001639d1f9a80c55dfd7534c5e6e7b4a",
"src/routes/api/sessions.ts": "209be41f615751d160af8b908bf938bed5db747fd393aab7f2a1d99e4d4cd720",
"src/routes/api/send-stream.ts": "95e182b21253fd1d7a37a2338e2df6f66761b4ded99063258a71b80a43e6f5a0",
"src/server/kanban-backend.ts": "4987b6ea35d7eaf296f1d57a7cbb4da74a08cfb20d5958c4b43267de6193b93e",
"src/routes/api/hermes-tasks.ts": "c20eb57f7d87fc444168032d78f87a0e3ceca54664463f573f9c188b3311e904",
"src/routes/api/claude-jobs.ts": "cd47fd163f669070210d0bcb1f181ae08454665ca1806704b0211bdfcfdaa803",
"src/routes/api/conductor-spawn.ts": "cac908c034a5dc21a88330838eb7d84f8ce77033012fe4df0606abb87acc2271",
}
PATCHED_FILES = {
"src/server/gateway-capabilities.ts": "8d37e5895ff40899242200d24f88e2e2e17ea0651f8575581bbc1c2a829c91c7",
"src/server/kanban-dashboard-proxy.ts": "ba981a50148a0d75b6a02d873646fd0371e116a266a907b56b4c5b4eb10ac6f7",
"src/routes/api/claude-tasks-assignees.ts": "001e870c6db2294ad73315de09b4a8f5337061a9bb179af63f01489d148fa0e9",
"src/server/profiles-browser.ts": "e397c6712bc265a21cf8046eff778557d7f9d4a1c2cef529bd863edb8e1915e5",
"src/components/mobile-hamburger-menu.tsx": "9f6bd64d1b5bdf6e8913c2d87e870be5767a8ec606ecf777740d6d4602f15deb",
"src/components/mobile-tab-bar.tsx": "8e699f2c2fe547001a3d0c42bcaf0c9b737bb681fe2817d689865d6110b1c08c",
"src/routes/__root.tsx": "c61251c233f325a6a9871bc153b89e0aa91baac2cd1c4aa03f54422f366907fc",
"src/routes/api/playground-admin.ts": "c99380cd813bad4e7d210e1654211bb571751cbb9de553cdd00f501febf13a27",
"src/routes/api/playground-npc.ts": "652135b9afb2ae8cabcf0ae4d4f9d993cee1f335a72482dbd07bba51914098f7",
"src/routes/api/models.ts": "68d1c6f451801c4943394faf13c21e9cae48bfdc5056d011ead05ca387beeb1e",
"src/routes/api/sessions.ts": "751be9381f02aa2f0a0d8a39639aa81ca12f4864d8749eb455782a270404a577",
"src/routes/api/send-stream.ts": "d61df1f062067cf9991ce33cf6d754c041e44148355423af28dc68d343c85f37",
"src/server/kanban-backend.ts": "a52f43a7082bf642f778347819b51f213dccf7215bd892d3cb87c5a92c9d638e",
"src/routes/api/hermes-tasks.ts": "901c10488536ff4000e1d45dc773f9fd5328ae7db99ce18d53782f0cd47dd591",
"src/routes/api/claude-jobs.ts": "3c0ba0116b4e87252580058571b822d47590b64a3b2e699b6afd16329bc49321",
"src/routes/api/conductor-spawn.ts": "23da2c21a6fb4398c8801f07222488d6c2f64b5b21bbb2857344621f5e4b5956",
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
        text = replace(text, "const _initialOverrides = readOverrides()", "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'\nconst _initialOverrides = CENTRAL_ONLY ? {} : readOverrides()", "central-only overrides")
        text = replace(text, """export function setGatewayUrl(input: string | null | undefined): string {
  const normalized""", """export function setGatewayUrl(input: string | null | undefined): string {
  if (CENTRAL_ONLY) throw new Error('Gateway URL is environment-managed in central-only mode')
  const normalized""", "central-only gateway setter")
        text = replace(text, """export function setDashboardUrl(input: string | null | undefined): string {
  const normalized""", """export function setDashboardUrl(input: string | null | undefined): string {
  if (CENTRAL_ONLY) throw new Error('Dashboard URL is environment-managed in central-only mode')
  const normalized""", "central-only dashboard setter")
        text = replace(text, "  const overrides = readOverrides()\n  const source = overrides.claudeApiUrl", "  const overrides = CENTRAL_ONLY ? {} : readOverrides()\n  const source = overrides.claudeApiUrl", "central-only resolved source")
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
        text = replace(text, "import YAML from 'yaml'", "import YAML from 'yaml'\nimport { dashboardFetch } from './gateway-capabilities'\n\nconst CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'", "profiles dashboard import")
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
        text = replace(text, """  const dashboardResult = await fetchDashboardProfiles()
  if (dashboardResult) return dashboardResult

  // Fall back to filesystem (colocated deployment)""", """  const dashboardResult = await fetchDashboardProfiles()
  if (dashboardResult) return dashboardResult
  if (CENTRAL_ONLY) throw new Error('Central profile source unavailable')

  // Fall back to filesystem (colocated deployment)""", "profiles central-only list")
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

  if (CENTRAL_ONLY) throw new Error('Central profile not found or unavailable')

  const profilePath =
    normalized === 'default'
      ? getClaudeRoot()
      : path.join(getProfilesRoot(), validateProfileIdentifier(normalized))
  if (fs.existsSync(profilePath)) return readProfile(normalized)

  throw new Error('Profile not found')
}
"""
        text = text[:start] + replacement + text[end:]
    elif rel == "src/routes/api/models.ts":
        text = replace(text, """        try {
          // Primary: read user-configured models from ~/.hermes/models.json""", """        try {
          if (process.env.HERMES_CENTRAL_ONLY === '1') {
            const models = await fetchClaudeModels()
            const configuredProviders = Array.from(
              new Set(
                models
                  .map((model) =>
                    typeof model.provider === 'string' ? model.provider : '',
                  )
                  .filter(Boolean),
              ),
            )
            return json({
              ok: true,
              object: 'list',
              data: models,
              models,
              configuredProviders,
              source: 'hermes-agent',
              ...readStreamTimeouts(),
            })
          }

          // Primary: read user-configured models from ~/.hermes/models.json""", "central-only models")
    elif rel == "src/routes/api/sessions.ts":
        text = replace(text, """} from '../../server/local-session-store'

export const Route""", """} from '../../server/local-session-store'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

export const Route""", "sessions central-only flag")
        text = replace(text, """          // Merge local portable sessions (Ollama, Atomic Chat, etc.)
          const localSessions = listLocalSessions()""", """          // Portable sessions are never an authority in central-only mode.
          const localSessions = CENTRAL_ONLY ? [] : listLocalSessions()""", "sessions local list")
        text = replace(text, """        if (!capabilities.sessions) {
          const friendlyId = randomUUID()""", """        if (!capabilities.sessions) {
          if (CENTRAL_ONLY) {
            return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503 })
          }
          const friendlyId = randomUUID()""", "sessions unavailable")
        text = replace(text, """          if (capabilities.dashboard.available && !capabilities.enhancedChat) {
            return json({""", """          if (capabilities.dashboard.available && !capabilities.enhancedChat) {
            if (CENTRAL_ONLY) {
              return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503 })
            }
            return json({""", "sessions unpersisted")
        text = replace(text, "          if (localSession) {", "          if (!CENTRAL_ONLY && localSession) {", "sessions local update")
        text = replace(text, "        if (getLocalSession(sessionKey)) {", "        if (!CENTRAL_ONLY && getLocalSession(sessionKey)) {", "sessions local delete")
    elif rel == "src/routes/api/send-stream.ts":
        text = replace(text, """const SESSION_BOOTSTRAP_KEYS = new Set(['main', 'new'])

function readString""", """const SESSION_BOOTSTRAP_KEYS = new Set(['main', 'new'])
const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

function readString""", "send stream central-only flag")
        text = replace(text, """        if (chatMode === 'portable' && sessionKey === 'new') {""", """        if (CENTRAL_ONLY && chatMode === 'portable') {
          return new Response(JSON.stringify({ ok: false, error: 'Central session stream unavailable' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        if (chatMode === 'portable' && sessionKey === 'new') {""", "send stream portable fallback")
    elif rel == "src/server/kanban-backend.ts":
        text = replace(text, """export type KanbanBackendId = 'local' | 'claude' | 'hermes-proxy'""", """const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

export type KanbanBackendId = 'local' | 'claude' | 'hermes-proxy'""", "kanban central-only flag")
        text = replace(text, """export function resolveKanbanBackend(): KanbanBackend {
  const preference""", """export function resolveKanbanBackend(): KanbanBackend {
  if (CENTRAL_ONLY) {
    if (getCapabilities().kanban) return dashboardProxyBackend
    throw new Error('Central Kanban unavailable in central-only mode')
  }
  const preference""", "kanban central-only selection")
    elif rel == "src/routes/api/hermes-tasks.ts":
        text = replace(text, """import type { TaskColumn, TaskPriority } from '../../server/tasks-store'

function jsonResponse""", """import type { TaskColumn, TaskPriority } from '../../server/tasks-store'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

function jsonResponse""", "tasks central-only flag")
        text = replace(text, """        const url = new URL(request.url)
        const tasks = listTasks({""", """        if (CENTRAL_ONLY) return jsonResponse({ error: 'Local task store disabled in central-only mode' }, 503)

        const url = new URL(request.url)
        const tasks = listTasks({""", "tasks central-only read")
        text = replace(text, """        try {
          const body = (await request.json()) as Record<string, unknown>""", """        if (CENTRAL_ONLY) return jsonResponse({ error: 'Local task store disabled in central-only mode' }, 503)

        try {
          const body = (await request.json()) as Record<string, unknown>""", "tasks central-only write")
    elif rel == "src/routes/api/claude-jobs.ts":
        text = replace(text, """import { createCapabilityUnavailablePayload } from '@/lib/feature-gates'

function authHeaders""", """import { createCapabilityUnavailablePayload } from '@/lib/feature-gates'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

function authHeaders""", "jobs central-only flag")
        text = replace(text, "const aggregateProfiles = url.searchParams.get('profiles') !== 'active'", "const aggregateProfiles = !CENTRAL_ONLY && url.searchParams.get('profiles') !== 'active'", "jobs local aggregation")
        text = replace(text, """        if (!capabilities.jobs) {
          return new Response(""", """        if (!capabilities.jobs) {
          if (CENTRAL_ONLY) {
            return new Response(JSON.stringify({ ok: false, error: 'Central jobs unavailable' }), {
              status: 503,
              headers: { 'Content-Type': 'application/json' },
            })
          }
          return new Response(""", "jobs unavailable")
        text = replace(text, """        if (profile) {
          try {""", """        if (profile) {
          if (CENTRAL_ONLY) {
            return new Response(JSON.stringify({ ok: false, error: 'Local profile jobs disabled in central-only mode' }), {
              status: 503,
              headers: { 'Content-Type': 'application/json' },
            })
          }
          try {""", "jobs local write")
    elif rel == "src/routes/api/conductor-spawn.ts":
        text = replace(text, """let cachedSkill: string | null = null

export const NATIVE_CONDUCTOR_MODE_NOTE""", """let cachedSkill: string | null = null
const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

export const NATIVE_CONDUCTOR_MODE_NOTE""", "conductor central-only flag")
        text = replace(text, "const nativeMission = getSwarmMission(missionId)", "const nativeMission = CENTRAL_ONLY ? null : getSwarmMission(missionId)", "conductor local mission read")
        text = replace(text, """        if (!capabilities.dashboard.available || !capabilities.conductor) {
          return json({ ok: false, error: 'Conductor mission not found in native swarm store and dashboard Conductor API is unavailable' }, { status: 404 })
        }""", """        if (!capabilities.dashboard.available || !capabilities.conductor) {
          const error = CENTRAL_ONLY
            ? 'Central Conductor unavailable in central-only mode'
            : 'Conductor mission not found in native swarm store and dashboard Conductor API is unavailable'
          return json({ ok: false, error }, { status: CENTRAL_ONLY ? 503 : 404 })
        }""", "conductor unavailable read")
        text = replace(text, """          if (!capabilities.dashboard.available || !capabilities.conductor) {
            const native = createNativeConductorMission({""", """          if (!capabilities.dashboard.available || !capabilities.conductor) {
            if (CENTRAL_ONLY) {
              return json({ ok: false, error: 'Central Conductor unavailable in central-only mode' }, { status: 503 })
            }
            const native = createNativeConductorMission({""", "conductor local fallback")
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
        text = replace(text, "export const Route = createFileRoute", "const HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'\n\nexport const Route = createFileRoute", "game endpoint flag")
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
