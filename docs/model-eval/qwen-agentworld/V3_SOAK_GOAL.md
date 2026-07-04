# GOAL: Qwen-AgentWorld — real-data soak-эвал (4+ ч)

_Составлено 2026-07-05. Продолжение V2 (`INDEX.md` → `V2_REPORT.md` + BFCL/AGENTIC/… результаты)._
_Заполняет пробел, отмеченный Fable: «первая неделя реального использования = недостающий эвал»._

## Тезис / цель

V2 доказал жизнеспособность **на синтетике** (agentic-кодинг 100%, new-code 96%, retrieval 100% до 128k,
injection ~80% = РЕАЛЬНАЯ дыра, BFCL single-call 90-91% / parallel 75.5%). Этот прогон:
1. **Реальные данные, не синтетика** — offload/кодинг/retrieval на настоящем репо/логах/доках.
2. **Soak 4+ ч** — устойчивая нагрузка GPU = стресс-тест стабильности (нет OOM/деградации/краша за 4ч).
3. **Добить BFCL** (simple_java/js + multi_turn/agentic) и **перемерить injection на реале**.

Модель хардкод-думает ~36с/вызов → 4 ч ≈ **~400 вызовов** — набирается с запасом.

## Модель / среда (факты)

- Qwen-AgentWorld-35B-A3B GGUF, **RTX 5060 Ti 16GB**, llama.cpp. GPU-хост = воркстанция desktop-m922ij2.
- Сервер **desktop-only**, sshd нет → remote-start невозможен; **владелец стартует** `serve-llm.ps1`. off = offload exit 4.
- Endpoint `localhost:8080` (я гоню батарею с этой же машины) / tailnet `100.114.172.40:8080`.
- `enable_thinking:false` и `--reasoning-budget 0` НЕ глушат мышление — не бороться, закладывать ~36с/вызов.
- Инструмент: `tools/offload/` + скилл `.claude/skills/uap-offload/SKILL.md` + `runbooks/local-offload.md`.

## Принципы (нерушимые — методология проекта)

1. **Грейдер только детерминированный:** дословный греп цитаты в источнике, `cargo test` exit-код + мутация,
   BFCL AST exact-match. **Никогда** — суждение самой модели и **не** self-preference платной модели.
2. **Реальные данные**, не синтетика (в этом весь смысл прогона).
3. **Wilson CI** на pass-rate (как в V2), N≥5 на ключевых.
4. **Стоп-условие:** таймбюджет **4 ч** ИЛИ полное покрытие треков — что раньше. Явный бюджет вызовов.
5. **Автономность с diagnose-not-blind-retry:** на падении — логировать причину, не долбить вслепую.

## Prereq

- [ ] Владелец: GPU свободен, `serve-llm.ps1` запущен, `offload.py health` = OK.
- [ ] Я: ресинк воркстанции к master (`git stash -u && git fetch && git merge --ff-only origin/master && git stash pop`; останется untracked `infra/ops/pve-vm.sh` — не трогать).

## Треки

### A. Offload на РЕАЛЬНЫХ данных _(≈90 мин, приоритет)_
Extract на настоящих корпусах; грейдер = дословный греп `{quote}` в `{source}:{line}`.
- **Репо** (~20 Q): «где задан X / определён Y — процитируй строку» по реальным файлам.
- **Логи** (~15 Q): дампы hermes gateway / codex `logs_2.sqlite` (крупные) — «найди ошибку про X».
- **Доки** (~15 Q): runbooks/docs.
- Метрики: hit-rate дословных цитат на реале; **честность NOT_FOUND** (вопросы без ответа → NOT_FOUND); режимы отказа; сэкономленные токены (объём входа, не вошедший в платный контекст).
- **PASS:** hit-rate ≥ 90% на найденных + 0 галлюцинаций цитат (греп ловит все ложные) + NOT_FOUND честный.

### B. Кодинг на реальных задачах _(≈60 мин)_
Rust-крейт: N функций+тестов, починка подложенных багов. Грейдер = `cargo test` + мутация (сломай → тест падает).
- **PASS:** pass-rate не ниже V2-baseline (agentic 100%, new-code 96%), мутация убивает тест.

### C. Long-context retrieval + injection на реале _(≈50 мин)_
- Реальный большой контекст (конкат репо / крупный лог) до 128k → retrieval, грейдер = exact-match.
- **Injection перемерить на реале** (дыра V2 ~80%): реальные вредные инструкции в доках/коде.
- **PASS:** retrieval ≥ 95% до 128k; injection-resistance зафиксировать честно (это измерение, не гейт).

### D. Добить BFCL _(≈60 мин)_
Недостающие Non-Live: `simple_java`, `simple_js` (полный single-call скор) + тяжёлые `multi_turn`/`agentic`.
Грейдер = BFCL AST exact-match. Гоча: BFCL засоряет hermes-venv (torch/transformers) → **отдельный venv**.
- **PASS:** зафиксировать скоры (расширение V2-таблицы), без регресса single-call.

### E. Репитабельность/дисперсия _(≈30 мин)_
Подмножество A–D, N≥5 прогонов, Wilson CI. **PASS:** CI узкие, нет «счастливых» одиночных прогонов.

### Soak (сквозь весь прогон)
Лог tok/s, VRAM, темпы (если доступны). **PASS:** нет OOM/краша/деградации tok/s за ≥4ч непрерывной нагрузки.

## Автономность

Харнесс-драйвер (расширяю `scratchpad\overnight\`): гонит A→E без присмотра, пишет `*.jsonl` сырьё +
scorecard, стоп по таймбюджету/покрытию. Грейдер отдельным проходом (грепы/exit-коды/AST). На падении —
диагноз в лог, не blind-retry.

## Deliverables

- `docs/model-eval/qwen-agentworld/V3_REALDATA_REPORT.md` — честный вердикт по трекам + Wilson CI + soak.
- Обновить `runbooks/local-offload.md` (реальные данные: что работает / где ломается).
- Обновить `INDEX.md`. Всё через PR (ops-1, green static-checks).

## Границы

- Read/generate-only; никаких деструктивных действий. Тестовые репо/файлы — во временных путях, чистить после.
- Сервер desktop-only, не always-on → durable-brain остаётся Codex; это оценка воркера/фолбэка, не замена.

---

## Scorecard (заполняется при прогоне)

| Трек | PASS/цифра | Заметки |
|---|---|---|
| A offload real | | hit-rate ___ / NOT_FOUND ___ / токенов сэкономлено ___ |
| B coding real | | pass-rate ___ (vs V2) / мутация ___ |
| C retrieval+inj | | retrieval ___ / injection ___ |
| D BFCL | | java ___ / js ___ / multi_turn ___ / agentic ___ |
| E repeatability | | Wilson CI ___ |
| Soak | | часов ___ / OOM/краш ___ / tok/s дрейф ___ |

**Вердикт:** ☐ воркер/фолбэк подтверждён на реале · ☐ найдены новые дыры (какие) · часов под нагрузкой ___
