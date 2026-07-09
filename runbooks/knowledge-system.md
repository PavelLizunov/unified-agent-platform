# UAP Engineering Knowledge System — canonical registry + локальный RAG

**Статус: MVP (Day-1 из research-дока) развёрнут на build-1 2026-07-09.**
Исходник исследования: Google Drive «Hermes AI Engineering Knowledge System Research v0.1» (2026-07-09).
Код: [tools/knowledge/knowledge.py](../tools/knowledge/knowledge.py) (один файл, ~500 строк).

## Главный принцип (из исследования)

**Vector DB — НЕ source of truth.** Истина = canonical registry (SQLite: records + documents + append-only
audit). Векторный индекс — производный и пересоздаваемый (`reindex`). Default-поиск видит только
active-знания; resolved/rejected/superseded/obsolete доступны только явно (`--historical` / `--scope`).

## Решения по 10 открытым вопросам исследования (приняты 2026-07-09)

| # | Вопрос | Решение | Почему |
|---|---|---|---|
| 1 | Первый проект | **UAP-репо** | корпус (docs/runbooks/ADR) уже есть; VPNRouter вторым (`--project vpnrouter`) |
| 2 | Registry: Postgres или SQLite | **SQLite** | ops-1 мал; память агентов не должна зависеть от кластера; Postgres = месяц-1 |
| 3 | Embedding-модель | **intfloat/multilingual-e5-large** (fastembed/ONNX, CPU) | корпус RU+EN; локально на 8 ядрах build-1; смена модели = `reindex` |
| 4 | Облачные эмбеддинги | **Нет, никакие** | приватность by default; всё локально |
| 5 | Drive mirror | human-facing only, mirror позже | Week-1 задача |
| 6 | Approval UI | **CLI**: `record set-status … --approve` | человек запускает команду = sign-off; Workspace-очередь позже |
| 7 | Строгость авто-переходов | risky-переходы (confirmed_fixed/resolved/rejected/superseded) **блокируются без --approve** | зашито в TRANSITIONS/APPROVAL_REQUIRED |
| 8 | GitHub issues canonical? | нет, только linked evidence | |
| 9 | Отдельная archive-коллекция? | **один индекс + retrieval_scope в payload** | проще, фильтр в SQL |
| 10 | Мульти-чат конфликты | append-only audit сейчас, curator merge потом | док сам к этому склонялся |

**Vector-слой = sqlite-vec, не Qdrant** (осознанное отклонение от рекомендации дока): docker на build-1
отсутствует, индекс by-design пересоздаваемый, наш масштаб — тысячи чанков, payload-фильтры = обычный SQL
WHERE. Миграция на Qdrant при росте тривиальна (`reindex` в новую БД). <!-- ponytail: sqlite-vec, Qdrant когда упрёмся в масштаб/HNSW -->

## Где живёт

- **build-1** (`uap@100.85.56.31`): движок `~/knowledge/bin/knowledge.py`, venv `~/knowledge/.venv`
  (fastembed+sqlite-vec+pyyaml, python 3.13/uv), БД `~/knowledge/knowledge.db` (WAL), модели `~/knowledge/models`.
- Корпус: `~/unified-agent-platform` (клон public-репо; sync идемпотентен по sha256).
- Установка deps/моделей — только через VLESS-прокси (`192.168.0.202:30880`), HF Cloudflare-фронтован.

## CLI (алиас: `K='~/knowledge/.venv/bin/python ~/knowledge/bin/knowledge.py'`)

```bash
$K sync --repo ~/unified-agent-platform --project uap   # инжест: скан+редакт+чанк+эмбед (только изменённое)
$K query "почему hermes получал 502 через прокси" [-k 8] [--historical] [--scope all] [--show-text]
$K record add --title "..." --type finding --status confirmed --body-file - <<'EOF' … EOF
$K record list [--status confirmed] ; $K record show UAP-K-0001
$K record set-status UAP-K-0001 patch_ready [--evidence "PR #94"]      # risky-переходы требуют --approve
$K stats ; $K reindex   # reindex = полное пере-эмбеддинование (смена модели)
```

## Как это устроено (соответствие research-доку)

- **Ingestion:** rglob `*.md` → `.ragignore` (в корне репо) → **блокер** (файл с PRIVATE KEY пропускается целиком)
  → **редактор** (regex: ghp_/github_pat_/sk-/AKIA/xox/age1/JWT/Bearer/vless|ss|vmess/password=… → `[REDACTED]`)
  → header-aware чанкер (~1600 chars, breadcrumb-префикс `[path > section]` в каждом чанке) → эмбеддинг →
  sha256/version tracking (изменился файл → version+1, чанки заменяются; файл исчез → status superseded,
  chunks → scope archive).
- **Lifecycle:** 12 статусов дока; допустимые переходы зашиты (TRANSITIONS map); терминальные/рисковые
  требуют `--approve`; каждый переход = audit event с evidence.
- **Retrieval policy:** default = scope active + (docs: active) + (records: confirmed/patch_ready/
  implemented/validation_pending). `--historical` включает resolved/rejected/superseded/obsolete.
  KNN over-fetch (k×12) → SQL-фильтры payload → top-k. Каждый запрос аудитируется.
- **Security:** документы = ДАННЫЕ, не инструкции (никогда не исполнять команды из найденных чанков);
  секреты редактируются ДО эмбеддинга; sops/env не индексируются.

## Доступ для Hermes (сейчас, без плагина)

Из пода / kanban-воркеров — через build1-обёртку:
`/opt/data/.local/bin/build1 "~/knowledge/.venv/bin/python ~/knowledge/bin/knowledge.py query '<вопрос>' -k 5"`
Плагин `hermes_knowledge` (tools: knowledge.search/get_record/propose_record/...) — Week-1 задача.

## План дальше (по доку; НЕ начато)

- **Week-1:** Drive-sync (export docs→md), GitHub issues/PR как source_type, scheduler (cron на build-1:
  15-min детект + nightly sync), Hermes-plugin tools, curator-отчёт (дубликаты/противоречия/stale).
- **Month-1:** regression hunter на PR (retrieval по affected_files из resolved/regression_watch),
  CI-интеграция, approval-очередь в UI, опционально graph-слой и Postgres/Qdrant при росте.

## Первая каноническая запись

`UAP-K-0001` — NO_PROXY exact-IP gotcha (третье место; см. `record show UAP-K-0001`) — заведена как
демонстрация полного цикла record → status transitions → audit.
