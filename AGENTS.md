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
| **Model** | Flow delivery использует автоматическую OpenAI-only policy ADR-031: Luna/Sol/Terra без подтверждения каждого запуска. `subfleet`/Claude остаётся исторически установленной отдельной capacity, но не является автоматическим fallback. **LIVE policy rollout сверять со `STATUS.md`.** |
| **Agent** | Внешний hermes-agent в k3s (`uap-system`, `uap-home-2`) — основа агентного слоя. Текущий brain/runtime и его доказательства сверять только с `STATUS.md`; Luna/Sol/Terra выбирает policy, а Claude/local/GPU без отдельного решения не запускать. **LIVE.** |
| **Tools** | На `uap-build-1` (VMID 102, 8c/16GB, tailnet `100.85.56.31`; всё systemd, **НЕ k3s, НЕ GitOps**): knowledge-система, Kanban-рой, ai-search, hermes-workspace `:3000`. `local-models`-router — systemd на ops-1. Индекс: [tools/README.md](tools/README.md). **LIVE.** |

### Канонический порядок чтения

1. `AGENTS.md` (этот файл) → `README.md` → `DECISIONS.md` → `STATUS.md` (факты) → `RISKS.md`
2. `docs/product-operating-contract.md` (что платформа обязана делать для владельца) → `docs/infrastructure.md`
   (флот + что-где) → `docs/next-steps.md` (текущий phased plan)
3. `docs/research/nousresearch-hermes-agent.md` + `docs/research/hermes-codex-subscription-brain.md` (почему hermes-agent;
   фактический текущий brain/runtime всегда сверять с `STATUS.md`)
4. Индексы: [runbooks/README.md](runbooks/README.md) (все runbook'и) + [tools/README.md](tools/README.md) (подсистемы `tools/`)
5. Гейты: `runbooks/validation-matrix.md` (инфра) + `runbooks/vibe-coding-acceptance.md` (сквозной цикл)

---

Ты получил спецификацию платформы. **Инфра/ADR-решения — закрыты:** реализуй, не перепроектируй. **НО
модельный/агентный слой и харнесс — в активной переработке** (2026-06 пивот на вайб-кодинг + внешний
NousResearch hermes-agent, ADR-022..031): здесь следуй принятым ADR и постоянным полномочиям владельца, и **не
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
- **Спрашивай владельца** только при настоящем продуктовом блокере или перед реально опасным действием: новые
  credentials/external authority, destructive non-disposable data loss/failover, выход за цель, смена закрытой
  архитектуры/security boundary, новый provider/Claude или local inference/GPU. Обычные Luna/Sol/Terra, стоимость,
  reasoning effort, retries, tests/VM, PR/CI/merge и repo-defined deploy/post-verify подтверждения не требуют.
- Новые фиксированные решения см. ADR-008..ADR-013: k3s вместо Docker/vanilla k8s, Tailscale как
  сетевой фундамент, бюджетный VPS-профиль только через веху, Flux+SOPS, Go-first/Rust-for-daemons,
  Windows/Mac только как внешние agent-воркеры.
- **Версии и команды в этом пакете — заготовки.** Перед применением сверь с актуальной документацией
  компонентов (k3s, CloudNativePG, Restate, LiteLLM) — они быстро меняются.
- **Секреты не коммить.** API-ключи (Claude, OpenRouter), пароли Postgres — через SOPS/age и
  k8s Secrets, не plaintext в открытых манифестах.

## Совместная работа ИИ-исполнителей

- Источник правды для любого ИИ-исполнителя: файлы репозитория, ADR и git, а не память отдельного агента.
- Перед началом задачи агент читает `AGENTS.md`, `DECISIONS.md`, актуальный этап в `BUILD-PLAN.md` и
  проверяет, нет ли незавершённых чужих изменений в тех же файлах.
- Параллельные кодинг-воркеры — **каждый в своём `git worktree`** на одноразовой ветке (а не «не править
  одни файлы» на словах); сливать в master только по зелёному гейту. Если работаешь без worktree и задачи
  пересекаются — сначала зафиксировать границу: кто меняет infra, кто tests/runbooks, кто docs.
- Multi-checkpoint и задачи дольше 30 минут запускаются по ADR-028 через Hermes Kanban flow из
  `runbooks/hermes-flow-v2.md`, а не цепочкой `chat --resume`.
- Author и read-only reviewer используют разные exact OpenAI models и разные sessions из детерминированного
  `delivery-route`: Luna→Sol, Sol→Terra или Terra→Sol. Review привязан к exact SHA, read-only sandbox и runtime
  attestation; один provider является принятой policy, не degraded fallback. Merge запрещён без `verification.json`
  с `accept`, совпадающим HEAD SHA и зелёным required CI; новый commit требует нового review.
- Claude, новый provider и локальные/GPU-модели запускаются только после отдельного решения владельца. Не делай
  probe запрещённой capacity. Точный model ID, effort и session всегда сохраняются в Flow artifacts.
- Коммиты — **Conventional Commits** (`type(scope): summary`). `Co-Authored-By` добавляется только для реально
  участвовавшего автора; точная модель и session фиксируются в Flow v2 artifacts. Git-identity на ops-1 =
  `UAP Agent <slovnmi@gmail.com>`.
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

**2026-07-17: автономный Hermes mission delivery** (ADR-030/031, `docs/product-operating-contract.md`). Внешний hermes-agent
остаётся основой. Workspace и Telegram должны показывать одну central Hermes mission/history; build-1, Flow/Kanban,
coding workers и test VM — execution plane этой mission, не вторая точка управления. A6 и A7.1/A7.2 завершили
central mission projection и safe blocked handoff. A7.3 прошёл fixed-profile acceptance canary на исправленном
`openai-autonomy-v2`: timer intake, runtime-attested Sol/Terra author/review, recovery planned durable checkpoint,
multi-platform CI, exact-head merge, fresh-main post-verify, единый Central/Workspace/Telegram terminal status и
cleanup без ручного coordinator tick или mid-run repair. Это не доказывает generic arbitrary-repository intake или
полную cross-channel chat/session history. Question/resume и lifecycle/retention уже установлены; дальнейшие правки
делать без нового сервиса, dashboard, Claude, local model или GPU.
Инфра-слой (k3s/Flux/SOPS) построен и стабилен; **VPS и HA отложены владельцем на неопределённый срок из-за бюджета**.
Третий k3s server не является active owner action. Фазированный план — `docs/next-steps.md` (Track A — пилот
hermes-agent, Track B — blast-radius + DR при текущей single-control-plane стратегии). HA-заявления — только после
будущей отдельной owner decision, 3 независимых server-нод и зелёной failover-вехи.
