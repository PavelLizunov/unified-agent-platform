import { createFileRoute } from '@tanstack/react-router'
import { isAuthenticated } from '../../server/auth-middleware'
import { gatewayFetch } from '../../server/gateway-capabilities'

export const Route = createFileRoute('/api/missions')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        if (!isAuthenticated(request)) {
          return Response.json({ error: 'Unauthorized' }, { status: 401 })
        }
        const url = new URL(request.url)
        const limit = url.searchParams.get('limit') || '20'
        try {
          const response = await gatewayFetch(
            `/api/missions?limit=${encodeURIComponent(limit)}`,
            { signal: AbortSignal.timeout(5_000) },
          )
          return new Response(await response.text(), {
            status: response.status,
            headers: { 'Content-Type': 'application/json' },
          })
        } catch (error) {
          return Response.json(
            {
              error:
                error instanceof Error
                  ? error.message
                  : 'Central mission API unavailable',
            },
            { status: 503 },
          )
        }
      },
    },
  },
})
