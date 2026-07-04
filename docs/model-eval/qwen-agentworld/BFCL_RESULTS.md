# BFCL v4 — Berkeley Function-Calling Leaderboard (2026-07-04)

Официальный лидерборд-бенчмарк ([BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html)), запущен против нашей
Qwen-AgentWorld-35B-A3B через её же handler (`Qwen/Qwen3-30B-A3B-Instruct-2507-FC` — та же 30B-A3B арх) на локальном
llama.cpp-endpoint. Детерминированный AST-чекер. Прогнано **1177 кейсов** Non-Live-ядра. temp дефолт.

## Реальные по-категорийные скоры (сравнимы с лидербордом)

| Категория | Accuracy | n |
|---|---|---|
| Simple AST (Python) | **90.75%** | ~400 |
| Multiple AST | **91.50%** | ~200 |
| Parallel AST | 75.50% | ~200 |
| Parallel-Multiple AST | 83.50% | ~200 |
| Irrelevance (галлюцинация) | **89.17%** | ~240 |
| **Non-Live AST (среднее 4)** | **≈85.3%** | — |

## ⚠️ Про агрегаты в CSV — НЕ скор модели
`data_non_live.csv` показывает "Non-Live Overall 70.19%", `data_overall.csv` — "Overall 11.48%". **Это артефакты
частичного покрытия:** прогнано 5 категорий из ~18; несделанные (Simple-Java, Simple-JavaScript, все Live, Multi-Turn,
Agentic, Format-Sensitivity) считаются N/A→0 и топят агрегат. Честные числа — по-категорийные выше.

## Интерпретация (место на лидерборде)
- **Single-call FC силён:** Simple 90.75%, Multiple 91.50%, Irrelevance 89.17% — конкурентно для малой MoE (3B активных).
  Это независимо подтверждает наш Ф1-результат «FC-механика сильна».
- **Parallel — слабое место: 75.50%** (эмитить НЕСКОЛЬКО вызовов за раз). Известно-трудная категория, здесь модель проседает.
- **Латентность: mean 36.25 c/кейс, p95 125 c** — тот самый thinking-налог (модель захардкожена думать, `enable_thinking:false`
  и `--reasoning-budget 0` не глушат). Для агента это дорого; подтверждает наш вывод про латентность.

## Оговорки / не сделано
- Полный офлайн-набор = **4434 кейса** → ~**12 ч** из-за обязательного thinking; сузил до канонического Non-Live-ядра.
- Для полного «Non-Live Overall» нужны ещё Simple-Java + Simple-JavaScript (~400 кейсов, ~1 ч).
- Live / Multi-Turn / Agentic / Format-Sensitivity — не прогнаны (объём/время); Multi-Turn и Agentic — самые
  показательные для north-star, но и самые тяжёлые.
- Handler — Qwen3-30B-A3B-Instruct (не-thinking вариант); наш AgentWorld думает всё равно → латентность выше «родной».
