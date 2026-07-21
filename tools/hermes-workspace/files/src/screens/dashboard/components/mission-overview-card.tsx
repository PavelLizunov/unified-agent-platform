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
  project_label?: string | null
  project_repository?: string | null
  notice?: {
    code: string
    message: string
    owner_action_required: boolean
    next_attempt_at?: string
  } | null
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
  artifacts?: Array<{
    artifact_id: string
    name: string
    kind: string
    media_type: string
    size_bytes: number
    sha256: string
  }>
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
const stageLabels: Record<string, string> = {
  accepted: 'Цель принята',
  planning: 'Планирование',
  implementing: 'Внесение изменений',
  testing: 'Автоматические проверки',
  reviewing: 'Независимая проверка',
  delivering: 'PR, CI и слияние',
  verifying: 'Проверка после слияния',
  complete: 'Готово',
}
const statusLabels: Record<string, string> = {
  active: 'в работе',
  waiting_owner: 'нужен ваш ответ',
  completed: 'завершено',
  failed: 'завершено с ошибкой',
  cancelled: 'отменено',
}
const noticeLabels: Record<string, string> = {
  capacity_wait: 'Модель OpenAI временно занята. Повтор запланирован автоматически.',
  capacity_recovered: 'Модель OpenAI снова доступна. Выполнение продолжилось автоматически.',
  execution_reconciling:
    'Проверяю прерванный запуск модели. Новый исполнитель не запускается; восстановление продолжится автоматически.',
  disk_space_wait:
    'Недостаточно свободного места на выделенном томе. Доставка приостановлена до освобождения пространства.',
  disk_space_recovered:
    'Место на выделенном томе освобождено. Доставка продолжилась автоматически.',
}

function ownerQuestionText(question: { question_id: string; text: string }) {
  if (question.question_id.startsWith('owner-gate:')) {
    return 'Задача меняет утверждённую архитектурную границу. Чтобы разрешить это изменение только для этой задачи, ответьте: APPROVE.'
  }
  return question.text
}

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
  if (!items.length) return <span className="text-xs opacity-60">Нет</span>
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
  const projectTitle = mission?.project_label
    ? `${mission.project_label}${mission.project_repository ? ` (${mission.project_repository})` : ''}`
    : mission?.project_repository || mission?.goal || mission?.mission_id

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
      setAnswerError(error instanceof Error ? error.message : 'Не удалось отправить ответ')
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
        Не удалось получить состояние задач: {(query.error as Error).message}
      </div>
    )
  }
  if (!mission) {
    return (
      <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-card)] px-4 py-3 text-sm opacity-70">
        Задач пока нет. Напишите обычным сообщением, что нужно сделать.
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
          <div className="truncate text-sm font-semibold">{projectTitle}</div>
          {mission.goal && mission.goal !== projectTitle ? (
            <div className="truncate text-xs opacity-75">{mission.goal}</div>
          ) : null}
          <div className="text-xs opacity-65">
            Этап: {stageLabels[mission.stage] || mission.stage} · {mission.progress_percent}% · Статус: {statusLabels[mission.status] || mission.status}
          </div>
        </div>
        {missions.length > 1 ? (
          <select
            aria-label="Задача"
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
          <p>Нужен ваш ответ: {ownerQuestionText(mission.question)}</p>
          <form className="mt-2 flex gap-2" onSubmit={submitAnswer}>
            <textarea
              aria-label="Ответ"
              placeholder="Введите ответ"
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
              {answering ? 'Отправляю…' : 'Ответить'}
            </button>
          </form>
          {answerError ? <p className="mt-1 text-xs text-red-400">{answerError}</p> : null}
        </div>
      ) : null}
      {mission.notice ? (
        <div className="mt-3 rounded-md bg-sky-500/10 px-3 py-2 text-sm">
          <p>{noticeLabels[mission.notice.code] || mission.notice.message}</p>
          {mission.notice.next_attempt_at ? (
            <p className="mt-1 text-xs opacity-70">
              Следующая автоматическая попытка (UTC): {mission.notice.next_attempt_at}
            </p>
          ) : null}
          <p className="mt-1 text-xs opacity-70">
            {mission.notice.owner_action_required
              ? 'Требуется ваше действие.'
              : 'От вас ничего не требуется.'}
          </p>
        </div>
      ) : null}
      {mission.result ? (
        <div className="mt-3 rounded-md bg-emerald-500/10 px-3 py-2 text-sm">
          <h3 className="text-xs font-semibold uppercase tracking-wide opacity-70">Результат</h3>
          <p className="mt-1 whitespace-pre-wrap leading-relaxed">{mission.result}</p>
        </div>
      ) : null}
      {mission.artifacts?.map((artifact) => (
        <figure key={artifact.artifact_id} className="mt-3">
          <img
            src={`/api/missions?mission_id=${encodeURIComponent(mission.mission_id)}&artifact_id=${encodeURIComponent(artifact.artifact_id)}`}
            alt={artifact.name}
            className="max-h-96 rounded-md border border-[var(--theme-border)] object-contain"
            loading="lazy"
          />
          <figcaption className="mt-1 text-xs opacity-60">
            {artifact.name} · {artifact.media_type} · {artifact.size_bytes} bytes
          </figcaption>
        </figure>
      ))}
      {mission.error ? <p className="mt-3 text-sm text-red-400">Ошибка: {mission.error}</p> : null}
      {replayQuery.isError ? (
        <p className="mt-3 text-xs text-red-400">
          История задачи временно недоступна: {(replayQuery.error as Error).message}
        </p>
      ) : null}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer select-none text-xs font-medium opacity-75">
          Подробнее о задаче · Задачи {mission.tasks.length} · Исполнители {mission.workers.length} · Проверки {mission.gates.length} · Изменения {mission.changes.length} · Результаты {mission.deliveries.length} · События {missionEvents.length}
        </summary>
        {mission.goal ? (
          <div className="mt-3 rounded-md bg-black/10 px-3 py-2">
            <h3 className="mb-1 text-xs font-semibold">Исходная цель</h3>
            <p className="whitespace-pre-wrap text-xs leading-relaxed">{mission.goal}</p>
          </div>
        ) : null}
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div><h3 className="mb-1 text-xs font-semibold">Задачи</h3>{rows(mission.tasks, 'title', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Исполнители</h3>{rows(mission.workers, 'worker_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Проверки</h3>{rows(mission.gates, 'gate_id', 'status')}</div>
          <div><h3 className="mb-1 text-xs font-semibold">Изменения</h3>{rows(mission.changes, 'path', 'status')}</div>
        </div>
        {missionEvents.length ? (
          <div className="mt-4">
            <h3 className="mb-1 text-xs font-semibold">Хронология</h3>
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
          {mission.mission_id} · событие {mission.sequence} · курсор {replayQuery.data?.cursor ?? 0} · состояние {mission.projection_id}
        </div>
      </details>
    </section>
  )
}
