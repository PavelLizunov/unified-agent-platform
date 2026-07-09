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

- На build-1 (kanban-воркеры, локальные сессии): просто **`knowledge query "<вопрос>" -k 5`** —
  враппер `~/.local/bin/knowledge` в системном PATH (`/etc/environment`), работает и в non-interactive ssh.
- Из прод-пода: `/opt/data/.local/bin/build1 "knowledge query '<вопрос>' -k 5"`.
- ⚠️ Урок SIM-1: слабые модели коверкают длинные команды → и шебанг на venv, и короткий враппер, и
  упрощённые SOUL-инструкции обязательны (invocation-proof). Плагин `hermes_knowledge` — Month-1, если надо.

## Week-1 — СДЕЛАНО 2026-07-09

- **GitHub ingestion:** `sync-github` — issues+PR (title/body/labels/comments) через авторизованный `gh`
  на build-1; change-detect по `updated_at`; ключи документов `gh:<owner/repo>#issue/N | #pr/N`.
  Живьём: +95 items, ретривал проверен (запрос про singbox-фикс вернул именно PR #19/#36).
- **Scheduler (cron, uap@build-1):** nightly 03:30 `~/knowledge/bin/nightly.sh` (git pull → sync repo →
  sync-github → drive-mirror если есть; лог `~/knowledge/logs/nightly-YYYYMMDD.log`); weekly Пн 04:10
  `weekly.sh` (curate → `~/knowledge/reports/`). Cron-путь проверен прогоном в `env -i`.
- **Curator:** `curate` — near-duplicates (KNN d<8), записи без evidence, stale (>30d), low-confidence,
  orphan-чанки. ТОЛЬКО предлагает — не удаляет (правило дока).
- **Doctor:** `doctor` — db/модель/gh-auth/последний audit (для отладки cron).
- **Validation-шаблон:** [docs/templates/validation-report.md](../docs/templates/validation-report.md)
  (+ анти-false-resolved чек-лист из секции 9 дока).
- **Hermes-интеграция (ladder вместо плагина):** блок «База знаний» добавлен в SOUL.md всех 5 профилей
  роя на build-1 (воркеры зовут CLI напрямую — они локальны) и в USER.md прод-пода (live + сид;
  из пода — через `build1 "..."`). Полноценный plugin (tools knowledge.search/...) — Month-1, если
  скилл-подход окажется недостаточным.
- **Drive-sync:** `~/knowledge/bin/drive-sync.sh` готов (rclone → `~/knowledge/drive-mirror` →
  `sync --source-type google_drive_doc`), но **BLOCKED на one-time owner OAuth**:
  на build-1 выполнить `rclone config` → new remote, имя `drive`, тип `drive`, scope `drive.readonly`
  (headless-флоу даст ссылку для браузера). После этого nightly сам подхватит зеркало.
  Папка по умолчанию «AI Notes» (`DRIVE_FOLDER` env, чтобы сменить).

## Веб-просмотр базы (добавлено 2026-07-09)

**http://100.85.56.31:8100** (tailnet-only) — datasette read-only поверх `knowledge.db` (WAL → живые данные,
ночной sync не конфликтует). Systemd `knowledge-web.service` (enable --now, Restart=on-failure), sqlite-vec
подгружается через `--load-extension`. Готовые выборки (canned queries) на главной: активные записи / все
записи / документы по источникам / аудит / кто-что-искал / кандидаты в устаревшие / самые объёмные документы.
Всё это же доступно как JSON: `…/knowledge/active_records.json?_shape=array` (можно дёргать из скриптов/Hermes).
Записи через UI НЕ делаются (истина меняется только через CLI с audit + --approve) — это окно, не редактор.

**Как «удалять» ненужное (управление памятью):** hard-delete НЕ используется (принцип дока) —
- запись устарела/неверна → `record set-status <id> obsolete|rejected --approve` → уходит в archive,
  из default-поиска исчезает, история остаётся;
- документ не нужен в базе → добавить путь в `.ragignore` → следующий sync уводит его в archive;
- кандидатов на чистку раз в неделю приносит curator (`~/knowledge/reports/`), решение — за человеком.

## План дальше (Month-1; НЕ начато)

- Regression hunter на PR (retrieval по affected_files из resolved/regression_watch), CI-интеграция,
  approval-очередь в UI, hermes_knowledge-плагин, опционально graph-слой и Postgres/Qdrant при росте.

## Первая каноническая запись

`UAP-K-0001` — NO_PROXY exact-IP gotcha (третье место; см. `record show UAP-K-0001`) — заведена как
демонстрация полного цикла record → status transitions → audit.
