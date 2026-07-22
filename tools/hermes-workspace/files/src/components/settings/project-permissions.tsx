import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type Project = {
  project_id: string
  label: string
  repository: string
  summary: string
  delivery_mode: 'none' | 'deploy'
  status: 'ready' | 'setup_required' | 'read_only' | 'archived'
  category: string
  test_targets: string[]
}

type Onboarding = {
  request_id: string
  project_id: string
  repository: string
  name: string
  description: string
  preset: 'rust' | 'go' | 'python' | 'web'
  checkpoint: 'requested' | 'repository_ready' | 'runtime_ready' | 'canary_passed' | 'ready' | 'failed'
  progress_percent: number
  error_code?: string | null
}

const statusLabels: Record<Project['status'], string> = {
  ready: 'Готов к автономной работе',
  setup_required: 'Нужно настроить профиль проверок',
  read_only: 'Только просмотр',
  archived: 'Архив',
}

const deliveryLabels: Record<Project['delivery_mode'], string> = {
  none: 'Деплой для этого проекта не настроен',
  deploy: 'После слияния: автоматический деплой и проверка production',
}

const targetLabels: Record<string, string> = {
  'uap-build-1': 'Linux build-1',
  'github-linux': 'GitHub Linux',
  'github-windows': 'GitHub Windows',
  'github-macos': 'GitHub macOS',
  'windows-brat': 'Windows test VM',
  'debian-xfce': 'Debian test VM',
  'pavels-mac-mini': 'Mac mini',
  'android-on-mac': 'Android через Mac mini',
  'desktop-m922ij2': 'Windows workstation',
  vpnctld: 'vpnctl production',
  browser: 'Browser smoke',
}

const onboardingLabels: Record<Onboarding['checkpoint'], string> = {
  requested: 'Создаю приватный GitHub-репозиторий и стартовый проект…',
  repository_ready: 'Репозиторий готов. Устанавливаю безопасный профиль выполнения…',
  runtime_ready: 'Профиль готов. Выполняю тестовую доработку, review и macOS CI…',
  canary_passed: 'Тестовая доработка прошла. Публикую проект в каталоге…',
  ready: 'Проект готов: его уже можно выбирать и использовать автономно.',
  failed: 'Автоматическая подготовка остановлена безопасно.',
}

async function projectPayload() {
  const response = await fetch('/api/mission-projects')
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error || 'Не удалось загрузить проекты')
  return payload
}

async function onboardingPayload() {
  const response = await fetch('/api/project-onboarding')
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error || 'Не удалось получить статус подготовки')
  return payload
}

export function ProjectPermissions() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState('')
  const [saved, setSaved] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [settingUp, setSettingUp] = useState('')
  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [preset, setPreset] = useState<Onboarding['preset']>('rust')
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null)

  useEffect(() => {
    let cancelled = false
    void Promise.all([projectPayload(), onboardingPayload()])
      .then(([projectData, onboardingData]) => {
        if (cancelled) return
        setProjects(Array.isArray(projectData.projects) ? projectData.projects : [])
        setSelected(projectData.selected_project_id || '')
        setSaved(projectData.selected_project_id || '')
        setOnboarding(onboardingData.onboarding || null)
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить настройки')
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!onboarding || ['ready', 'failed'].includes(onboarding.checkpoint)) return
    const timer = window.setInterval(() => {
      void onboardingPayload()
        .then(async (payload) => {
          const next = (payload.onboarding || null) as Onboarding | null
          setOnboarding(next)
          if (next?.checkpoint === 'ready') {
            const projectData = await projectPayload()
            setProjects(Array.isArray(projectData.projects) ? projectData.projects : [])
            setSelected(projectData.selected_project_id || next.project_id)
            setSaved(projectData.selected_project_id || next.project_id)
          }
        })
        .catch((reason) => setError(reason instanceof Error ? reason.message : 'Не удалось обновить статус'))
    }, 5_000)
    return () => window.clearInterval(timer)
  }, [onboarding?.checkpoint, onboarding?.request_id])

  async function save() {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const response = await fetch('/api/mission-projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: selected }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || 'Не удалось сохранить выбор')
      setSaved(selected)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось сохранить выбор')
    } finally {
      setSaving(false)
    }
  }

  async function createProject() {
    setCreating(true)
    setError('')
    try {
      const response = await fetch('/api/project-onboarding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, preset }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || 'Не удалось начать подготовку проекта')
      setOnboarding(payload.onboarding || null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось начать подготовку проекта')
    } finally {
      setCreating(false)
    }
  }

  async function startSetup(projectId: string) {
    setSettingUp(projectId)
    setError('')
    try {
      const response = await fetch('/api/mission-projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, mode: 'setup' }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || 'Не удалось открыть настройку проекта')
      window.location.assign('/chat/new')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось открыть настройку проекта')
      setSettingUp('')
    }
  }

  if (busy && projects.length === 0) {
    return <p className="text-sm text-primary-600">Загружаю проекты и доступы…</p>
  }

  const visibleProjects = projects.filter((project) => {
    const needle = query.trim().toLocaleLowerCase()
    return !needle || `${project.label} ${project.repository} ${project.summary}`.toLocaleLowerCase().includes(needle)
  })
  const onboardingActive = Boolean(
    onboarding && !['ready', 'failed'].includes(onboarding.checkpoint),
  )
  const validName = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(name) && !name.toLocaleLowerCase().endsWith('.git')

  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded-xl border border-primary-200 bg-primary-50 p-4">
        <div>
          <h3 className="text-sm font-semibold text-primary-900">Новый проект одной кнопкой</h3>
          <p className="mt-1 text-xs text-primary-600">
            Платформа создаст приватный репозиторий, добавит стартовый код и macOS CI, выполнит реальную
            тестовую доработку с независимым review и подключит проект после успешной проверки.
            Дополнительных подтверждений не потребуется.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs font-medium text-primary-700">
            Имя репозитория
            <input
              value={name}
              onChange={(event) => setName(event.target.value.trim())}
              placeholder="my-mac-project"
              maxLength={100}
              disabled={onboardingActive}
              className="mt-1 w-full rounded-lg border border-primary-200 bg-white px-3 py-2 text-sm text-primary-900"
            />
          </label>
          <label className="text-xs font-medium text-primary-700">
            Тип проекта
            <select
              value={preset}
              onChange={(event) => setPreset(event.target.value as Onboarding['preset'])}
              disabled={onboardingActive}
              className="mt-1 w-full rounded-lg border border-primary-200 bg-white px-3 py-2 text-sm text-primary-900"
            >
              <option value="rust">Rust</option>
              <option value="go">Go</option>
              <option value="python">Python</option>
              <option value="web">Web / JavaScript</option>
            </select>
          </label>
        </div>
        <label className="block text-xs font-medium text-primary-700">
          Короткое описание
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Что это за проект"
            maxLength={500}
            rows={2}
            disabled={onboardingActive}
            className="mt-1 w-full rounded-lg border border-primary-200 bg-white px-3 py-2 text-sm text-primary-900"
          />
        </label>
        <p className="text-xs text-primary-600">
          Проверка macOS выполняется на одноразовой машине GitHub. Доступ к вашему Mac mini не выдаётся.
        </p>
        <Button
          type="button"
          disabled={!validName || creating || onboardingActive}
          onClick={createProject}
        >
          {creating ? 'Создаю заявку…' : 'Создать и подготовить'}
        </Button>
        {onboarding ? (
          <div className="space-y-2 rounded-lg border border-primary-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3 text-xs text-primary-700">
              <span>{onboardingLabels[onboarding.checkpoint]}</span>
              <span>{onboarding.progress_percent}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-primary-100">
              <div
                className="h-full rounded-full bg-primary-600 transition-all"
                style={{ width: `${Math.max(0, Math.min(100, onboarding.progress_percent))}%` }}
              />
            </div>
            <p className="break-all text-xs text-primary-600">{onboarding.repository}</p>
            {onboarding.checkpoint === 'failed' ? (
              <p className="text-xs text-red-600">
                Ничего опасного не запущено. Код ошибки: {onboarding.error_code || 'unknown'}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-primary-900">Разрешённые проекты</h3>
          <p className="mt-1 text-sm text-primary-600">
            Выбор определяет репозиторий для новых задач. Платформа может менять код, запускать проверки,
            создавать PR и сливать зелёный результат. Релизы и опасные операции сюда не входят.
          </p>
          <p className="mt-2 text-xs text-primary-600">
            Код запускается только на указанных тестовых площадках. Control-plane, Proxmox и ops-сервер
            не используются как произвольные build-машины.
          </p>
        </div>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Найти проект или репозиторий"
          className="w-full rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm text-primary-900"
        />
        <div className="grid gap-3">
          {visibleProjects.map((project) => (
            <label
              key={project.project_id}
              className={`flex gap-3 rounded-xl border border-primary-200 bg-primary-50 p-4 ${
                project.status === 'ready' ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'
              }`}
            >
              <input
                type="radio"
                name="mission-project"
                value={project.project_id}
                checked={selected === project.project_id}
                onChange={() => setSelected(project.project_id)}
                disabled={project.status !== 'ready'}
                className="mt-1"
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-primary-900">{project.label}</span>
                <span className="block break-all text-xs text-primary-600">{project.repository}</span>
                <span className="mt-1 block text-sm text-primary-700">{project.summary}</span>
                <span className="mt-2 flex flex-wrap items-center gap-2 text-xs font-medium text-primary-700">
                  <span>{statusLabels[project.status] || project.status}</span>
                  {project.category === 'active-maintained' ? (
                    <span className="rounded-full border border-primary-200 px-2 py-0.5">
                      Основной проект
                    </span>
                  ) : null}
                </span>
                {project.test_targets.length ? (
                  <span className="mt-1 block text-xs text-primary-600">
                    Проверки: {project.test_targets.map((target) => targetLabels[target] || target).join(' · ')}
                  </span>
                ) : null}
                <span className="mt-1 block text-xs text-primary-600">
                  {deliveryLabels[project.delivery_mode]}
                </span>
                {project.status === 'setup_required' ? (
                  <Button
                    type="button"
                    className="mt-3"
                    disabled={Boolean(settingUp)}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      void startSetup(project.project_id)
                    }}
                  >
                    {settingUp === project.project_id ? 'Открываю чат…' : 'Настроить в чате'}
                  </Button>
                ) : null}
              </span>
            </label>
          ))}
        </div>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        {saved ? (
          <p className="text-xs text-primary-600">
            Текущий проект: {projects.find((project) => project.project_id === saved)?.label}
          </p>
        ) : null}
        <Button type="button" disabled={!selected || saving || selected === saved} onClick={save}>
          {saving ? 'Сохраняю…' : 'Сохранить проект'}
        </Button>
      </section>
    </div>
  )
}
