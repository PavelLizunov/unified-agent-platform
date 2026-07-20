import { createFileRoute } from '@tanstack/react-router'
import { isAuthenticated } from '../../server/auth-middleware'
import { gatewayFetch } from '../../server/gateway-capabilities'

const COOKIE = 'uap_project_onboarding'
const PROJECT_COOKIE = 'uap_mission_project'
const REQUEST_ID = /^project-onboarding-[0-9a-f]{32}$/
const PROJECT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/
const PRESETS = new Set(['rust', 'go', 'python', 'web'])

function cookieValue(request: Request, name: string): string {
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const [candidate, ...value] = part.trim().split('=')
    if (candidate === name) return decodeURIComponent(value.join('='))
  }
  return ''
}

async function central(path: string, init?: RequestInit) {
  const response = await gatewayFetch(path, {
    ...init,
    signal: AbortSignal.timeout(10_000),
  })
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>
  return { response, payload }
}

function result(
  payload: Record<string, unknown>,
  status: number,
  requestId?: string,
) {
  const headers = new Headers()
  if (requestId) {
    headers.append(
      'Set-Cookie',
      `${COOKIE}=${encodeURIComponent(requestId)}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict`,
    )
  }
  const onboarding = payload.onboarding as Record<string, unknown> | undefined
  if (onboarding?.checkpoint === 'ready' && typeof onboarding.project_id === 'string') {
    headers.append(
      'Set-Cookie',
      `${PROJECT_COOKIE}=${encodeURIComponent(onboarding.project_id)}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict`,
    )
  }
  return Response.json(payload, { status, headers })
}

export const Route = createFileRoute('/api/project-onboarding')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        if (!isAuthenticated(request)) {
          return Response.json({ error: 'Unauthorized' }, { status: 401 })
        }
        const requestId = cookieValue(request, COOKIE)
        if (!requestId) return Response.json({ onboarding: null })
        if (!REQUEST_ID.test(requestId)) {
          return Response.json({ error: 'Некорректный идентификатор настройки проекта' }, { status: 400 })
        }
        try {
          const { response, payload } = await central(`/api/project-onboarding/${requestId}`)
          if (response.status === 404) {
            return Response.json(
              { onboarding: null },
              { headers: { 'Set-Cookie': `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict` } },
            )
          }
          return result(payload, response.status, requestId)
        } catch {
          return Response.json({ error: 'Central временно недоступен' }, { status: 503 })
        }
      },
      POST: async ({ request }) => {
        if (!isAuthenticated(request)) {
          return Response.json({ error: 'Unauthorized' }, { status: 401 })
        }
        const ownerKey = process.env.HERMES_MISSION_OWNER_KEY?.trim()
        if (!ownerKey) {
          return Response.json(
            { error: 'Mission owner capability unavailable' },
            { status: 503 },
          )
        }
        const body = (await request.json().catch(() => null)) as {
          name?: unknown
          description?: unknown
          preset?: unknown
        } | null
        if (
          typeof body?.name !== 'string' ||
          !PROJECT_NAME.test(body.name) ||
          body.name.toLocaleLowerCase().endsWith('.git') ||
          typeof body.description !== 'string' ||
          body.description.length > 500 ||
          typeof body.preset !== 'string' ||
          !PRESETS.has(body.preset)
        ) {
          return Response.json({ error: 'Проверьте имя, описание и тип проекта' }, { status: 400 })
        }
        try {
          const { response, payload } = await central('/api/project-onboarding', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Hermes-Mission-Owner-Key': ownerKey,
            },
            body: JSON.stringify({
              name: body.name,
              description: body.description,
              preset: body.preset,
            }),
          })
          const onboarding = payload.onboarding as Record<string, unknown> | undefined
          const requestId = typeof onboarding?.request_id === 'string'
            ? onboarding.request_id
            : undefined
          return result(payload, response.status, requestId)
        } catch {
          return Response.json({ error: 'Central временно недоступен' }, { status: 503 })
        }
      },
    },
  },
})
