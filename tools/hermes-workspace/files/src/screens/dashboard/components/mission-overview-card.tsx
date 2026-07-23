import { useQuery } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'

type Item = Record<string, string | number | boolean | null | undefined>

export type MissionView = {
  mission_id: string
  sequence: number
  projection_id: string
  status: string
  stage: string
  progress_percent: number
  updated_at?: string | null
  project_label?: string | null
  project_repository?: string | null
  notice?: {
    code: string
    message: string
    owner_action_required: boolean
    next_attempt_at?: string
    phase?: string
    cycle?: number
    cycle_limit?: number
    url?: string
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
  source?: string
  payload?: Record<string, unknown>
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
  deploying: 'Развёртывание',
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
const waitLabels: Record<string, string> = {
  capacity_wait: 'освобождения модели OpenAI',
  disk_space_wait: 'освобождения места на томе',
  execution_reconciling: 'восстановления прерванного запуска',
}
const checkpointLabels: Record<string, string> = {
  new: 'задача создана',
  author_committed: 'изменения внесены автором',
  candidate_pushed: 'кандидат отправлен в репозиторий',
  candidate_pr_open: 'открыт черновик PR',
  pr_open: 'PR открыт',
  pre_review_ci_green: 'CI зелёный до ревью',
  needs_fix: 'требуются правки после ревью',
  ci_failed: 'CI не пройден',
  author_checks_failed: 'проверки автора не пройдены',
  review_escalation_pending: 'ожидает эскалации ревью',
  waiting_owner: 'ожидает владельца',
  owner_answer_pending: 'ожидает ответа владельца',
  post_verify_running: 'проверка после слияния выполняется',
  post_verify_retry_pending: 'запланирован повтор проверки после слияния',
  post_verify_failed: 'проверка после слияния не пройдена',
  post_verify_repair_completed: 'восстановление после слияния завершено',
  deploy_running: 'развёртывание выполняется',
  deploy_retry_wait: 'ожидание повтора развёртывания',
  deployment_failed: 'развёртывание не выполнено',
  complete: 'готово',
}
const costUnattested =
  'API-стоимость: не подтверждена — официального прайса для внутренних маршрутов нет, runtime подписки стоимость не аттестует'

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

function formattedUpdatedAt(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString('ru-RU')
}

function missionIdFromLocation() {
  if (typeof window === 'undefined') return ''
  return new URLSearchParams(window.location.search).get('mission') || ''
}

function selectMissionInLocation(missionId: string) {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  url.searchParams.set('mission', missionId)
  window.history.replaceState(null, '', url)
}

function missionDeepLink(missionId: string) {
  if (typeof window === 'undefined' || !missionId) return ''
  const url = new URL('/dashboard', window.location.origin)
  url.searchParams.set('mission', missionId)
  return url.toString()
}

function compactTokenCount(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(value)
}

function numberValue(item: Item, key: string) {
  const value = item[key]
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : null
}

function runningTaskTitle(tasks: Array<Item>): string | null {
  for (const task of tasks) {
    if (task.status === 'running' || task.status === 'in_progress') {
      const title = task.title
      if (typeof title === 'string' && title.trim()) {
        return title.replace(/\s+/g, ' ').trim().slice(0, 120)
      }
    }
  }
  return null
}

function eventPresentation(event: MissionEvent) {
  const payload = event.payload ?? {}
  const text = (key: string) =>
    typeof payload[key] === 'string' ? String(payload[key]) : ''
  const number = (key: string) =>
    typeof payload[key] === 'number' ? Number(payload[key]) : null
  switch (event.type) {
    case 'mission.accepted':
      return { title: 'Цель принята', detail: 'Создана одна durable-задача в Central Hermes.' }
    case 'mission.stage': {
      const stage = text('stage')
      const progress = number('progress_percent')
      return {
        title: stageLabels[stage] || stage || 'Этап обновлён',
        detail: progress === null ? '' : `Прогресс ${progress}%.`,
      }
    }
    case 'mission.notice':
      return {
        title: 'Подробное обновление',
        detail: text('message'),
      }
    case 'task.upsert': {
      const status = text('status')
      return {
        title: status === 'running' ? 'Задача запущена' : 'Задача подготовлена',
        detail: text('title'),
      }
    }
    case 'worker.upsert': {
      const profile = text('profile')
      const role = profile === 'author' ? 'Автор' : profile === 'reviewer' ? 'Ревьюер' : 'Координатор'
      const model = text('model')
      const input = number('input_tokens')
      return {
        title: `${role}: ${text('status') || 'обновление'}`,
        detail: [model, input === null ? '' : `вход ${compactTokenCount(input)}`].filter(Boolean).join(' · '),
      }
    }
    case 'gate.upsert':
      return { title: `Проверка: ${text('gate_id')}`, detail: text('status') }
    case 'change.upsert':
      return { title: `Изменение: ${text('path')}`, detail: text('status') }
    case 'delivery.upsert':
      return { title: `Результат: ${text('kind')}`, detail: text('status') }
    case 'mission.completed':
      return { title: 'Задача завершена', detail: text('result') }
    case 'mission.failed':
      return { title: 'Задача завершилась с ошибкой', detail: text('error') }
    case 'mission.cancelled':
      return { title: 'Задача отменена', detail: text('reason') }
    default:
      return { title: event.type, detail: '' }
  }
}

function rows(items: Array<Item>, primary: string, secondary: string) {
  if (!items.length) return <span className="text-xs opacity-60">Нет</span>
  return (
    <ul className="space-y-1 text-xs">
      {items.map((item, index) => (
        <li key={`${item[primary] || index}`} className="flex justify-between gap-3">
          <span className="truncate">{String(item[primary] ?? '')}</span>
          <span className="shrink-0 opacity-65">{String(item[secondary] ?? '')}</span>
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
  const [selectedId, setSelectedId] = useState(missionIdFromLocation)
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
  const selectedMissionId = selectedId || snapshotMission?.mission_id || ''
  const replayQuery = useQuery<MissionReplay>({
    queryKey: ['central-mission-events', selectedMissionId],
    enabled: Boolean(selectedMissionId),
    queryFn: async () => {
      const missionId = selectedMissionId
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
  const missionOptions =
    mission && !missions.some((item) => item.mission_id === mission.mission_id)
      ? [mission, ...missions]
      : missions
  const telemetryWorkers = mission?.workers.filter(
    (worker) => worker.profile === 'author' || worker.profile === 'reviewer',
  ) ?? []
  const usageWorker = mission?.workers.find(
    (worker) => worker.profile === 'usage',
  )
  const measuredWorkers = (usageWorker ? [usageWorker] : telemetryWorkers).filter(
    (worker) => numberValue(worker, 'input_tokens') !== null,
  )
  const usageIsCumulative = Boolean(usageWorker)
  const totalInput = measuredWorkers.reduce(
    (total, worker) => total + (numberValue(worker, 'input_tokens') ?? 0),
    0,
  )
  const hasCompleteCacheData = measuredWorkers.every(
    (worker) => numberValue(worker, 'cached_input_tokens') !== null,
  )
  const totalCached = measuredWorkers.reduce(
    (total, worker) => total + (numberValue(worker, 'cached_input_tokens') ?? 0),
    0,
  )
  const hasCompleteOutputData = measuredWorkers.every(
    (worker) => numberValue(worker, 'output_tokens') !== null,
  )
  const totalOutput = measuredWorkers.reduce(
    (total, worker) => total + (numberValue(worker, 'output_tokens') ?? 0),
    0,
  )
  const hasCompleteRequestData = measuredWorkers.every(
    (worker) => numberValue(worker, 'model_requests') !== null,
  )
  const totalRequests = measuredWorkers.reduce(
    (total, worker) => total + (numberValue(worker, 'model_requests') ?? 0),
    0,
  )
  const discardedAttempts = measuredWorkers.reduce(
    (total, worker) => total + (numberValue(worker, 'attempts_discarded') ?? 0),
    0,
  )
  const projectTitle = mission?.project_label
    ? `${mission.project_label}${mission.project_repository ? ` (${mission.project_repository})` : ''}`
    : mission?.project_repository || mission?.goal || mission?.mission_id
  const updatedAt = formattedUpdatedAt(mission?.updated_at)

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

  const isActive = activeStatuses.has(mission.status)
  // Unknown stage falls back to the same localized generic label as Telegram —
  // never expose a raw internal stage id in the active-update block.
  const stageLabel = stageLabels[mission.stage] || 'Выполнение'
  const runningTitle = runningTaskTitle(mission.tasks)
  const currentOperation = `${stageLabel}${runningTitle ? ` — ${runningTitle}` : ''}`
  const phaseLabel = mission.notice?.phase
    ? checkpointLabels[mission.notice.phase] ?? null
    : null
  const checkpoint = [
    stageLabel,
    mission.sequence > 0 ? `durable-событие ${mission.sequence}` : null,
    phaseLabel,
  ]
    .filter(Boolean)
    .join(' · ')
  const waitingFor = mission.question?.text
    ? 'вашего ответа на вопрос'
    : mission.notice && waitLabels[mission.notice.code]
      ? waitLabels[mission.notice.code]
      : 'причина ожидания ещё не записана, жду следующей автоматической контрольной точки'
  const ownerActionRequired =
    Boolean(mission.question?.text) || Boolean(mission.notice?.owner_action_required)

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
          {mission.notice?.cycle && mission.notice?.cycle_limit ? (
            <div className="text-xs opacity-65">
              Цикл {mission.notice.cycle} из {mission.notice.cycle_limit}
              {mission.notice.phase && checkpointLabels[mission.notice.phase]
                ? ` · ${checkpointLabels[mission.notice.phase]}`
                : ''}
            </div>
          ) : null}
          {updatedAt ? (
            <div className="text-xs opacity-55">Последнее обновление: {updatedAt}</div>
          ) : null}
          {mission.mission_id ? (
            <a
              href={missionDeepLink(mission.mission_id)}
              className="text-xs underline underline-offset-2 opacity-70"
            >
              Ссылка на эту задачу
            </a>
          ) : null}
        </div>
        {missionOptions.length > 1 ? (
          <select
            aria-label="Задача"
            value={mission.mission_id}
            onChange={(event) => {
              replayRef.current = null
              setSelectedId(event.target.value)
              selectMissionInLocation(event.target.value)
            }}
            className="max-w-52 rounded-md border border-[var(--theme-border)] bg-transparent px-2 py-1 text-xs"
          >
            {missionOptions.map((item) => (
              <option key={item.mission_id} value={item.mission_id}>
                {item.project_label || item.project_repository?.split('/').pop() || 'Задача'} · {(item.goal || '').replace(/\s+/g, ' ').slice(0, 48)} · {stageLabels[item.stage] || item.stage} {item.progress_percent}% · {item.mission_id.slice(-8)}
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
      {isActive ? (
        <div className="mt-3 rounded-md bg-black/10 px-3 py-2 text-xs leading-relaxed">
          <p>Сейчас: {currentOperation}</p>
          <p>Контрольная точка: {checkpoint}</p>
          <p>Ждёт: {waitingFor}</p>
          <p>Нужно ваше действие: {ownerActionRequired ? 'да' : 'нет'}</p>
        </div>
      ) : null}
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
          {mission.notice.url && safeDeliveryUrl(mission.notice.url) ? (
            <a
              href={safeDeliveryUrl(mission.notice.url)!}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block text-xs underline underline-offset-2"
            >
              Открыть текущий PR или результат
            </a>
          ) : null}
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
      {measuredWorkers.length ? (
        <div className="mt-3 rounded-md bg-violet-500/10 px-3 py-2 text-sm">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide opacity-70">
              {usageIsCumulative
                ? 'Накопительный расход выбранной задачи'
                : 'Последние сохранённые прогоны'}
            </h3>
            <span className="text-xs opacity-65">
              {hasCompleteRequestData
                ? `${totalRequests} запросов к моделям`
                : 'число запросов не сохранено'}
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed">
            Вход {compactTokenCount(totalInput)}
            {hasCompleteCacheData
              ? ` · runtime-кэш (подтверждено runtime, не биллинг) ${compactTokenCount(totalCached)} (${totalInput ? ((totalCached * 100) / totalInput).toFixed(1) : '0.0'}%) · новый вход ${compactTokenCount(Math.max(0, totalInput - totalCached))}`
              : ' · данные о кэше не сохранены'}
            {hasCompleteOutputData
              ? ` · выход ${compactTokenCount(totalOutput)}`
              : ' · выход не сохранён'}
          </p>
          <p className="mt-1 text-xs opacity-70">
            {telemetryWorkers.map((worker) => (
              `${worker.profile === 'author' ? 'Автор' : 'Ревьюер'}: ${String(worker.model || 'модель не указана')}`
            )).join(' · ')}
          </p>
          <p className="mt-1 text-xs opacity-70">{costUnattested}</p>
          {!usageIsCumulative ? (
            <p className="mt-1 text-xs text-amber-300">
              Для этой старой миссии накопительный ledger ещё не вёлся; предыдущие correction cycles могут не входить в сумму.
            </p>
          ) : null}
          {discardedAttempts ? (
            <p className="mt-1 text-xs text-amber-300">
              Это нижняя граница: как минимум {discardedAttempts} предыдущих или отброшенных прогонов не входят в сумму.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 rounded-md bg-black/10 px-3 py-2 text-xs opacity-70">
          Токены появятся здесь сразу после завершения текущего прогона модели. Во время самого прогона Codex не отдаёт подтверждённый итоговый usage.
        </div>
      )}
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
            <ol className="max-h-72 space-y-2 overflow-auto text-xs">
              {missionEvents.map((event) => {
                const presentation = eventPresentation(event)
                return (
                  <li key={event.event_id} className="flex gap-2 rounded bg-black/5 px-2 py-1.5">
                    <span className="w-6 shrink-0 text-right opacity-45">{event.sequence}</span>
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{presentation.title}</span>
                      {presentation.detail ? (
                        <span className="mt-0.5 block whitespace-pre-wrap opacity-70">
                          {presentation.detail}
                        </span>
                      ) : null}
                      <span className="mt-0.5 block font-mono text-[10px] opacity-35">
                        {event.type}
                      </span>
                    </span>
                    {event.occurred_at ? (
                      <time className="shrink-0 opacity-45">
                        {formattedUpdatedAt(event.occurred_at)}
                      </time>
                    ) : null}
                  </li>
                )
              })}
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
            {mission.deliveries.map((delivery, index) => {
              const kind = String(delivery.kind ?? 'result')
              const status = String(delivery.status ?? '')
              const url = safeDeliveryUrl(String(delivery.url ?? ''))
              const key = `${kind}-${index}`
              return url ? (
                <a
                  key={key}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  {kind}: {status}
                </a>
              ) : (
                <span key={key}>{kind}: {status}</span>
              )
            })}
          </div>
        ) : null}
        <div className="mt-3 text-[10px] opacity-45">
          {mission.mission_id} · событие {mission.sequence} · курсор {replayQuery.data?.cursor ?? 0} · состояние {mission.projection_id}
        </div>
      </details>
    </section>
  )
}
