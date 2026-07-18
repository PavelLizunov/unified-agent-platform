import { useQuery } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'

type Item = Record<string, string>

export type MissionView = {
  mission_id: string
  sequence: number
  projection_id: string
  status: string
  stage: string
  progress_percent: number
  goal?: string | null
  question?: { question_id: string; text: string } | null
  answer?: { question_id: string; text: string } | null
  result?: string | null
  error?: string | null
  tasks: Array<Item>
  workers: Array<Item>
  terminal: Array<{ sequence: number; stream: string; text: string }>
  changes: Array<Item>
  gates: Array<Item>
  deliveries: Array<Item>
}

type MissionResponse = { missions?: Array<MissionView>; error?: string }
type MissionEvent = {
  event_id: string
  sequence: number
  type: string
  occurred_at?: string
}
type MissionReplayResponse = {
  mission?: MissionView
  events?: Array<MissionEvent>
  cursor?: number
  error?: string
}
type MissionReplay = {
  mission: MissionView
  events: Array<MissionEvent>
  cursor: number
}

const activeStatuses = new Set(['active', 'waiting_owner'])

export function mergeMissionReplay(
  previous: MissionReplay | null,
  incoming: MissionReplayResponse,
  missionId: string,
): MissionReplay {
  const mission = incoming.mission
  const cursor = incoming.cursor
  const events = incoming.events
  if (
    !mission ||
    mission.mission_id !== missionId ||
    typeof cursor !== 'number' ||
    !Number.isSafeInteger(cursor) ||
    cursor < 0 ||
    !Array.isArray(events)
  ) {
    throw new Error('Invalid mission replay response')
  }
  const base = previous?.mission.mission_id === missionId ? previous : null
  const baseCursor = base?.cursor ?? 0
  const appended: Array<MissionEvent> = []
  let expected = baseCursor + 1
  for (const event of events) {
    if (
      !Number.isSafeInteger(event.sequence) ||
      event.sequence < 1 ||
      typeof event.event_id !== 'string' ||
      typeof event.type !== 'string'
    ) {
      throw new Error('Invalid mission replay event')
    }
    if (event.sequence <= baseCursor) continue
    if (event.sequence !== expected) throw new Error('Mission event sequence gap')
    appended.push(event)
    expected += 1
  }
  if (baseCursor + appended.length !== cursor) {
    throw new Error('Mission replay cursor mismatch')
  }
  return {
    mission,
    events: [...(base?.events ?? []), ...appended],
    cursor,
  }
}

export function selectMission(
  missions: Array<MissionView>,
  selectedId: string,
): MissionView | null {
  return (
    missions.find((mission) => mission.mission_id === selectedId) ??
    missions.find((mission) => activeStatuses.has(mission.status)) ??
    missions[0] ??
    null
  )
}

function rows(items: Array<Item>, primary: string, secondary: string) {
  if (!items.length) return <span className="text-xs opacity-60">None</span>
  return (
    <ul className="space-y-1 text-xs">
      {items.map((item, index) => (
        <li key={`${item[primary] || index}`} className="flex justify-between gap-3">
          <span className="truncate">{item[primary]}</span>
          <span className="shrink-0 opacity-65">{item[secondary]}</span>
        </li>
      ))}
    </ul>
  )
}

function safeDeliveryUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

export function MissionOverviewCard() {
  const [selectedId, setSelectedId] = useState('')
  const [answerDraft, setAnswerDraft] = useState({ questionId: '', text: '' })
  const [answerError, setAnswerError] = useState('')
  const [answering, setAnswering] = useState(false)
  const replayRef = useRef<MissionReplay | null>(null)
  const query = useQuery<MissionResponse>({
    queryKey: ['central-missions'],
    queryFn: async () => {
      const response = await fetch('/api/missions?limit=8', { cache: 'no-store' })
      const body = (await response.json()) as MissionResponse
      if (!response.ok) throw new Error(body.error || `Mission API ${response.status}`)
      return body
    },
    refetchInterval: 2_000,
    refetchOnWindowFocus: true,
    retry: 1,
  })
  const missions = query.data?.missions ?? []
  const snapshotMission = selectMission(missions, selectedId)
  const replayQuery = useQuery<MissionReplay>({
    queryKey: ['central-mission-events', snapshotMission?.mission_id],
    enabled: Boolean(snapshotMission),
    queryFn: async () => {
      const missionId = snapshotMission!.mission_id
      const previous =
        replayRef.current?.mission.mission_id === missionId
          ? replayRef.current
          : null
      const response = await fetch(
        `/api/missions?mission_id=${encodeURIComponent(missionId)}&after=${previous?.cursor ?? 0}`,
        { cache: 'no-store' },
      )
      const body = (await response.json()) as MissionReplayResponse
      if (!response.ok) throw new Error(body.error || `Mission API ${response.status}`)
      const replay = mergeMissionReplay(previous, body, missionId)
      replayRef.current = replay
      return replay
    },
    refetchInterval: 2_000,
    refetchOnWindowFocus: true,
    retry: 1,
  })
  const mission = replayQuery.data?.mission ?? snapshotMission
  const missionEvents = replayQuery.data?.events ?? []

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const question = mission?.question
    const text =
      answerDraft.questionId === question?.question_id
        ? answerDraft.text.trim()
        : ''
    if (!mission || !question || !text) return
    setAnswering(true)
    setAnswerError('')
    try {
      const response = await fetch('/api/missions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mission_id: mission.mission_id,
          question_id: question.question_id,
          text,
        }),
      })
      const body = (await response.json()) as MissionResponse
      if (!response.ok) throw new Error(body.error || `Mission API ${response.status}`)
      setAnswerDraft({ questionId: '', text: '' })
      await query.refetch()
      await replayQuery.refetch()
    } catch (error) {
      setAnswerError(error instanceof Error ? error.message : 'Answer failed')
    } finally {
      setAnswering(false)
    }
  }

  if (query.isLoading) {
    return <div className="h-20 animate-pulse rounded-xl bg-[var(--theme-card)]" />
  }
  if (query.isError) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm">
        Central mission state unavailable: {(query.error as Error).message}
      </div>
    )
  }
  if (!mission) {
    return (
      <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-card)] px-4 py-3 text-sm opacity-70">
        No central missions yet.
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-card)] px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`size-2 rounded-full ${activeStatuses.has(mission.status) ? 'bg-amber-400' : mission.status === 'completed' ? 'bg-emerald-500' : 'bg-red-500'}`}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{mission.goal || mission.mission_id}</div>
          <div className="text-xs opacity-65">
            {mission.stage} · {mission.progress_percent}% · {mission.status}
          </div>
        </div>
        {missions.length > 1 ? (
          <select
            aria-label="Mission"
            value={mission.mission_id}
            onChange={(event) => setSelectedId(event.target.value)}
            className="max-w-52 rounded-md border border-[var(--theme-border)] bg-transparent px-2 py-1 text-xs"
          >
            {missions.map((item) => (
              <option key={item.mission_id} value={item.mission_id}>
                {item.mission_id}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded bg-black/15">
        <div
          className="h-full bg-[var(--theme-accent)] transition-[width]"
          style={{ width: `${Math.max(0, Math.min(100, mission.progress_percent))}%` }}
        />
      </div>
      {mission.question ? (
        <div className="mt-3 rounded-md bg-amber-500/10 px-3 py-2 text-sm">
          <p>Question: {mission.question.text}</p>
          <form className="mt-2 flex gap-2" onSubmit={submitAnswer}>
            <textarea
              aria-label="Answer"
              maxLength={4_000}
              rows={2}
              value={
                answerDraft.questionId === mission.question.question_id
                  ? answerDraft.text
                  : ''
              }
              onChange={(event) =>
                setAnswerDraft({
                  questionId: mission.question!.question_id,
                  text: event.target.value,
                })
              }
              className="min-w-0 flex-1 rounded-md border border-[var(--theme-border)] bg-transparent px-2 py-1 text-sm"
            />
            <button
              type="submit"
              disabled={
                answering ||
                answerDraft.questionId !== mission.question.question_id ||
                !answerDraft.text.trim()
              }
              className="self-end rounded-md border border-[var(--theme-border)] px-3 py-1 text-xs disabled:opacity-50"
            >
              {answering ? 'Sending…' : 'Answer'}
            </button>
          </form>
          {answerError ? <p className="mt-1 text-xs text-red-400">{answerError}</p> : null}
        </div>
      ) : null}
      {mission.result ? <p className="mt-3 text-sm">Result: {mission.result}</p> : null}
      {mission.error ? <p className="mt-3 text-sm text-red-400">{mission.error}</p> : null}
      {replayQuery.isError ? (
        <p className="mt-3 text-xs text-red-400">
          Mission history unavailable: {(replayQuery.error as Error).message}
        </p>
      ) : null}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer select-none text-xs font-medium opacity-75">
          Tasks {mission.tasks.length} · Workers {mission.workers.length} · Gates {mission.gates.length} · Changes {mission.changes.length} · Events {missionEvents.length}
        </summary>
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div><h3 className="mb-1 text-xs font-semibold">Tasks</h3>{rows(mission.tasks, 'title', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Workers</h3>{rows(mission.workers, 'worker_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Gates</h3>{rows(mission.gates, 'gate_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Changes</h3>{rows(mission.changes, 'path', 'status')}</div>
        </div>
        {missionEvents.length ? (
          <div className="mt-4">
            <h3 className="mb-1 text-xs font-semibold">Timeline</h3>
            <ol className="max-h-44 space-y-1 overflow-auto text-xs">
              {missionEvents.map((event) => (
                <li key={event.event_id} className="flex gap-2">
                  <span className="w-8 shrink-0 text-right opacity-45">{event.sequence}</span>
                  <span>{event.type}</span>
                  {event.occurred_at ? (
                    <time className="ml-auto shrink-0 opacity-45">{event.occurred_at}</time>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
        {mission.terminal.length ? (
          <pre className="mt-4 max-h-56 overflow-auto rounded-md bg-black/20 p-3 text-xs whitespace-pre-wrap">
            {mission.terminal.map((entry) => entry.text).join('')}
          </pre>
        ) : null}
        {mission.deliveries.length ? (
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {mission.deliveries.map((delivery) => (
              safeDeliveryUrl(delivery.url) ? (
                <a
                  key={delivery.kind}
                  href={safeDeliveryUrl(delivery.url)!}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  {delivery.kind}: {delivery.status}
                </a>
              ) : (
                <span key={delivery.kind}>{delivery.kind}: {delivery.status}</span>
              )
            ))}
          </div>
        ) : null}
        <div className="mt-3 text-[10px] opacity-45">
          {mission.mission_id} · event {mission.sequence} · cursor {replayQuery.data?.cursor ?? 0} · state {mission.projection_id}
        </div>
      </details>
    </section>
  )
}
