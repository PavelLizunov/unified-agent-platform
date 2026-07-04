# V3: Qwen-AgentWorld — real-data soak-eval (результаты)

_Прогон 2026-07-05. Против плана `V3_SOAK_GOAL.md`. Модель = Qwen-AgentWorld-35B-A3B GGUF на RTX 5060 Ti
(llama.cpp, localhost:8080). Грейдер везде детерминированный (греп цитат / cargo hidden-assert / exact-match),
НЕ суждение модели. Продолжает V2 (`V2_REPORT.md`) — там синтетика; здесь РЕАЛЬНЫЕ данные._

> **STATUS: IN PROGRESS** — smoke пройден (Track D 5/5, Track A offload verified на реальном репо), полный
> 4-часовой прогон запускается. Числа ниже заполняются по мере треков.

## Методика прогона

- Харнесс: `tools/offload/soak/` (`run_soak.py` гоняет A→D в цикле до таймбюджета; E = повторяемость).
- Гоча подтверждена на смоуке: модель **думает** и усекает JSON после ~3 ответов на вызов → offload-вопросы
  чанкуются по 3 (иначе пустой парс). Один вызов на 100–130KB корпус = ~150–240с (prefill доминирует).

## Результаты по трекам

### Track D — function-calling _(self-contained, exact-match name+args)_
**5/5** на смоуке: single ×3, parallel ×1, no-call ×1 — все exact-match, быстро (2–7с/вызов, без усечения).
Модель корректно эмитит tool-call по схеме, не галлюцинирует вызов на no-call. _(N≥5 повтор — в soak-цикле.)_

### Track A — offload на реальных корпусах _(дословный греп цитаты)_
Смоук на `clusters/prod/infra/*.yaml` (125KB): 3/3 verified — процитировала `tool_output_token_limit = 10000`,
`nodePort: 30880`, `nodePort: 30911` с верными номерами строк. Полный прогон (репо/логи/доки, 14 Q + 4 NOT_FOUND):
_[pending — заполнить: hit-rate дословных цитат, UNVERIFIED=галлюцинации, честность NOT_FOUND, сэкономленные токены]_

### Track B — кодинг на реальных задачах _(мои скрытые cargo-ассерты на build-1)_
_[pending — заполнить: N/N спеков проходят скрытую проверку; сравнение с V2 new-code ~96%]_

### Track C — long-context retrieval + injection _(exact-match / marker)_
_[pending — заполнить: retrieval needle ×3 глубины на 80KB; injection-resistance vs V2-дыра ~80%]_

### Track E — репитабельность / дисперсия _(Wilson CI)_
_[pending — заполнить: pass-rate ± CI по раундам soak-цикла]_

### Soak — стабильность под нагрузкой
_[pending — заполнить: часов непрерывной нагрузки, OOM/краш, дрейф tok/s]_

## Вердикт

_[pending — заполнить после полного прогона: подтверждён ли воркер/фолбэк на РЕАЛЕ, новые дыры, часов под нагрузкой]_
