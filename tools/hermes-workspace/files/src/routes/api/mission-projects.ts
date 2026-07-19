import { createFileRoute } from '@tanstack/react-router'
import { isAuthenticated } from '../../server/auth-middleware'
import { gatewayFetch } from '../../server/gateway-capabilities'

const COOKIE = 'uap_mission_project'
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

function selectedProject(request: Request): string {
  const cookie = request.headers.get('cookie') || ''
  for (const part of cookie.split(';')) {
    const [name, ...value] = part.trim().split('=')
    if (name === COOKIE) return decodeURIComponent(value.join('='))
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
          const selected = selectedProject(request)
          return Response.json({
            projects,
            selected_project_id: projects.some(
              (project) => project.project_id === selected,
            )
              ? selected
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
        } | null
        const projectId = body?.project_id
        if (typeof projectId !== 'string' || !PROJECT_ID.test(projectId)) {
          return Response.json({ error: 'Invalid project selection' }, { status: 400 })
        }
        try {
          const projects = await catalog()
          if (!projects.some((project) => project.project_id === projectId)) {
            return Response.json({ error: 'Project is not registered' }, { status: 403 })
          }
          return Response.json(
            { ok: true, selected_project_id: projectId },
            {
              headers: {
                'Set-Cookie': `${COOKIE}=${encodeURIComponent(projectId)}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict`,
              },
            },
          )
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
