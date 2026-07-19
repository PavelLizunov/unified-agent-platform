import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type Project = {
  project_id: string
  label: string
  repository: string
  summary: string
  delivery_mode: 'none'
  status: 'ready' | 'setup_required' | 'read_only' | 'archived'
  category: string
  test_targets: string[]
}

const statusLabels: Record<Project['status'], string> = {
  ready: 'Готов к автономной работе',
  setup_required: 'Нужно настроить профиль проверок',
  read_only: 'Только просмотр',
  archived: 'Архив',
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
  browser: 'Browser smoke',
}

export function ProjectPermissions() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState('')
  const [saved, setSaved] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [query, setQuery] = useState('')

  useEffect(() => {
    void fetch('/api/mission-projects')
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.error || 'Не удалось загрузить проекты')
        setProjects(Array.isArray(payload.projects) ? payload.projects : [])
        setSelected(payload.selected_project_id || '')
        setSaved(payload.selected_project_id || '')
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Не удалось загрузить проекты'))
      .finally(() => setBusy(false))
  }, [])

  async function save() {
    if (!selected) return
    setBusy(true)
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
      setBusy(false)
    }
  }

  if (busy && projects.length === 0) return <p className="text-sm text-primary-600">Загружаю разрешённые проекты…</p>

  const visibleProjects = projects.filter((project) => {
    const needle = query.trim().toLocaleLowerCase()
    return !needle || `${project.label} ${project.repository} ${project.summary}`.toLocaleLowerCase().includes(needle)
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-primary-600">
        Выбор определяет репозиторий для новых задач. Платформа может менять код,
        запускать проверки, создавать PR и сливать зелёный результат. Релизы и
        опасные операции этим разрешением не включаются.
      </p>
      <p className="text-xs text-primary-600">
        Операционные серверы UAP известны платформе, но код проекта запускается только на указанных тестовых
        площадках. Control-plane, Proxmox и ops-сервер не используются как произвольные build-машины.
      </p>
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
            </span>
          </label>
        ))}
      </div>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {saved ? <p className="text-xs text-primary-600">Текущий проект: {projects.find((p) => p.project_id === saved)?.label}</p> : null}
      <Button type="button" disabled={!selected || busy || selected === saved} onClick={save}>
        Сохранить проект
      </Button>
    </div>
  )
}
