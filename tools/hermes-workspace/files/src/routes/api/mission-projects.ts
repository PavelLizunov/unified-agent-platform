import { createFileRoute } from '@tanstack/react-router'
import { deleteCookie, setCookie } from '@tanstack/react-start/server'
import { isAuthenticated } from '../../server/auth-middleware'
import { gatewayFetch } from '../../server/gateway-capabilities'

const COOKIE = 'uap_mission_project'
const SETUP_COOKIE = 'uap_project_setup'
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

function cookieValue(request: Request, cookieName: string): string {
  const cookie = request.headers.get('cookie') || ''
  for (const part of cookie.split(';')) {
    const [name, ...value] = part.trim().split('=')
    if (name === cookieName) return decodeURIComponent(value.join('='))
  }
  return ''
}

async function catalog() {
  const response = await gatewayFetch('/api/mission-projects?platform=workspace', {
    signal: AbortSignal.timeout(5_000),
  })
  const payload = (await response.json()) as {
    projects?: Array<Record<string, unknown>>
    error?: string
  }
  if (!response.ok) throw new Error(payload.error || 'Central project catalog unavailable')
  return Array.isArray(payload.projects) ? payload.projects : []
}

export const Route = createFileRoute('/api/mission-projects')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        if (!isAuthenticated(request)) {
          return Response.json({ error: 'Unauthorized' }, { status: 401 })
        }
        try {
          const projects = await catalog()
          const selected = cookieValue(request, COOKIE)
          const setup = cookieValue(request, SETUP_COOKIE)
          return Response.json({
            projects,
            selected_project_id: projects.some(
              (project) => project.project_id === selected && project.status === 'ready',
            )
              ? selected
              : null,
            setup_project_id: projects.some(
              (project) => project.project_id === setup && project.status === 'setup_required',
            )
              ? setup
              : null,
          })
        } catch (error) {
          return Response.json(
            { error: error instanceof Error ? error.message : 'Project catalog unavailable' },
            { status: 503 },
          )
        }
      },
      POST: async ({ request }) => {
        if (!isAuthenticated(request)) {
          return Response.json({ error: 'Unauthorized' }, { status: 401 })
        }
        const body = (await request.json().catch(() => null)) as {
          project_id?: unknown
          mode?: unknown
        } | null
        const projectId = body?.project_id
        if (typeof projectId !== 'string' || !PROJECT_ID.test(projectId)) {
          return Response.json({ error: 'Invalid project selection' }, { status: 400 })
        }
        try {
          const projects = await catalog()
          const project = projects.find((item) => item.project_id === projectId)
          if (!project) {
            return Response.json({ error: 'Проект не зарегистрирован' }, { status: 403 })
          }
          if (body?.mode === 'setup') {
            if (project.status !== 'setup_required') {
              return Response.json({ error: 'Проект не требует настройки' }, { status: 409 })
            }
            setCookie(SETUP_COOKIE, projectId, {
              path: '/',
              maxAge: 86400,
              httpOnly: true,
              sameSite: 'strict',
            })
            return Response.json({ ok: true, setup_project_id: projectId })
          }
          if (body?.mode !== undefined && body.mode !== 'select') {
            return Response.json({ error: 'Invalid project action' }, { status: 400 })
          }
          if (project.status !== 'ready') {
            return Response.json(
              { error: 'Для проекта ещё не настроен проверенный автономный профиль' },
              { status: 409 },
            )
          }
          setCookie(COOKIE, projectId, {
            path: '/',
            maxAge: 31536000,
            httpOnly: true,
            sameSite: 'strict',
          })
          deleteCookie(SETUP_COOKIE, {
            path: '/',
            httpOnly: true,
            sameSite: 'strict',
          })
          return Response.json({ ok: true, selected_project_id: projectId })
        } catch (error) {
          return Response.json(
            { error: error instanceof Error ? error.message : 'Project catalog unavailable' },
            { status: 503 },
          )
        }
      },
    },
  },
})
