import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

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

const activeStatuses = new Set(['active', 'waiting_owner'])

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
  const mission = selectMission(missions, selectedId)

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
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer select-none text-xs font-medium opacity-75">
          Tasks {mission.tasks.length} · Workers {mission.workers.length} · Gates {mission.gates.length} · Changes {mission.changes.length}
        </summary>
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div><h3 className="mb-1 text-xs font-semibold">Tasks</h3>{rows(mission.tasks, 'title', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Workers</h3>{rows(mission.workers, 'worker_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Gates</h3>{rows(mission.gates, 'gate_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Changes</h3>{rows(mission.changes, 'path', 'status')}</div>
        </div>
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
          {mission.mission_id} · event {mission.sequence} · state {mission.projection_id}
        </div>
      </details>
    </section>
  )
}
