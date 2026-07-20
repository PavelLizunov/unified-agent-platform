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
        const missionId = url.searchParams.get('mission_id')
        const artifactId = url.searchParams.get('artifact_id')
        const limit = url.searchParams.get('limit') || '20'
        try {
          if (missionId !== null) {
            if (artifactId !== null) {
              if (!missionId.trim() || !artifactId.trim() || artifactId.length > 128) {
                return Response.json({ error: 'Invalid mission artifact request' }, { status: 400 })
              }
              const response = await gatewayFetch(
                `/api/missions/${encodeURIComponent(missionId)}/artifacts/${encodeURIComponent(artifactId)}`,
                { signal: AbortSignal.timeout(30_000) },
              )
              return new Response(response.body, {
                status: response.status,
                headers: {
                  'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream',
                  'Content-Disposition': response.headers.get('Content-Disposition') || 'inline',
                  'Cache-Control': 'private, max-age=31536000, immutable',
                  'X-Content-Type-Options': 'nosniff',
                },
              })
            }
            const after = Number(url.searchParams.get('after') || '0')
            if (
              !missionId.trim() ||
              missionId.length > 128 ||
              !Number.isSafeInteger(after) ||
              after < 0
            ) {
              return Response.json(
                { error: 'Invalid mission replay request' },
                { status: 400 },
              )
            }
            const response = await gatewayFetch(
              `/api/missions/${encodeURIComponent(missionId)}?after=${after}`,
              { signal: AbortSignal.timeout(5_000) },
            )
            return new Response(await response.text(), {
              status: response.status,
              headers: { 'Content-Type': 'application/json' },
            })
          }
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
        const body = (await request.json().catch(() => null)) as Record<
          string,
          unknown
        > | null
        const missionId = body?.mission_id
        const questionId = body?.question_id
        const text = body?.text
        if (
          typeof missionId !== 'string' ||
          typeof questionId !== 'string' ||
          typeof text !== 'string' ||
          !text.trim() ||
          text.length > 4_000
        ) {
          return Response.json({ error: 'Invalid mission answer' }, { status: 400 })
        }
        try {
          const response = await gatewayFetch(
            `/api/missions/${encodeURIComponent(missionId)}/answer`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Hermes-Mission-Owner-Key': ownerKey,
              },
              body: JSON.stringify({ question_id: questionId, text }),
              signal: AbortSignal.timeout(5_000),
            },
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
