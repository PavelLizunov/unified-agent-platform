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
"src/components/settings/settings-sidebar.tsx": "f6d986201b242e9adbfae4675c6224aa2ee56bb8306c12a0fb0bfe2d68f4c1a2",
"src/routes/settings/index.tsx": "ba25520be3c3e53b760dd40e77c2fb84d67098a029e274c5c32882244fb540a9",
"src/screens/chat/components/chat-sidebar.tsx": "a5bd23e6c678c620ba5251cd94b26facba6d8c9f124dbff6c98efc860e49707c",
"src/components/command-palette.tsx": "29a9c16810544572dea66ddef084c9f872df378176f70a173ea5d36301fc8ed4",
"src/screens/chat/components/message-item.tsx": "375d24774808f9943cf03972d9d7f0254473271dbfe8fe4e4d105b7b61cb5c63",
"src/screens/chat/components/message-actions-bar.tsx": "14f6e0c7135a1035718be02c5f296f9934996e21d473586f24897848784c4054",
}
PATCHED_FILES = {
"src/server/gateway-capabilities.ts": "8d37e5895ff40899242200d24f88e2e2e17ea0651f8575581bbc1c2a829c91c7",
"src/server/kanban-dashboard-proxy.ts": "ba981a50148a0d75b6a02d873646fd0371e116a266a907b56b4c5b4eb10ac6f7",
"src/routes/api/claude-tasks-assignees.ts": "001e870c6db2294ad73315de09b4a8f5337061a9bb179af63f01489d148fa0e9",
"src/server/profiles-browser.ts": "e397c6712bc265a21cf8046eff778557d7f9d4a1c2cef529bd863edb8e1915e5",
"src/components/mobile-hamburger-menu.tsx": "97005e234d8e98297908ee4aef2e4141fb731ee1406e3a79cb748d2242e9e970",
"src/components/mobile-tab-bar.tsx": "f0494c1497085d36c6d59d599117f2909eeb2638d5bd6d34ae6e525619de6fa0",
"src/routes/__root.tsx": "cdb09287285105e67d986459b5b09c256d6397a8b33686fa9ffd77995355e3f0",
"src/routes/api/playground-admin.ts": "b83ced3b20dabf4b0ba7604f28b326ab25202cf5efc44060d7b141e8d7544f06",
"src/routes/api/playground-npc.ts": "7d626539973696cda605222a3408c83bcbdfcbbd32763be6936cebf1ab8ad5f7",
"src/routes/api/models.ts": "68d1c6f451801c4943394faf13c21e9cae48bfdc5056d011ead05ca387beeb1e",
"src/routes/api/sessions.ts": "559e5731c69f7f8b2d0214ae98555738ca0ba968c10b0df4cbc767e275dca277",
"src/routes/api/send-stream.ts": "75368d06701cff843f51f5fcb58163889602fad228c0bed645e3d3630c9fce62",
"src/server/claude-api.ts": "21b29443860152f497399cdd8a11c22835b1d8b956b29d0ff543818569b08342",  # gitleaks:allow -- pinned patched SHA-256
"src/server/kanban-backend.ts": "a52f43a7082bf642f778347819b51f213dccf7215bd892d3cb87c5a92c9d638e",
"src/routes/api/hermes-tasks.ts": "901c10488536ff4000e1d45dc773f9fd5328ae7db99ce18d53782f0cd47dd591",
"src/routes/api/claude-jobs.ts": "3c0ba0116b4e87252580058571b822d47590b64a3b2e699b6afd16329bc49321",
"src/routes/api/conductor-spawn.ts": "23da2c21a6fb4398c8801f07222488d6c2f64b5b21bbb2857344621f5e4b5956",
"src/screens/chat/chat-screen.tsx": "5ae01227fc3e2ead75f1c03f0eb9e075e74adbd2edf72ee8d20abfac7df7b8d4",
"src/screens/dashboard/dashboard-screen.tsx": "492a3b47faf03a319024c1f6f351c8d7a664505d50b85653a0de4b5ec869afc1",
"src/components/settings/settings-sidebar.tsx": "4e8e540d7b5e1a2dd42847249a5431f8372a01fc2d847ae9c962dce98e85300d",
"src/routes/settings/index.tsx": "3f4ccf742d4cb98adabc563c555cd2fee6b7f42d736b8cd19aa2b57b9712f87b",
"src/screens/chat/components/chat-sidebar.tsx": "321334173ba996d7b77819d6b84ec2d2488657ab0cb58c4b5091109314a96feb",
"src/components/command-palette.tsx": "a7c343e6a39e1e9e623107626512a68b66e4ac73c577917ac5164be24020a2ab",
"src/screens/chat/components/message-item.tsx": "3e53d0e104732c7da5b949559cde9e6c3a0c3a97434b62c825f875200a6fcfdf",
"src/screens/chat/components/message-actions-bar.tsx": "2691dee85e70727ba0d7124ab71f254560a3ab98ad960828f49cf1d8d0eab58b",
}
LEGACY_FILES = {
"src/server/gateway-capabilities.ts": "d599c442441be9763e0d6d3c4fb999783e326ad61ea7261064d79337cac840e5",
"src/server/profiles-browser.ts": "e5b84d509ad2960f2a0a57d785d3602110fdaf6e4dffa0da4211858d74d86385",
}
PREVIOUS_PATCHED_FILES = {
"src/routes/api/sessions.ts": (
    "751be9381f02aa2f0a0d8a39639aa81ca12f4864d8749eb455782a270404a577",
    "75f30477f71b088646364aac40ed8d6654da5f98d7f429dd714546c69364e5ce",
    "f1fa702405ce65cbf937a8883c5f7f13bc19c681b5e7fae10cdf15122328267c",
),
"src/routes/api/send-stream.ts": (
    "ec312e605aadce46748087c392c9a414ff228a5f16c65b2a80d6a71cd40466e2",
    "6127483b81d22ab3d91fa5b318e4e4423dfb41619e82364cfe3e21446252828b",
    "8cdcb90478dbd7c41839e6f4229b83bf5e5c5526f06528b2fdbd82700c3b54de",  # gitleaks:allow -- pinned previous patched SHA-256
),
"src/server/claude-api.ts": (
    "039dc37395d4255712403d259d3ee7a2254506e71bcfd3e77548e527af100942",  # gitleaks:allow -- pinned previous patched SHA-256
    "d984cf1500364c7313bda428a97f4353bab3a24263f9cb199ca40f490672374a",  # gitleaks:allow -- pinned previous patched SHA-256
    "15edfd328c3757fba773af30329959bf345347daab3a93d6abdb7e533ce6dc92",  # gitleaks:allow -- pinned previous patched SHA-256
    "ef12ed9cc4d760e809b4ff9339e55a235674dae43ce0fa4a20d9e41003621abf",  # gitleaks:allow -- pinned previous patched SHA-256
),
"src/screens/chat/chat-screen.tsx": (
    "d20725179b11de51faebd0f35a54b6716d0343d094c87e65e30da5680469c9da",
    "7b9e6a3bb701d43b25f2c766296c66ba70c90469ea39ff607886cc471098cf77",
),
"src/components/mobile-hamburger-menu.tsx": (
    "9f6bd64d1b5bdf6e8913c2d87e870be5767a8ec606ecf777740d6d4602f15deb",
),
"src/components/mobile-tab-bar.tsx": (
    "8e699f2c2fe547001a3d0c42bcaf0c9b737bb681fe2817d689865d6110b1c08c",
),
"src/routes/__root.tsx": (
    "c61251c233f325a6a9871bc153b89e0aa91baac2cd1c4aa03f54422f366907fc",
),
"src/routes/api/playground-admin.ts": (
    "c99380cd813bad4e7d210e1654211bb571751cbb9de553cdd00f501febf13a27",
),
"src/routes/api/playground-npc.ts": (
    "652135b9afb2ae8cabcf0ae4d4f9d993cee1f335a72482dbd07bba51914098f7",
),
}
ADDED_FILES = {
    "src/routes/api/missions.ts": "src/routes/api/missions.ts",
    "src/routes/api/mission-projects.ts": "src/routes/api/mission-projects.ts",
    "src/routes/api/project-onboarding.ts": "src/routes/api/project-onboarding.ts",
    "src/components/settings/project-permissions.tsx": "src/components/settings/project-permissions.tsx",
    "src/screens/dashboard/components/mission-overview-card.tsx": "src/screens/dashboard/components/mission-overview-card.tsx",
}
LEGACY_ADDED_FILES = {
    "src/routes/api/missions.ts": "e92e59ee7556741adac03a0850b1166234e582ba7cdaaa16379a4347797c84ac",
    "src/screens/dashboard/components/mission-overview-card.tsx": "7ab5ceff84f8b8a6eefd8acf694dfd27047b57ac25d73956707fbf2ea9088c45",
}
PREVIOUS_ADDED_FILES = {
    "src/routes/api/project-onboarding.ts": (
        "d727dfa55ac2eb266bff72cb87ea8d4c4c5b3482447fcf5fc14cb2a519de2977",
    ),
    "src/routes/api/mission-projects.ts": (
        "9e68a9e8e704cdccb39061e173e3c5ae7c841f450906b08787fcb1ab6dc01ce1",
        "e24378c6bd13f6bd4af0da76a7353b192e1c5ebcfb6aa6feb294ef7dea7a053b",
    ),
    "src/components/settings/project-permissions.tsx": (
        "0fdbaf45acdadcad6a6657e33aea1f1adc63804fc5f5e45714ba3b47d010bd74",
        "ffb920cb09279eabc136e91131771b26df8d0b47636b11784ae2657aea4ca093",
        "c9399af7536897389786c80b2710d01ed4670d4683fd62268b5255a090296877",
        "22b99cd0f61079d631d821b45817a37d35fe474166269408b7bc417b72f10f9a",
        "1d368904c3ee2fababb105b42cfa0539666bf7ddbe5580592c777d568f0194a0",
    ),
    "src/routes/api/missions.ts": (
        "082ffe7f4d100d8a5a64fbde40893cfba1f98a1774c914acb2495ce1a857a243",
        "45d6f3fb04da76e955147faa59b5295637da239c2727cee059b3ba81b3dd39a9",
    ),
    "src/screens/dashboard/components/mission-overview-card.tsx": (
        "990eb901032d2f2784eece487bc462b02b0672c1feb9f0c1bef403e1019e6b5b",
        "8fc9a10f19a40df929f57695e3efaf44c2ae1f8fdd19df80212f7161d195be89",
        "486df3f1451ce7cbc4e80dbce70dd3105d39b78b64b5c61d2a2a6e91fd0b532d",
        "7b244d5739f0fe30f85470e90362c5f2e2ee8dd4bc8fe140ed0aea0cee6b82fa",
        "5b03769fc1be0c253168ffe9e4ac5a1de062489d99efdb65a9e3a3b3fa9ec69c",
        "c3293795a4ff3883553de2f47e118d85c584851f9e87f0888358a79f86245c75",
        "22a1f4189b2b359fe53e920c702dfbb6fe637d92085fae5a54905f395958e71f",
        "3b0fe465c716052bc8b3c094d5c3d8a28613a9bf7a2ab2e8e103aa186a46398b",
        "f241d05b4f206a62dee6607e84f9cec4b671633a61e078ccd0e68607be1d054d",
        "27d9d9e5d1dbe6849294c224767fdd02e0f1c1558f97011b68f7073e424c21ef",
        "562e8d6f5a3d742951c0580fb6ad0d278489b2c290dc1a33516ce4fa552a8ea2",
        "bea3db0ee7055a166e88b6ae161083f59b1a443e3c156985f886d4fe5b313e03",
    ),
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
        text = replace(text, """          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >

          const requestedLabel =""", """          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >
          const setupCookie = (request.headers.get('cookie') || '')
            .split(';')
            .map((part) => part.trim())
            .find((part) => part.startsWith('uap_project_setup='))
          const setupProjectId = setupCookie
            ? decodeURIComponent(setupCookie.slice('uap_project_setup='.length))
            : ''

          const requestedLabel =""", "setup session cookie")
        text = replace(text, """          const session = await createSession({
            id: friendlyId || randomUUID(),
            title: label,
            model,
          })""", """          const session = await createSession({
            id: friendlyId || randomUUID(),
            title: label,
            model,
            setup_project_id: setupProjectId || undefined,
          })""", "setup-bound session creation")
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
        text = replace(text, """  useEffect(() => {
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand])""", """  useEffect(() => {
    if (statusQuery.data?.ok !== true) return
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand, statusQuery.data?.ok])""", "pending command waits for backend")
        text = replace(text, """    if (navCancelKeyRef.current !== navKey) {
      navCancelKeyRef.current = navKey
      cancelStreaming()
    }
  }, [activeCanonicalKey, activeFriendlyId, isNewChat, cancelStreaming])""", """    if (navCancelKeyRef.current !== navKey) {
      navCancelKeyRef.current = navKey
      if (!pendingStartRef.current) {
        cancelStreaming()
      }
    }
  }, [activeCanonicalKey, activeFriendlyId, isNewChat, cancelStreaming])""", "nav cancel preserves pending send")
        text = replace(text, """        if (activeSend?.clientId && !isMissingAuth(messageText)) {
          updateHistoryMessageByClientIdEverywhere(
            queryClient,
            activeSend.clientId,
            (message) => ({
              ...message,
              status: 'error',
            }),
          )
        }
        activeSendRef.current = null""", """        if (activeSend?.clientId && !isMissingAuth(messageText)) {
          const boundedError = messageText.slice(0, 200)
          updateHistoryMessageByClientIdEverywhere(
            queryClient,
            activeSend.clientId,
            (message) => ({
              ...message,
              status: 'error',
              errorMessage: boundedError,
            }),
          )
        }
        activeSendRef.current = null""", "onError attaches bounded error")
        text = replace(text, """    refetchInterval: 60_000, // Re-check every 60s to clear stale errors
  })
  // Don't show errors for new chats or when SSE is connected""", """    refetchInterval: 60_000, // Re-check every 60s to clear stale errors
  })
  const missionProjectsQuery = useQuery({
    queryKey: ['uap', 'mission-projects'],
    queryFn: async () => {
      const res = await fetch('/api/mission-projects')
      if (!res.ok) return null
      return (await res.json()) as {
        projects?: Array<{ project_id: string; label?: string; repository?: string }>
        selected_project_id?: string | null
      } | null
    },
    retry: false,
  })
  const selectedProject = useMemo(() => {
    const data = missionProjectsQuery.data
    if (!data?.selected_project_id || !Array.isArray(data.projects)) return null
    return data.projects.find((p) => p.project_id === data.selected_project_id) ?? null
  }, [missionProjectsQuery.data])
  // Don't show errors for new chats or when SSE is connected""", "mission projects query")
        text = replace(text, """              onUndo={undefined}
              onClear={undefined}
            />
          )}

          {errorNotice && (""", """              onUndo={undefined}
              onClear={undefined}
            />
          )}

          {!compact && (
            <div className="flex items-center gap-2 border-b border-[var(--theme-border)] px-4 py-1.5 text-xs text-[var(--theme-muted)]">
              {selectedProject ? (
                <>
                  <span className="font-medium text-[var(--theme-text)]">{selectedProject.label || selectedProject.project_id}</span>
                  {selectedProject.repository ? (
                    <span className="truncate opacity-70">{selectedProject.repository}</span>
                  ) : null}
                </>
              ) : (
                <span>Проект не выбран</span>
              )}
              <a
                href="/settings?section=projects"
                className="ml-auto shrink-0 text-[var(--theme-accent)] hover:underline"
                onClick={(e) => {
                  e.preventDefault()
                  void navigate({ to: '/settings', search: { section: 'projects' } })
                }}
              >
                Настройки
              </a>
            </div>
          )}

          {errorNotice && (""", "selected project strip")
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
        const projectCookie = (request.headers.get('cookie') || '')
          .split(';')
          .map((part) => part.trim())
          .find((part) => part.startsWith('uap_mission_project='))
        const projectId = projectCookie
          ? decodeURIComponent(projectCookie.slice('uap_mission_project='.length))
          : ''
        const setupCookie = (request.headers.get('cookie') || '')
          .split(';')
          .map((part) => part.trim())
          .find((part) => part.startsWith('uap_project_setup='))
        const setupProjectId = setupCookie
          ? decodeURIComponent(setupCookie.slice('uap_project_setup='.length))
          : ''
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
                  project_id: CENTRAL_ONLY && projectId ? projectId : undefined,
                  setup_project_id: CENTRAL_ONLY && setupProjectId ? setupProjectId : undefined,
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
        text = replace(text, """  model?: string
}): Promise<ClaudeSession> {""", """  model?: string
  setup_project_id?: string
}): Promise<ClaudeSession> {""", "setup session request type")
        return replace(text, """    attachments?: Array<Record<string, unknown>>
  },""", """    attachments?: Array<Record<string, unknown>>
    source_message_id?: string
    project_id?: string
    setup_project_id?: string
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
    elif rel == "src/components/mobile-hamburger-menu.tsx":
        text = replace(text, "export const MOBILE_HAMBURGER_NAV_ITEMS = [", "const CENTRAL_ONLY_BLOCKED_NAV_IDS = new Set(['playground', 'terminal', 'jobs', 'conductor', 'operations', 'swarm', 'swarm2', 'files', 'tasks', 'agents'])\n\nexport const MOBILE_HAMBURGER_NAV_ITEMS = [", "hamburger blocked ids")
        text = replace(text, """  const visibleNavItems = MOBILE_HAMBURGER_NAV_ITEMS.filter(
    (item) => item.id !== 'echo-studio' || echoStudioEnabled,
  )""", """  const visibleNavItems = MOBILE_HAMBURGER_NAV_ITEMS.filter(
    (item) =>
      (item.id !== 'echo-studio' || echoStudioEnabled) &&
      !CENTRAL_ONLY_BLOCKED_NAV_IDS.has(item.id),
  )""", "hamburger blocked filter")
    elif rel == "src/components/mobile-tab-bar.tsx":
        text = replace(text, "]\n\nexport function MobileTabBar() {", "]\n\nconst CENTRAL_ONLY_BLOCKED_TAB_IDS = new Set(['playground', 'files', 'terminal', 'jobs', 'swarm', 'swarm2', 'conductor', 'operations', 'tasks', 'agents'])\nconst VISIBLE_NAV_TABS = MOBILE_NAV_TABS.filter((tab) => !CENTRAL_ONLY_BLOCKED_TAB_IDS.has(tab.id))\n\nexport function MobileTabBar() {", "tab bar blocked ids")
        text = replace(text, "const currentIdx = MOBILE_NAV_TABS.findIndex((tab) => tab.match(pathname))", "const currentIdx = VISIBLE_NAV_TABS.findIndex((tab) => tab.match(pathname))", "tab bar swipe find")
        text = replace(text, "Math.min(currentIdx + 1, MOBILE_NAV_TABS.length - 1)", "Math.min(currentIdx + 1, VISIBLE_NAV_TABS.length - 1)", "tab bar swipe next")
        text = replace(text, "nextIdx < MOBILE_NAV_TABS.length", "nextIdx < VISIBLE_NAV_TABS.length", "tab bar swipe bound")
        text = replace(text, "void navigate({ to: MOBILE_NAV_TABS[nextIdx].to })", "void navigate({ to: VISIBLE_NAV_TABS[nextIdx].to })", "tab bar swipe navigate")
        text = replace(text, "{MOBILE_NAV_TABS.map((tab, idx) => {", "{VISIBLE_NAV_TABS.map((tab, idx) => {", "tab bar render map")
    elif rel == "src/routes/__root.tsx":
        text = replace(text, "} from '@tanstack/react-router'", "  Navigate,\n} from '@tanstack/react-router'", "root Navigate import")
        text = replace(text, "import { LoginScreen } from '@/components/auth/login-screen'", "import { LoginScreen } from '@/components/auth/login-screen'\n\nconst HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED === '1'\nconst UPDATE_CENTER_ENABLED = import.meta.env.VITE_UPDATE_CENTER_ENABLED === '1'\nconst CENTRAL_ONLY_BLOCKED_PATHS = new Set(['/playground', '/hermes-world', '/world', '/reserve', '/reserve/confirm', '/early-access', '/files', '/terminal', '/jobs', '/tasks', '/conductor', '/operations', '/agents', '/swarm', '/swarm2'])", "root flags")
        text = replace(text, "  const isGameSurfaceRoute = isHermesWorldLandingRoute || pathname === '/playground' || pathname.startsWith('/playground/')", "  const isGameSurfaceRoute = HERMESWORLD_ENABLED && (isHermesWorldLandingRoute || pathname === '/playground' || pathname.startsWith('/playground/'))\n  const redirectBlockedRoute = [...CENTRAL_ONLY_BLOCKED_PATHS].some((base) => pathname === base || pathname.startsWith(`${base}/`))", "root game guard")
        text = replace(text, "{!isHermesWorldLandingRoute ? <UpdateCenterNotifier /> : null}", "{UPDATE_CENTER_ENABLED && !isHermesWorldLandingRoute ? <UpdateCenterNotifier /> : null}", "update flag")
        text = replace(text, "        <>\n          <GlobalShortcutListener />", "        <>\n          {redirectBlockedRoute ? <Navigate to=\"/dashboard\" replace /> : null}\n          {!redirectBlockedRoute ? <>\n          <GlobalShortcutListener />", "root redirect")
        text = replace(text, "          ) : null}\n        </>\n      ) : null", "          ) : null}\n          </> : null}\n        </>\n      ) : null", "root redirect close")
    elif rel in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
        text = replace(text, "export const Route = createFileRoute", "const HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED === '1'\n\nexport const Route = createFileRoute", "game endpoint flag")
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
    elif rel == "src/components/settings/settings-sidebar.tsx":
        text = replace(
            text,
            "  | 'connection'\n  | 'claude'",
            "  | 'connection'\n  | 'projects'\n  | 'claude'",
            "project settings navigation type",
        )
        text = replace(
            text,
            "  { id: 'connection', label: 'Connection' },",
            "  { id: 'connection', label: 'Connection' },\n"
            "  { id: 'projects', label: 'Проекты и доступы' },",
            "project settings navigation item",
        )
    elif rel == "src/routes/settings/index.tsx":
        text = replace(
            text,
            "import { usePageTitle } from '@/hooks/use-page-title'",
            "import { usePageTitle } from '@/hooks/use-page-title'\n"
            "import { ProjectPermissions } from '@/components/settings/project-permissions'",
            "project permissions import",
        )
        text = replace(
            text,
            "          {activeSection === 'connection' && <ConnectionSection />}\n",
            """          {activeSection === 'connection' && <ConnectionSection />}

          {activeSection === 'projects' && (
            <SettingsSection
              title="Проекты и доступы"
              description="Выберите зарегистрированный репозиторий для новых автономных задач."
              icon={Link01Icon}
            >
              <ProjectPermissions />
            </SettingsSection>
          )}
""",
            "project permissions section",
        )
    elif rel == "src/screens/chat/components/chat-sidebar.tsx":
        text = replace(
            text,
            "  const isDashboardActive = pathname === '/dashboard'\n\n  const mainItems: Array<NavItemDef> = [",
            "  const isDashboardActive = pathname === '/dashboard'\n\n"
            "  const CENTRAL_ONLY_BLOCKED_NAV_PATHS = new Set(['/files', '/terminal', '/jobs', '/tasks', '/conductor', '/operations', '/agents', '/swarm', '/swarm2'])\n\n"
            "  const mainItems: Array<NavItemDef> = [",
            "desktop sidebar blocked paths",
        )
        return replace(
            text,
            "  ]\n\n  const knowledgeItems: Array<NavItemDef> = [",
            "  ].filter((item) => !(item.kind === 'link' && item.to && CENTRAL_ONLY_BLOCKED_NAV_PATHS.has(item.to)))\n\n  const knowledgeItems: Array<NavItemDef> = [",
            "desktop sidebar blocked filter",
        )
    elif rel == "src/components/command-palette.tsx":
        text = replace(
            text,
            "export function CommandPalette({ pathname, sessions }: CommandPaletteProps) {",
            "const CENTRAL_ONLY_BLOCKED_SCREEN_IDS = new Set(['screen-files', 'screen-terminal'])\n\n"
            "export function CommandPalette({ pathname, sessions }: CommandPaletteProps) {",
            "command palette blocked ids",
        )
        return replace(
            text,
            "    ],\n    [navigate],\n  )",
            "    ].filter((action) => !CENTRAL_ONLY_BLOCKED_SCREEN_IDS.has(action.id)),\n    [navigate],\n  )",
            "command palette blocked filter",
        )
    elif rel == "src/screens/chat/components/message-item.tsx":
        text = replace(text, """function rawTimestamp(message: ChatMessage): number | null {""", """function getMessageErrorMessage(message: ChatMessage): string | undefined {
  const raw = (message as Record<string, unknown>).errorMessage
  return typeof raw === 'string' && raw.trim() ? raw.slice(0, 200) : undefined
}

function rawTimestamp(message: ChatMessage): number | null {""", "message error helper")
        text = replace(text, """          isFailed={isUser && (isFailed || isStuckSending)}
          onRetry={""", """          isFailed={isUser && (isFailed || isStuckSending)}
          errorMessage={isUser && isFailed ? getMessageErrorMessage(message) : undefined}
          onRetry={""", "message error prop")
    elif rel == "src/screens/chat/components/message-actions-bar.tsx":
        text = replace(text, """  isFailed?: boolean
  onRetry?: () => void
}""", """  isFailed?: boolean
  errorMessage?: string
  onRetry?: () => void
}""", "actions bar error type")
        text = replace(text, """  isFailed = false,
  onRetry,
}: MessageActionsBarProps) {""", """  isFailed = false,
  errorMessage,
  onRetry,
}: MessageActionsBarProps) {""", "actions bar error param")
        text = replace(text, """      {isFailed && onRetry && (
        <TooltipProvider>
          <TooltipRoot>
            <TooltipTrigger
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors"
            >
              <HugeiconsIcon icon={RefreshIcon} size={14} strokeWidth={1.6} />
              <span className="text-[11px] font-medium">Retry</span>
            </TooltipTrigger>
            <TooltipContent side="top">Resend failed message</TooltipContent>
          </TooltipRoot>
        </TooltipProvider>
      )}""", """      {isFailed && onRetry && (
        <TooltipProvider>
          <TooltipRoot>
            <TooltipTrigger
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors"
            >
              <HugeiconsIcon icon={RefreshIcon} size={14} strokeWidth={1.6} />
              <span className="text-[11px] font-medium">Retry</span>
            </TooltipTrigger>
            <TooltipContent side="top">Resend failed message</TooltipContent>
          </TooltipRoot>
        </TooltipProvider>
      )}
      {isFailed && errorMessage && (
        <span className="max-w-[240px] truncate text-[11px] text-red-500" title={errorMessage}>
          {errorMessage}
        </span>
      )}""", "actions bar error display")
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
    if rel == "src/screens/chat/chat-screen.tsx":
        if "if (statusQuery.data?.ok !== true) return" not in text:
            text = replace(text, """  useEffect(() => {
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand])""", """  useEffect(() => {
    if (statusQuery.data?.ok !== true) return
    const pendingCommand = window.sessionStorage.getItem(
      CHAT_PENDING_COMMAND_STORAGE_KEY,
    )
    if (!pendingCommand) return

    window.sessionStorage.removeItem(CHAT_PENDING_COMMAND_STORAGE_KEY)
    runPaletteSlashCommand(pendingCommand)
  }, [runPaletteSlashCommand, statusQuery.data?.ok])""", "pending command waits for backend upgrade")
        if "if (!pendingStartRef.current)" not in text:
            text = replace(text, """    if (navCancelKeyRef.current !== navKey) {
      navCancelKeyRef.current = navKey
      cancelStreaming()
    }
  }, [activeCanonicalKey, activeFriendlyId, isNewChat, cancelStreaming])""", """    if (navCancelKeyRef.current !== navKey) {
      navCancelKeyRef.current = navKey
      if (!pendingStartRef.current) {
        cancelStreaming()
      }
    }
  }, [activeCanonicalKey, activeFriendlyId, isNewChat, cancelStreaming])""", "nav cancel preserves pending send upgrade")
        if "errorMessage: boundedError" not in text:
            text = replace(text, """        if (activeSend?.clientId && !isMissingAuth(messageText)) {
          updateHistoryMessageByClientIdEverywhere(
            queryClient,
            activeSend.clientId,
            (message) => ({
              ...message,
              status: 'error',
            }),
          )
        }
        activeSendRef.current = null""", """        if (activeSend?.clientId && !isMissingAuth(messageText)) {
          const boundedError = messageText.slice(0, 200)
          updateHistoryMessageByClientIdEverywhere(
            queryClient,
            activeSend.clientId,
            (message) => ({
              ...message,
              status: 'error',
              errorMessage: boundedError,
            }),
          )
        }
        activeSendRef.current = null""", "onError attaches bounded error upgrade")
        if "missionProjectsQuery" not in text:
            text = replace(text, """    refetchInterval: 60_000, // Re-check every 60s to clear stale errors
  })
  // Don't show errors for new chats or when SSE is connected""", """    refetchInterval: 60_000, // Re-check every 60s to clear stale errors
  })
  const missionProjectsQuery = useQuery({
    queryKey: ['uap', 'mission-projects'],
    queryFn: async () => {
      const res = await fetch('/api/mission-projects')
      if (!res.ok) return null
      return (await res.json()) as {
        projects?: Array<{ project_id: string; label?: string; repository?: string }>
        selected_project_id?: string | null
      } | null
    },
    retry: false,
  })
  const selectedProject = useMemo(() => {
    const data = missionProjectsQuery.data
    if (!data?.selected_project_id || !Array.isArray(data.projects)) return null
    return data.projects.find((p) => p.project_id === data.selected_project_id) ?? null
  }, [missionProjectsQuery.data])
  // Don't show errors for new chats or when SSE is connected""", "mission projects query upgrade")
        if "Проект не выбран" not in text:
            text = replace(text, """              onUndo={undefined}
              onClear={undefined}
            />
          )}

          {errorNotice && (""", """              onUndo={undefined}
              onClear={undefined}
            />
          )}

          {!compact && (
            <div className="flex items-center gap-2 border-b border-[var(--theme-border)] px-4 py-1.5 text-xs text-[var(--theme-muted)]">
              {selectedProject ? (
                <>
                  <span className="font-medium text-[var(--theme-text)]">{selectedProject.label || selectedProject.project_id}</span>
                  {selectedProject.repository ? (
                    <span className="truncate opacity-70">{selectedProject.repository}</span>
                  ) : null}
                </>
              ) : (
                <span>Проект не выбран</span>
              )}
              <a
                href="/settings?section=projects"
                className="ml-auto shrink-0 text-[var(--theme-accent)] hover:underline"
                onClick={(e) => {
                  e.preventDefault()
                  void navigate({ to: '/settings', search: { section: 'projects' } })
                }}
              >
                Настройки
              </a>
            </div>
          )}

          {errorNotice && (""", "selected project strip upgrade")
        return text
    if rel == "src/routes/api/sessions.ts":
        if "if (CENTRAL_ONLY) {\n              return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE" in text:
            text = replace(text, """          if (capabilities.dashboard.available && !capabilities.enhancedChat) {
            if (CENTRAL_ONLY) {
              return json({ ok: false, error: SESSIONS_API_UNAVAILABLE_MESSAGE }, { status: 503 })
            }
            return json({""", """          if (!CENTRAL_ONLY && capabilities.dashboard.available && !capabilities.enhancedChat) {
            return json({""", "central session creation upgrade")
        if "setup_project_id: setupProjectId || undefined" not in text:
            text = replace(text, """          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >

          const requestedLabel =""", """          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >
          const setupCookie = (request.headers.get('cookie') || '')
            .split(';')
            .map((part) => part.trim())
            .find((part) => part.startsWith('uap_project_setup='))
          const setupProjectId = setupCookie
            ? decodeURIComponent(setupCookie.slice('uap_project_setup='.length))
            : ''

          const requestedLabel =""", "setup session cookie upgrade")
            text = replace(text, """          const session = await createSession({
            id: friendlyId || randomUUID(),
            title: label,
            model,
          })""", """          const session = await createSession({
            id: friendlyId || randomUUID(),
            title: label,
            model,
            setup_project_id: setupProjectId || undefined,
          })""", "setup-bound session creation upgrade")
        return text
    if rel == "src/routes/api/send-stream.ts":
        if "project_id: CENTRAL_ONLY ? projectId : undefined" in text:
            text = replace(text, """        const projectId = projectCookie
          ? decodeURIComponent(projectCookie.slice('uap_mission_project='.length))
          : ''""", """        const projectId = projectCookie
          ? decodeURIComponent(projectCookie.slice('uap_mission_project='.length))
          : ''
        const setupCookie = (request.headers.get('cookie') || '')
          .split(';')
          .map((part) => part.trim())
          .find((part) => part.startsWith('uap_project_setup='))
        const setupProjectId = setupCookie
          ? decodeURIComponent(setupCookie.slice('uap_project_setup='.length))
          : ''""", "setup project cookie upgrade")
            text = replace(text, """        if (CENTRAL_ONLY && !projectId) {
          return new Response(
            JSON.stringify({ ok: false, error: 'Выберите проект в Настройки → Проекты и доступы' }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          )
        }
""", "", "discussion without selected project upgrade")
            return replace(text, """                  project_id: CENTRAL_ONLY ? projectId : undefined,
""", """                  project_id: CENTRAL_ONLY && projectId ? projectId : undefined,
                  setup_project_id: CENTRAL_ONLY && setupProjectId ? setupProjectId : undefined,
""", "setup project forwarding upgrade")
        if "Central session stream unavailable" in text:
            text = replace(text, """        if (CENTRAL_ONLY && chatMode === 'portable') {
          return new Response(JSON.stringify({ ok: false, error: 'Central session stream unavailable' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }""", """        if (CENTRAL_ONLY) {
          chatMode = 'enhanced-claude'
        }""", "central-only stream upgrade")
        text = replace(text, """        const sourceMessageId =
          typeof body.idempotencyKey === 'string' ? body.idempotencyKey.trim() : ''
        if (CENTRAL_ONLY && !sourceMessageId) {""", """        const sourceMessageId =
          typeof body.idempotencyKey === 'string' ? body.idempotencyKey.trim() : ''
        const projectCookie = (request.headers.get('cookie') || '')
          .split(';')
          .map((part) => part.trim())
          .find((part) => part.startsWith('uap_mission_project='))
        const projectId = projectCookie
          ? decodeURIComponent(projectCookie.slice('uap_mission_project='.length))
          : ''
        const setupCookie = (request.headers.get('cookie') || '')
          .split(';')
          .map((part) => part.trim())
          .find((part) => part.startsWith('uap_project_setup='))
        const setupProjectId = setupCookie
          ? decodeURIComponent(setupCookie.slice('uap_project_setup='.length))
          : ''
        if (CENTRAL_ONLY && !sourceMessageId) {""", "project selection cookie upgrade")
        return replace(text, """                  source_message_id: CENTRAL_ONLY ? sourceMessageId : undefined,
                },""", """                  source_message_id: CENTRAL_ONLY ? sourceMessageId : undefined,
                  project_id: CENTRAL_ONLY && projectId ? projectId : undefined,
                  setup_project_id: CENTRAL_ONLY && setupProjectId ? setupProjectId : undefined,
                },""", "project selection forwarding upgrade")
    if rel == "src/server/claude-api.ts":
        if "  setup_project_id?: string\n}): Promise<ClaudeSession>" not in text:
            text = replace(text, """  model?: string
}): Promise<ClaudeSession> {""", """  model?: string
  setup_project_id?: string
}): Promise<ClaudeSession> {""", "setup session request type upgrade")
        if "    project_id?: string\n    setup_project_id?: string\n" in text:
            return text
        if "    project_id?: string\n" in text:
            return replace(text, """    project_id?: string
""", """    project_id?: string
    setup_project_id?: string
""", "setup project request type upgrade")
        if "const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'" not in text:
            text = replace(text, """} from './claude-dashboard-api'

const _authHeaders""", """} from './claude-dashboard-api'

const CENTRAL_ONLY = process.env.HERMES_CENTRAL_ONLY === '1'
const _authHeaders""", "central-only session source upgrade")
            text = replace(text, """}): Promise<ClaudeSession> {
  if (getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", """}): Promise<ClaudeSession> {
  if (!CENTRAL_ONLY && getCapabilities().dashboard.available) {
    const resp = await createDashboardSession(opts || {})""", "central-only session creation upgrade")
        return replace(text, """    source_message_id?: string
  },""", """    source_message_id?: string
    project_id?: string
    setup_project_id?: string
  },""", "project selection request type upgrade")
    if rel == "src/components/mobile-hamburger-menu.tsx":
        text = replace(text, "const HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'\n\nexport const MOBILE_HAMBURGER_NAV_ITEMS = [", "const CENTRAL_ONLY_BLOCKED_NAV_IDS = new Set(['playground', 'terminal', 'jobs', 'conductor', 'operations', 'swarm', 'swarm2', 'files', 'tasks', 'agents'])\n\nexport const MOBILE_HAMBURGER_NAV_ITEMS = [", "hamburger blocked ids upgrade")
        text = replace(text, "  ...(HERMESWORLD_ENABLED ? [{\n    id: 'playground',", "  {\n    id: 'playground',", "hamburger unwrap open")
        text = replace(text, "  }] : []),\n  {\n    id: 'terminal',", "  },\n  {\n    id: 'terminal',", "hamburger unwrap close")
        return replace(text, """  const visibleNavItems = MOBILE_HAMBURGER_NAV_ITEMS.filter(
    (item) => item.id !== 'echo-studio' || echoStudioEnabled,
  )""", """  const visibleNavItems = MOBILE_HAMBURGER_NAV_ITEMS.filter(
    (item) =>
      (item.id !== 'echo-studio' || echoStudioEnabled) &&
      !CENTRAL_ONLY_BLOCKED_NAV_IDS.has(item.id),
  )""", "hamburger blocked filter upgrade")
    if rel == "src/components/mobile-tab-bar.tsx":
        text = replace(text, "const HERMESWORLD_ENABLED = import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'\n\nexport const MOBILE_NAV_TABS: Array<TabItem> = [", "export const MOBILE_NAV_TABS: Array<TabItem> = [", "tab bar flag removal")
        text = replace(text, "  ...(HERMESWORLD_ENABLED ? [{\n    id: 'playground',", "  {\n    id: 'playground',", "tab bar unwrap open")
        text = replace(text, "  }] : []),\n  {\n    id: 'files',", "  },\n  {\n    id: 'files',", "tab bar unwrap close")
        text = replace(text, "]\n\nexport function MobileTabBar() {", "]\n\nconst CENTRAL_ONLY_BLOCKED_TAB_IDS = new Set(['playground', 'files', 'terminal', 'jobs', 'swarm', 'swarm2', 'conductor', 'operations', 'tasks', 'agents'])\nconst VISIBLE_NAV_TABS = MOBILE_NAV_TABS.filter((tab) => !CENTRAL_ONLY_BLOCKED_TAB_IDS.has(tab.id))\n\nexport function MobileTabBar() {", "tab bar blocked ids upgrade")
        text = replace(text, "const currentIdx = MOBILE_NAV_TABS.findIndex((tab) => tab.match(pathname))", "const currentIdx = VISIBLE_NAV_TABS.findIndex((tab) => tab.match(pathname))", "tab bar swipe find upgrade")
        text = replace(text, "Math.min(currentIdx + 1, MOBILE_NAV_TABS.length - 1)", "Math.min(currentIdx + 1, VISIBLE_NAV_TABS.length - 1)", "tab bar swipe next upgrade")
        text = replace(text, "nextIdx < MOBILE_NAV_TABS.length", "nextIdx < VISIBLE_NAV_TABS.length", "tab bar swipe bound upgrade")
        text = replace(text, "void navigate({ to: MOBILE_NAV_TABS[nextIdx].to })", "void navigate({ to: VISIBLE_NAV_TABS[nextIdx].to })", "tab bar swipe navigate upgrade")
        return replace(text, "{MOBILE_NAV_TABS.map((tab, idx) => {", "{VISIBLE_NAV_TABS.map((tab, idx) => {", "tab bar render map upgrade")
    if rel == "src/routes/__root.tsx":
        text = replace(text, "import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'", "import.meta.env.VITE_HERMESWORLD_ENABLED === '1'", "root hermesworld flag upgrade")
        text = replace(text, "import.meta.env.VITE_UPDATE_CENTER_ENABLED !== '0'", "import.meta.env.VITE_UPDATE_CENTER_ENABLED === '1'", "root update center flag upgrade")
        text = replace(text, "const DISABLED_GAME_PATHS = new Set(['/playground', '/hermes-world', '/world', '/reserve', '/reserve/confirm', '/early-access'])", "const CENTRAL_ONLY_BLOCKED_PATHS = new Set(['/playground', '/hermes-world', '/world', '/reserve', '/reserve/confirm', '/early-access', '/files', '/terminal', '/jobs', '/tasks', '/conductor', '/operations', '/agents', '/swarm', '/swarm2'])", "root blocked paths upgrade")
        text = replace(text, "  const redirectDisabledGame = !HERMESWORLD_ENABLED && DISABLED_GAME_PATHS.has(pathname)", "  const redirectBlockedRoute = [...CENTRAL_ONLY_BLOCKED_PATHS].some((base) => pathname === base || pathname.startsWith(`${base}/`))", "root redirect logic upgrade")
        text = replace(text, "{redirectDisabledGame ? <Navigate to=\"/dashboard\" replace /> : null}", "{redirectBlockedRoute ? <Navigate to=\"/dashboard\" replace /> : null}", "root redirect jsx upgrade")
        return replace(text, "{!redirectDisabledGame ? <>", "{!redirectBlockedRoute ? <>", "root redirect close upgrade")
    if rel in ("src/routes/api/playground-admin.ts", "src/routes/api/playground-npc.ts"):
        return replace(text, "import.meta.env.VITE_HERMESWORLD_ENABLED !== '0'", "import.meta.env.VITE_HERMESWORLD_ENABLED === '1'", "game endpoint flag upgrade")
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
        elif actual in PREVIOUS_PATCHED_FILES.get(rel, ()):
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
        elif sha(path) in PREVIOUS_ADDED_FILES.get(rel, ()):
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
