# Hermes Kanban Swarm — пилот multi-agent оркестрации на build-1

**Статус: Phase 1 (toy swarm) ПРОЙДЕНА 2026-07-09.** Все exit-критерии зелёные. Это durable-рецепт
установки + результаты + план следующих фаз.

## Решение (из 100-итерационного исследования, Google Drive: «2026-07-09 Local-Cloud Multi-Agent Feedback Loop»)

- **Ядро оркестрации = родной Hermes Kanban swarm** (durable SQLite-доска, DAG задач, диспетчер в gateway,
  tmux-воркеры). НЕ сторонний hermes-workspace (он только UI, не source of truth — известные расхождения
  approvals/profiles) и НЕ `delegate_task` (нестабилен для durable: provider-routing/async-потери).
- **Хост пилота = uap-build-1** (8c/16GB) — отдельная инсталляция, прод-под в k3s не тронут.
- **Роли ← соак-данные:** drafter/coder = `ornith-9b` (мак), reviewer+synthesizer = `qwen-35b` (десктоп RTX).
  Правило: **1 воркер : 1 модельный эндпоинт** (иначе очередь, а не параллельность).
- Облачный reviewer позже = поменять провайдер ОДНОГО профиля, структура не меняется.

## Установка (воспроизводимо)

```bash
# build-1, под uap. Всё качается ЧЕРЕЗ VLESS-прокси (astral/GitHub Cloudflare-фронтованы).
export HTTPS_PROXY=http://192.168.0.202:30880 HTTP_PROXY=$HTTPS_PROXY
curl -fsSL https://astral.sh/uv/install.sh | sh          # uv 0.11.28
uv python install 3.13                                    # hermes требует >=3.11,<3.14 (system py = 3.10!)
git clone https://github.com/NousResearch/hermes-agent ~/hermes-agent
cd ~/hermes-agent && git checkout 7c1a0295                # ПИН = коммит прод-пода (паритет версий)
uv venv --python 3.13 .venv && uv pip install -e .
.venv/bin/hermes --version                                # Hermes Agent v0.18.0
```

## Профили (4 шт, `hermes profile create <name>`)

Каждому — `~/.hermes/profiles/<name>/config.yaml` (формат проверен, тот же что в managed-config пода):

```yaml
model:
  provider: custom
  base_url: http://100.82.241.121:8090/v1   # наш роутер на ops-1
  default: <ornith-9b | qwen-35b>
  model: <тот же>
  api_key: local
```

| Профиль | Модель | Роль |
|---|---|---|
| `drafter-ornith` | ornith-9b | драфт/кодинг (соак: 100% coding) |
| `drafter-qwen` | qwen-35b | драфт/reasoning |
| `reviewer-qwen` | qwen-35b | verifier (позже → облако) |
| `synth-qwen` | qwen-35b | synthesizer |

`~/.hermes/config.yaml` (default-профиль) — тоже qwen: под ним живёт gateway/диспетчер.

## Запуск

```bash
H=~/hermes-agent/.venv/bin/hermes
$H kanban init
tmux new-session -d -s hermes-gw "$H gateway 2>&1 | tee -a ~/hermes-gw.log"   # диспетчер ЖИВЁТ в gateway
$H kanban swarm "<goal>" \
  --worker "drafter-ornith:<титул>" --worker "drafter-qwen:<титул>" \
  --verifier reviewer-qwen --synthesizer synth-qwen --json
# наблюдение: $H kanban list / watch / runs <id> / log <id> / context <id> / stats
```

⚠️ **Перед диспетчем — healthcheck обоих эндпоинтов** (пиfall P0 из исследования; окупился сразу — поймал
выключенный qwen): `curl -m 90 <router>/v1/chat/completions -d '{"model":"...","messages":[{"role":"user","content":"ok"}],"max_tokens":1}'` → 200.
qwen НЕ always-on (десктоп): `tools/local-models/start-qwen.bat`.

## ГОЧА №3 про NO_PROXY (та же, что в поде и offload.py!)

`/etc/environment` на build-1 задаёт глобальный прокси (для cargo/GitHub), а `no_proxy` содержал только
LAN-CIDR — **tailnet-IP роутера там не было** → hermes (httpx) слал запросы к `100.82.241.121:8090` через
VLESS → **HTTP 502 на ОБА бэкенда** → воркеры падали → `blocked`. Фикс (сделан durable): добавить в
`no_proxy`/`NO_PROXY` в `/etc/environment` **точные IP** `100.82.241.121,100.85.56.31` (+`100.64.0.0/10`
для curl). httpx CIDR игнорирует — нужен exact-IP. Gateway перезапустить с новым env.

## Результаты toy-прогона (все exit-критерии Phase 1)

- ✅ **Параллельность реальна:** оба воркера `running` одновременно (ornith@мак + qwen@десктоп).
- ✅ DAG: verifier ждал ОБОИХ воркеров; synthesizer ждал verifier; переходы todo→ready автоматические.
- ✅ Воркеры сдали `kanban_complete(summary, metadata)` с машиночитаемыми метаданными (пути артефактов).
- ✅ Verifier НЕ по пересказу: сам перечитал README + оба саммари, вердикт с обоснованием.
  Вердикт: **ornith лучше qwen** («структура + покрытие») — воспроизводит наши соак-замеры.
- ✅ Synthesizer реально объединил (структура ornith + детали qwen) → result.md.
- ✅ **Self-healing:** protocol violation (воркер вышел без complete) → авто-retry → done; фатальные 502 →
  `blocked` с точной причиной в `show` (не молчаливый зомби). Ради этой наблюдаемости и выбран Kanban.

## Известные слабости (для Phase 2)

1. **qwen-воркеры периодически забывают `kanban_complete`** (protocol violation; спасает retry диспетчера,
   limit=2). Лечение: усилить промпт-контракт задачи / goal-mode.
2. **Scratch-workspace эфемерен** (удаляется при complete) — для реальной работы задавать
   `--workspace dir:/abs/path` (или `worktree:` для git), иначе артефакты доступны только через metadata-пути.
3. Локальные модели медленные: полный DAG toy-задачи ≈ 20 мин (2 воркера ~7м, verifier ~5м, synth ~5м).

## SIM-1 — всеохватывающая симуляция полного цикла (2026-07-09) — ПРОЙДЕНА

Сценарий: RU-задача «свежая нода Tailscale не выходит в онлайн» (ответ ЗАРАНЕЕ есть в базе знаний →
отличаем честный retrieval от галлюцинаций). Проверялось всё разом: модели→роутер, рой (DAG),
обязательное обращение воркеров к базе, артефакт-контракт в durable-каталог, write-back знания, гейты, UI.

| Тест | Результат |
|---|---|
| T1 инфра (qwen+ornith 200, gateway, doctor, web) | PASS |
| T2 прод-под → база через `build1` (команда из USER.md) | PASS |
| T3 рой: RU-задача, параллельность, DAG до конца | PASS (с 2 ручными вмешательствами, см. находки) |
| T4 воркеры РЕАЛЬНО спрашивают базу | PASS — аудит: 7→14 searches; в артефактах точные значения из KB |
| T5 артефакт-контракт (`~/swarm-out/sim1/`: 2 драфта + final.md) | PASS — durable, verifier читал файлы |
| T6 write-back: находка роя → `UAP-K-0003` → hypothesis→needs_verification→confirmed (evidence) | PASS — retrieval возвращает запись ПЕРВОЙ (d=11.6 < доков) |
| T7 гейты (запрещённый переход, --approve) + datasette JSON + аудит (196 событий, 3 перехода) | PASS |

**Находки и фиксы (ради этого симуляция и была):**
1. **Слабая модель коверкает длинные команды.** ornith-воркер звал базу как `knowledge.py query` без
   venv-питона (exit 126 → «missing module» → блуждание, 12 runs). Фикс ИНФРАСТРУКТУРНЫЙ, не промптовый:
   venv-шебанг + `chmod +x` на `~/knowledge/bin/knowledge.py`, короткий враппер **`~/.local/bin/knowledge`**,
   SOUL упрощён до `knowledge query "..."`. После фикса ornith с ретрая дошёл до конца сам.
2. **Heartbeat маскирует отсутствие прогресса** (пиfall P0 дока подтверждён вживую): run 12 слал heartbeat
   55+ минут без артефакта; max-runtime гварда в Hermes нет. Ручной протокол восстановления:
   `pgrep -f "<profile>.*<task>"` → `kill` → диспетчер ретраит (после blocked — `kanban unblock`).
   **ЗАКРЫТО watchdog'ом (2026-07-09):** `tools/swarm/watchdog.sh` → `~/swarm-bin/watchdog.sh` на build-1,
   cron `*/15`: убивает worker-процессы старше `WATCHDOG_MAX_S` (деф. 3600с), лог `~/.hermes/watchdog.log`;
   диспетчер дальше сам (retry/blocked). При первом же прогоне поймал живого орфана (71 мин, задача давно
   done) — класс «орфаны копят память» из pod-risk-audit. Разблокировка после серии килов — за человеком.
3. **Протокольный хвост (`kanban_complete`) — систематическая слабость локальных моделей** (в toy — synth,
   тут — synth опять: final.md готов, а воркер крутит kanban_show). Законное восстановление оператором:
   `hermes kanban complete <id> --summary "<итог + путь артефакта + пометка operator-close>"` —
   содержимое произведено моделью, оператор только закрывает факт.

**Главный итог:** внутренний цикл research-дока провёрнут целиком на живой системе:
база → рой → артефакты → verifier → synthesizer → новое знание в базу → оно ищется первым.

## План следующих фаз (по исследованию; НЕ начаты)

- **Phase 2 — artifact contract:** durable workspace + обязательные `summary.json`/`verification.json`
  (schema_version, verdict accept/revise/reject, feedback_for_worker) — verifier читает файлы, не пересказ.
- **Phase 3 — feedback-плагин:** `ctx.register_hook(post_llm_call/post_tool_call/transform_tool_result)` →
  JSONL-трейсы → `~/.hermes/feedback/`.
- **Phase 4 — eval gate** (Promptfoo/DeepEval) перед промоцией фидбека в скиллы/память.
- **Phase 5 — promotion:** повторная verified-критика → skill candidate → eval pass → патч + rollback.
- Облачный reviewer: сменить провайдер `reviewer-qwen` при появлении API-ключа.
