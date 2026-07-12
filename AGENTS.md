# Инструкция агенту-исполнителю (Codex)

## TL;DR (для нового агента)

UAP — self-hosted AI-платформа в k3s-хоумлабе (в РФ, LLM-egress через VLESS-прокси). **North star —
вайб-кодинг:** владелец даёт идею + инфраструктуру и **код не ревьюит** → self-test агента + CI **и есть**
гейт качества. Твоя правка должна быть корректной и самодостаточной. Деплой — **только через PR** (прямой
push в master блокируется ruleset'ом; нужен зелёный `static-checks`). `STATUS.md` — источник истины по
фактам; этот файл — правила и границы. Секреты — никогда в файлы; ссылайся на расположение.

### Статус слоёв (сверять со `STATUS.md`)

| Слой | Состояние |
|---|---|
| **Infra** | k3s 2-node, **НЕ HA** (единственный control-plane/server `uap-home-1` + agent `uap-home-2` = один etcd-член; `uap-home-2` = 6 vCPU / 8 GB). VPS/HA отложены владельцем из-за бюджета; текущая стратегия — один control-plane + R2 backups + проверенный restore drill. Flux GitOps + SOPS/age; etcd→R2 DR. **LIVE.** |
| **Model** | `subfleet` v0.3.1 (Claude-подписка как OpenAI-совместимый gateway) **LIVE + healthy**; DE-exit ротирован на живой ninitux. LiteLLM. Два egress-сервиса: `singbox-egress` (pinned VLESS, subfleet OAuth — **НИКОГДА не ротировать**) + `singbox-egress-ha` (urltest-failover, hermes + build-1). **LIVE.** |
| **Agent** | hermes-agent в k3s (`uap-system`, `uap-home-2`). **Мозг = локальный router** (`http://100.82.241.121:8090/v1`, `qwen-35b`, fallback `ornith-9b`); cloud-tier (Codex/Claude) **OFF** — платные лимиты исчерпаны, revert-путь в ConfigMap. **Codex — только coding-engine.** **LIVE.** |
| **Tools** | На `uap-build-1` (VMID 102, 8c/16GB, tailnet `100.85.56.31`; всё systemd, **НЕ k3s, НЕ GitOps**): knowledge-система, Kanban-рой, ai-search, hermes-workspace `:3000`. `local-models`-router — systemd на ops-1. Индекс: [tools/README.md](tools/README.md). **LIVE.** |

### Канонический порядок чтения

1. `AGENTS.md` (этот файл) → `README.md` → `DECISIONS.md` → `STATUS.md` (факты) → `RISKS.md`
2. `docs/infrastructure.md` (флот + что-где) → `docs/next-steps.md` (план hermes-agent + открытый фундамент)
3. `docs/research/nousresearch-hermes-agent.md` + `docs/research/hermes-codex-subscription-brain.md` (почему hermes-agent; исходное «мозг = Codex» — теперь локальный router, см. `STATUS.md`)
4. Индексы: [runbooks/README.md](runbooks/README.md) (все runbook'и) + [tools/README.md](tools/README.md) (подсистемы `tools/`)
5. Гейты: `runbooks/validation-matrix.md` (инфра) + `runbooks/vibe-coding-acceptance.md` (сквозной цикл)

---

Ты получил спецификацию платформы. **Инфра/ADR-решения — закрыты:** реализуй, не перепроектируй. **НО
модельный/агентный слой и харнесс — в активной переработке** (2026-06 пивот на вайб-кодинг + внешний
NousResearch hermes-agent, ADR-022..026): здесь предлагай через ADR и действуй с согласия владельца, и **не
считай старые ADR-001/004/006 текущими** по этому слою. Ориентиры: `STATUS.md`, `docs/next-steps.md`, `docs/research/`.

## Порядок работы

1. Прочитай [README.md](README.md) → [ARCHITECTURE.md](ARCHITECTURE.md) → [DECISIONS.md](DECISIONS.md) →
   [BUILD-PLAN.md](BUILD-PLAN.md) → [RISKS.md](RISKS.md).
2. Реализуй по [BUILD-PLAN.md](BUILD-PLAN.md) **строго по этапам**. Этап 0 выполняет владелец (VPS + сеть).
   Твоя работа начинается с Этапа 1.
3. Этап считается выполненным **только** когда проходит его «веха» (тест на отказоустойчивость).
   Не переходи к следующему этапу, пока веха не зелёная.

## Правила

- **Следуй [DECISIONS.md](DECISIONS.md).** Эти вопросы закрыты. Если считаешь решение ошибочным —
  не меняй молча: вынеси аргумент владельцу и жди ответа.
- **Спрашивай владельца** по любому открытому пункту (домены, ключи API, destructive failover-тесты,
  смена уже принятой топологии). Не выдумывай за него.
- Новые фиксированные решения см. ADR-008..ADR-013: k3s вместо Docker/vanilla k8s, Tailscale как
  сетевой фундамент, бюджетный VPS-профиль только через веху, Flux+SOPS, Go-first/Rust-for-daemons,
  Windows/Mac только как внешние agent-воркеры.
- **Версии и команды в этом пакете — заготовки.** Перед применением сверь с актуальной документацией
  компонентов (k3s, CloudNativePG, Restate, LiteLLM) — они быстро меняются.
- **Секреты не коммить.** API-ключи (Claude, OpenRouter), пароли Postgres — через SOPS/age и
  k8s Secrets, не plaintext в открытых манифестах.

## Совместная работа Codex + Claude Code

- Codex и Claude Code — равноправные ИИ-исполнители. Источник правды: файлы репозитория, ADR и git,
  а не память отдельного агента.
- Перед началом задачи агент читает `AGENTS.md`, `DECISIONS.md`, актуальный этап в `BUILD-PLAN.md` и
  проверяет, нет ли незавершённых чужих изменений в тех же файлах.
- Параллельные кодинг-воркеры — **каждый в своём `git worktree`** на одноразовой ветке (а не «не править
  одни файлы» на словах); сливать в master только по зелёному гейту. Если работаешь без worktree и задачи
  пересекаются — сначала зафиксировать границу: кто меняет infra, кто tests/runbooks, кто docs.
- Коммиты — **Conventional Commits** (`type(scope): summary`) с трейлером
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; git-identity на ops-1 = `UAP Agent <slovnmi@gmail.com>`.
  **Деплой — только через PR** (прямой push в master отклоняется ruleset'ом; требуется зелёный `static-checks`).
- Изменения делать маленькими и проверяемыми: манифесты отдельно, скрипты отдельно, runbook отдельно.
- Каждый агент оставляет результат так, чтобы другой мог продолжить: что изменено, какие команды
  запускались, что прошло, что не проверено.
- Для Claude Code текущий handoff лежит в `CLAUDE.md`; обновляй его, если меняется фактический порядок
  продолжения работ, команды проверки или список безопасных следующих задач.
- Архитектурные изменения сначала фиксируются как ADR или правка существующего ADR; молча менять
  закрытые решения запрещено.
- Секреты не вставлять в prompts, логи, markdown, shell history или манифесты. Агентам выдавать только
  имена secret keys/переменных и команды создания секретов без значений.

## Чего НЕ делать

- ❌ Не делать локальный inference-слой (Ollama на Mac/Windows) отказоустойчивым — он best-effort overflow.
- ❌ Не включать Windows/Mac в etcd-кворум k3s — их выключают, кворум развалится. Они только воркеры.
- ❌ Не делать durable execution для всех задач подряд — только для критичных/длинных (см. ADR-004).
- ❌ Не завязывать архитектуру на конкретный дашборд — он сменный модуль (ADR-007).
- ❌ Не ждать, что LiteLLM сам решит «простая задача или сложная» — это делает агент явными правилами (ADR-006).
- ❌ Не использовать Claude Code или Codex как скрытый источник решений: всё важное должно быть в файлах.

## Текущий фокус

**2026-06 пивот: вайб-кодинг через внешний hermes-agent** (ADR-024/025). Магистраль — поднять hermes-agent
(мозг = Codex `codex_app_server` или локальная FC-модель на RTX 5060 Ti; кодинг = `claude -p` + `codex exec`).
Инфра-слой (k3s/Flux/SOPS) построен и стабилен; **VPS и HA отложены владельцем на неопределённый срок из-за бюджета**.
Третий k3s server не является active owner action. Фазированный план — `docs/next-steps.md` (Track A — пилот
hermes-agent, Track B — blast-radius + DR при текущей single-control-plane стратегии). HA-заявления — только после
будущей отдельной owner decision, 3 независимых server-нод и зелёной failover-вехи.
