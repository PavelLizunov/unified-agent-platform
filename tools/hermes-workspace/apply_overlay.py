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
"src/server/claude-api.ts": "303ef03606c25cccef8e02e947838988c5b28de62d5277ce6e92c9a45545796d",  # gitleaks:allow -- pinned source SHA-256
"src/server/kanban-backend.ts": "4987b6ea35d7eaf296f1d57a7cbb4da74a08cfb20d5958c4b43267de6193b93e",
"src/routes/api/hermes-tasks.ts": "c20eb57f7d87fc444168032d78f87a0e3ceca54664463f573f9c188b3311e904",
"src/routes/api/claude-jobs.ts": "cd47fd163f669070210d0bcb1f181ae08454665ca1806704b0211bdfcfdaa803",
"src/routes/api/conductor-spawn.ts": "cac908c034a5dc21a88330838eb7d84f8ce77033012fe4df0606abb87acc2271",
"src/screens/chat/chat-screen.tsx": "ba1175ef3d637f2114b1f8ad19e5f299a848d60f607ec3b3166d73f4391d18e5",
"src/screens/dashboard/dashboard-screen.tsx": "3e562694308922351aee07bc5bbb7908e752d3c9a6211e896e90dec284bcc7c4",
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
"src/routes/api/sessions.ts": "f1fa702405ce65cbf937a8883c5f7f13bc19c681b5e7fae10cdf15122328267c",
"src/routes/api/send-stream.ts": "6127483b81d22ab3d91fa5b318e4e4423dfb41619e82364cfe3e21446252828b",
"src/server/claude-api.ts": "d984cf1500364c7313bda428a97f4353bab3a24263f9cb199ca40f490672374a",  # gitleaks:allow -- pinned patched SHA-256
"src/server/kanban-backend.ts": "a52f43a7082bf642f778347819b51f213dccf7215bd892d3cb87c5a92c9d638e",
"src/routes/api/hermes-tasks.ts": "901c10488536ff4000e1d45dc773f9fd5328ae7db99ce18d53782f0cd47dd591",
"src/routes/api/claude-jobs.ts": "3c0ba0116b4e87252580058571b822d47590b64a3b2e699b6afd16329bc49321",
"src/routes/api/conductor-spawn.ts": "23da2c21a6fb4398c8801f07222488d6c2f64b5b21bbb2857344621f5e4b5956",
"src/screens/chat/chat-screen.tsx": "d20725179b11de51faebd0f35a54b6716d0343d094c87e65e30da5680469c9da",
"src/screens/dashboard/dashboard-screen.tsx": "492a3b47faf03a319024c1f6f351c8d7a664505d50b85653a0de4b5ec869afc1",
}
LEGACY_FILES = {
"src/server/gateway-capabilities.ts": "d599c442441be9763e0d6d3c4fb999783e326ad61ea7261064d79337cac840e5",
"src/server/profiles-browser.ts": "e5b84d509ad2960f2a0a57d785d3602110fdaf6e4dffa0da4211858d74d86385",
}
PREVIOUS_PATCHED_FILES = {
"src/routes/api/sessions.ts": "751be9381f02aa2f0a0d8a39639aa81ca12f4864d8749eb455782a270404a577",
"src/routes/api/send-stream.ts": "8cdcb90478dbd7c41839e6f4229b83bf5e5c5526f06528b2fdbd82700c3b54de",  # gitleaks:allow -- pinned previous patched SHA-256
"src/server/claude-api.ts": "15edfd328c3757fba773af30329959bf345347daab3a93d6abdb7e533ce6dc92",  # gitleaks:allow -- pinned previous patched SHA-256
}
ADDED_FILES = {
    "src/routes/api/missions.ts": "src/routes/api/missions.ts",
    "src/screens/dashboard/components/mission-overview-card.tsx": "src/screens/dashboard/components/mission-overview-card.tsx",
}
LEGACY_ADDED_FILES = {
    "src/routes/api/missions.ts": "e92e59ee7556741adac03a0850b1166234e582ba7cdaaa16379a4347797c84ac",
    "src/screens/dashboard/components/mission-overview-card.tsx": "7ab5ceff84f8b8a6eefd8acf694dfd27047b57ac25d73956707fbf2ea9088c45",
}
PREVIOUS_ADDED_FILES = {
    "src/routes/api/missions.ts": "082ffe7f4d100d8a5a64fbde40893cfba1f98a1774c914acb2495ce1a857a243",
    "src/screens/dashboard/components/mission-overview-card.tsx": "990eb901032d2f2784eece487bc462b02b0672c1feb9f0c1bef403e1019e6b5b",
}
ASSET_ROOT = pathlib.Path(__file__).with_name("files")
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
            return json({""", """          if (!CENTRAL_ONLY && capabilities.dashboard.available && !capabilities.enhancedChat) {
            return json({""", "sessions unpersisted")
        text = replace(text, "          if (localSession) {", "          if (!CENTRAL_ONLY && localSession) {", "sessions local update")
        text = replace(text, "        if (getLocalSession(sessionKey)) {", "        if (!CENTRAL_ONLY && getLocalSession(sessionKey)) {", "sessions local delete")
    elif rel == "src/screens/chat/chat-screen.tsx":
        text = replace(text, """        if (!isPortableMode) {
          void createSessionForMessage(threadId).catch((err: unknown) => {
            if (import.meta.env.DEV) {
              console.warn('[chat] failed to register new thread', err)
            }
            void queryClient.invalidateQueries({
              queryKey: chatQueryKeys.sessions,
            })
          })
        }

        sendMessage(
          threadId,
          threadId,
          trimmedBody,
          attachmentPayload,
          fastMode,
          true,
          typeof optimisticMessage.clientId === 'string'
            ? optimisticMessage.clientId
            : '',
        )
        // In portable mode, navigate to /chat/main instead of UUID
        if (!embedded) {
          navigate({
            to: '/chat/$sessionKey',
            params: { sessionKey: threadId },
            replace: true,
          })
        }
        return""", """        const optimisticClientId =
          typeof optimisticMessage.clientId === 'string'
            ? optimisticMessage.clientId
            : ''

        if (!isPortableMode) {
          void createSessionForMessage(threadId)
            .then(({ sessionKey, friendlyId }) => {
              if (sessionKey !== threadId || friendlyId !== threadId) {
                throw new Error('Central session identity mismatch')
              }
              sendMessage(
                sessionKey,
                friendlyId,
                trimmedBody,
                attachmentPayload,
                fastMode,
                true,
                optimisticClientId,
              )
              if (!embedded) {
                navigate({
                  to: '/chat/$sessionKey',
                  params: { sessionKey: friendlyId },
                  replace: true,
                })
              }
            })
            .catch((err: unknown) => {
              const messageText = err instanceof Error ? err.message : String(err)
              setError(messageText)
              setPendingGeneration(false)
              setSending(false)
              setWaitingForResponse(false)
              void queryClient.invalidateQueries({
                queryKey: chatQueryKeys.sessions,
              })
            })
          return
        }

        sendMessage(
          threadId,
          threadId,
          trimmedBody,
          attachmentPayload,
          fastMode,
          true,
          optimisticClientId,
        )
        if (!embedded) {
          navigate({
            to: '/chat/$sessionKey',
            params: { sessionKey: threadId },
            replace: true,
          })
        }
        return""", "central session before first message")
    elif rel == "src/routes/api/send-stream.ts":
        text = replace(text, """const SESSION_BOOTSTRAP_KEYS = new Set(['main', 'new'])

function readString""", """const SESSION_BOOTSTRAP_KEYS = new Set(['main', 'new'])
const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'

function readString""", "send stream central-only flag")
        text = replace(text, """        if (chatMode === 'portable' && sessionKey === 'new') {""", """        if (CENTRAL_ONLY) {
          chatMode = 'enhanced-claude'
        }
        if (chatMode === 'portable' && sessionKey === 'new') {""", "send stream portable fallback")
        text = replace(text, """        const message = String(body.message ?? '')
        const thinking =""", """        const message = String(body.message ?? '')
        const sourceMessageId =
          typeof body.idempotencyKey === 'string' ? body.idempotencyKey.trim() : ''
        if (CENTRAL_ONLY && !sourceMessageId) {
          return new Response(
            JSON.stringify({ ok: false, error: 'message identity required' }),
            { status: 400, headers: { 'Content-Type': 'application/json' } },
          )
        }
        const thinking =""", "ordinary goal identity")
        text = replace(text, """                  message: scopedMessage,
                  model:""", """                  message: CENTRAL_ONLY ? message : scopedMessage,
                  model:""", "ordinary goal text")
        return replace(text, """                  attachments: attachments || undefined,
                },""", """                  attachments: attachments || undefined,
                  source_message_id: CENTRAL_ONLY ? sourceMessageId : undefined,
                },""", "ordinary goal forwarding")
    elif rel == "src/server/claude-api.ts":
        text = replace(text, """} from './claude-dashboard-api'

const _authHeaders""", """} from './claude-dashboard-api'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'
const _authHeaders""", "central-only session source")
        text = replace(text, """}): Promise<ClaudeSession> {
  if (getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", """}): Promise<ClaudeSession> {
  if (!CENTRAL_ONLY && getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", "central-only session creation")
        return replace(text, """    attachments?: Array<Record<string, unknown>>
  },""", """    attachments?: Array<Record<string, unknown>>
    source_message_id?: string
  },""", "ordinary goal request type")
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
    elif rel == "src/screens/dashboard/dashboard-screen.tsx":
        text = replace(text, "import { LogsTailCard } from './components/logs-tail-card'", "import { LogsTailCard } from './components/logs-tail-card'\nimport { MissionOverviewCard } from './components/mission-overview-card'", "mission card import")
        text = replace(text, """      </div>

      {/* ── Attention marquee ──""", """      </div>

      <MissionOverviewCard />

      {/* ── Attention marquee ──""", "mission card placement")
    return text

def upgrade_legacy(rel, text):
    if rel == "src/server/gateway-capabilities.ts":
        text = replace(text, "const _initialOverrides = readOverrides()", "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'\nconst _initialOverrides = CENTRAL_ONLY ? {} : readOverrides()", "legacy central-only overrides")
        text = replace(text, """export function setGatewayUrl(input: string | null | undefined): string {
  const normalized""", """export function setGatewayUrl(input: string | null | undefined): string {
  if (CENTRAL_ONLY) throw new Error('Gateway URL is environment-managed in central-only mode')
  const normalized""", "legacy central-only gateway setter")
        text = replace(text, """export function setDashboardUrl(input: string | null | undefined): string {
  const normalized""", """export function setDashboardUrl(input: string | null | undefined): string {
  if (CENTRAL_ONLY) throw new Error('Dashboard URL is environment-managed in central-only mode')
  const normalized""", "legacy central-only dashboard setter")
        return replace(text, "  const overrides = readOverrides()\n  const source = overrides.claudeApiUrl", "  const overrides = CENTRAL_ONLY ? {} : readOverrides()\n  const source = overrides.claudeApiUrl", "legacy central-only resolved source")
    if rel == "src/server/profiles-browser.ts":
        text = replace(text, "import { dashboardFetch } from './gateway-capabilities'", "import { dashboardFetch } from './gateway-capabilities'\n\nconst CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'", "legacy profiles central-only flag")
        text = replace(text, """  const dashboardResult = await fetchDashboardProfiles()
  if (dashboardResult) return dashboardResult

  // Fall back to filesystem (colocated deployment)""", """  const dashboardResult = await fetchDashboardProfiles()
  if (dashboardResult) return dashboardResult
  if (CENTRAL_ONLY) throw new Error('Central profile source unavailable')

  // Fall back to filesystem (colocated deployment)""", "legacy profiles central-only list")
        return replace(text, """  const profilePath =
    normalized === 'default'""", """  if (CENTRAL_ONLY) throw new Error('Central profile not found or unavailable')

  const profilePath =
    normalized === 'default'""", "legacy profiles central-only read")
    raise SystemExit(f"no legacy upgrade for {rel}")

def upgrade_previous(rel, text):
    if rel == "src/routes/api/sessions.ts":
        return replace(text, """          if (capabilities.dashboard.available && !capabilities.enhancedChat) {
            if (CENTRAL_ONLY) {
              return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503 })
            }
            return json({""", """          if (!CENTRAL_ONLY && capabilities.dashboard.available && !capabilities.enhancedChat) {
            return json({""", "central session creation upgrade")
    if rel == "src/routes/api/send-stream.ts":
        return replace(text, """        if (CENTRAL_ONLY && chatMode === 'portable') {
          return new Response(JSON.stringify({ ok: false, error: 'Central session stream unavailable' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }""", """        if (CENTRAL_ONLY) {
          chatMode = 'enhanced-claude'
        }""", "central-only stream upgrade")
    if rel == "src/server/claude-api.ts":
        text = replace(text, """} from './claude-dashboard-api'

const _authHeaders""", """} from './claude-dashboard-api'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'
const _authHeaders""", "central-only session source upgrade")
        return replace(text, """}): Promise<ClaudeSession> {
  if (getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", """}): Promise<ClaudeSession> {
  if (!CENTRAL_ONLY && getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", "central-only session creation upgrade")
    raise SystemExit(f"no previous patched upgrade for {rel}")

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
            source_paths.append((rel, path, False))
        elif actual == PATCHED_FILES[rel]:
            statuses.append(f"{rel}: exact-patched")
        elif actual == LEGACY_FILES.get(rel):
            statuses.append(f"{rel}: legacy-needs-overlay")
            source_paths.append((rel, path, True))
        elif actual == PREVIOUS_PATCHED_FILES.get(rel):
            statuses.append(f"{rel}: previous-needs-overlay")
            source_paths.append((rel, path, "previous"))
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {rel}")
    added_paths = []
    for rel, asset_rel in ADDED_FILES.items():
        path = root / rel
        asset = ASSET_ROOT / asset_rel
        if not path.exists():
            statuses.append(f"{rel}: source-needs-overlay")
            added_paths.append((path, asset))
        elif sha(path) == sha(asset):
            statuses.append(f"{rel}: exact-patched")
        elif sha(path) == PREVIOUS_ADDED_FILES.get(rel):
            statuses.append(f"{rel}: previous-needs-overlay")
            added_paths.append((path, asset))
        elif sha(path) == LEGACY_ADDED_FILES.get(rel):
            statuses.append(f"{rel}: legacy-needs-overlay")
            added_paths.append((path, asset))
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {rel}")
    if args.check:
        print("\n".join(statuses))
    else:
        for rel, path, legacy in source_paths:
            transform_file = (
                upgrade_previous if legacy == "previous"
                else upgrade_legacy if legacy
                else transform
            )
            path.write_text(transform_file(rel, path.read_text()), encoding="utf-8")
            if sha(path) != PATCHED_FILES[rel]:
                raise SystemExit(f"overlay output fingerprint mismatch: {rel}")
            changed = True
        for path, asset in added_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(asset.read_bytes())
            changed = True
        print("overlay applied" if changed else "overlay already applied")
if __name__ == "__main__":
    main()
