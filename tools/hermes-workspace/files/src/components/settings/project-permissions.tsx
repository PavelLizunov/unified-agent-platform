import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type Project = {
  project_id: string
  label: string
  repository: string
  summary: string
  delivery_mode: 'none'
}

export function ProjectPermissions() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState('')
  const [saved, setSaved] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)

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

  return (
    <div className="space-y-4">
      <p className="text-sm text-primary-600">
        Выбор определяет репозиторий для новых задач. Платформа может менять код,
        запускать проверки, создавать PR и сливать зелёный результат. Релизы и
        опасные операции этим разрешением не включаются.
      </p>
      <div className="grid gap-3">
        {projects.map((project) => (
          <label
            key={project.project_id}
            className="flex cursor-pointer gap-3 rounded-xl border border-primary-200 bg-primary-50 p-4"
          >
            <input
              type="radio"
              name="mission-project"
              value={project.project_id}
              checked={selected === project.project_id}
              onChange={() => setSelected(project.project_id)}
              className="mt-1"
            />
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-primary-900">{project.label}</span>
              <span className="block break-all text-xs text-primary-600">{project.repository}</span>
              <span className="mt-1 block text-sm text-primary-700">{project.summary}</span>
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
