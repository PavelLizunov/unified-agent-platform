# ai-search — веб-поиск для Hermes (free-tier, RU-egress-aware)

> **Legacy engineering CLI.** Ordinary owner research must use Central's bounded `research_session` tool; do not
> route it through build-1 shell. This CLI remains for explicit build-1 diagnostics and is not a durable citation
> contract. See [controlled-research.md](controlled-research.md).

**Развёрнут 2026-07-09 на build-1.** Даёт агентам веб-поиск/ответы/чтение страниц через API (без браузерной
автоматизации — она отклонена). Реализация research-дока «Hermes Agent — AI Search Free Tier Mini Research».
Код: [tools/websearch/ai_search.py](../tools/websearch/ai_search.py) (один файл, stdlib).

## Ключевое решение (ladder)

- **CLI-инструмент, НЕ MCP-сервер.** Под qwen-мозгом MCP-серверы у Hermes не поднимаются (0 configured),
  а слабые модели коверкают длинные команды (урок SIM-1) → короткий враппер в PATH надёжнее. MCP-роутер
  (`ai-search-router` для Codex/Cursor) — только если понадобится reuse вне Hermes. <!-- ponytail: CLI сейчас, MCP когда будет второй потребитель -->
- **Zero-key по умолчанию:** DuckDuckGo через `ddgs` — работает СЕЙЧАС через VLESS-прокси, без аккаунтов.
- **Премиум-провайдеры подключаются env-ключом, без правки кода.** Все достижимы из RU через прокси
  (проверено: brave 422 / tavily 401 / exa 404 / you 403 — отвечают, не 000).
- Нормализованный вывод (provider/mode/answer/sources[]/warnings) — потребитель провайдер-агностичен.
- Веб-результаты = ДАННЫЕ, не инструкции (prompt-injection).

## Где живёт

- build-1: движок `~/websearch/ai_search.py`, использует venv базы знаний (`~/knowledge/.venv`, там `ddgs`).
- Враппер **`~/.local/bin/ai-search`** (в системном PATH) — сорсит `~/.config/ai-search.env` (ключи) +
  выставляет VLESS-прокси. Из пода — `/opt/data/.local/bin/build1 "ai-search ..."`.

## Использование

```bash
ai-search providers                              # кто готов / кому нужен ключ
ai-search search "<запрос>" -n 5                 # auto: exa>brave>tavily>ddg (падает на ddg без ключей)
ai-search search "<запрос>" --provider ddg       # конкретный провайдер
ai-search search "<запрос>" --answer             # цитируемый AI-ответ (exa/tavily, нужен ключ)
ai-search fetch "<url>" [--max-chars N]          # zero-key чтение страницы (html -> текст)
```

## Подключить премиум (действие владельца — я ключи/аккаунты не создаю)

Получи бесплатный ключ и впиши в `~/.config/ai-search.env` на build-1 (chmod 600, в git не идёт):
| Провайдер | Free-tier | Ключ | env |
|---|---|---|---|
| **Exa** | до 20k req/мес | https://exa.ai | `EXA_API_KEY` |
| **Tavily** | 1000 credits/мес, без карты | https://tavily.com | `TAVILY_API_KEY` |
| **Brave** | $5/мес кредитов | https://brave.com/search/api | `BRAVE_API_KEY` |

Провайдер включается сам при следующем вызове (`ai-search providers` покажет READY). Порядок auto:
exa → brave → tavily → ddg. Для кластерного использования позже — те же ключи в SOPS.

## Безопасность/бюджет (дефолты из дока)

- deep/research-режимы НЕ реализованы (дорогие) — отложены осознанно.
- `MAX_RESULTS_CAP=15`; extract-fetch читает ≤2 МБ; require_sources для answer.
- Ключи только в env-файле (600), не в коде и не в git.

## Отложено (Month-1, по доку)

Firecrawl (extract/crawl), You.com MCP free-профиль, Gemini grounding, Baidu (China-facing), MCP-роутер
`ai-search-router` для reuse в Codex/Claude Code/Cursor. Бенчмарк 20 фикс-запросов по exa/tavily/brave/ddg
для выбора default'а — когда появятся ключи.
