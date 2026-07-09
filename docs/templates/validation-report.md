# Validation report — <RECORD-ID>: <title>

<!-- Заполняется Validation-агентом или человеком. Регистрируется:
     knowledge record add --type validation_report --status confirmed --source <RECORD-ID> --body-file <этот файл>
     Затем переход исходной записи: knowledge record set-status <RECORD-ID> <status> --evidence "<этот отчёт>" [--approve] -->

## Input
- record: <RECORD-ID> (status at check: <status>)
- repo/ref: <repo> @ <commit>
- affected files/symbols: <...>

## Checks performed
1. Source refs still exist: <yes/no — детали>
2. Current code inspection: <файлы/строки, что реально в коде СЕЙЧАС>
3. Related tests/CI/PRs: <ссылки + их статус>
4. Non-destructive test run: <команда → результат, или "proposed: <команда>">
5. Finding vs current implementation: <совпадает / расходится — в чём>

## Anti-false-resolved checklist (все должны быть учтены)
- [ ] evidence НЕ только changelog
- [ ] evidence НЕ только закрытый issue
- [ ] переименованные файлы искал по symbol/component
- [ ] тесты relevant (не "прошли посторонние")
- [ ] branch/ref совпадает с тем, где заявлен фикс

## Verdict
- verdict: accept | revise | reject
- confidence: 0.0-1.0
- proposed transition: <from> -> <to> (requires --approve: yes/no)
- feedback_for_worker: <что улучшить в следующий раз>

## Evidence
- <kind>: <ref> — <одна строка>
