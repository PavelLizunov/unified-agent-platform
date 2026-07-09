# Веб-командный центр — hermes-workspace на build-1

**Развёрнут 2026-07-09.** Первый шаг user-friendly дорожки: чат + kanban-доска роя + память + скиллы +
терминал в браузере, для владельца (и сестры) — поверх ВАЛИДИРОВАННОГО ядра (SIM-1), как и предписывал
research-док («Workspace — optional UI после валидации, не source of truth»).

## Доступ

- **UI: http://100.85.56.31:3000** (tailnet-only; build-1 не имеет публичного IP).
- Пароль: на build-1 в **`~/WORKSPACE-PASSWORD.txt`** (в чат/git не выносим). Сменить: поправить
  `HERMES_PASSWORD` в `~/hermes-workspace/.env` + `sudo systemctl restart hermes-workspace`.
- Источник истины при расхождениях — CLI/kanban/gateway, НЕ UI (правило research-дока).

## Архитектура (все — systemd, переживают ребут)

| Unit | Порт | Что |
|---|---|---|
| `hermes-gateway` | 127.0.0.1:8642 | `hermes gateway run` — messaging-гейтвей + **kanban-диспетчер** + OpenAI-совместимый API-сервер |
| `hermes-dashboard` | 127.0.0.1:9119 | dashboard API (config/sessions/skills для workspace) |
| `hermes-workspace` | 0.0.0.0:3000 | UI (node server-entry.js, prod-build vite) |

Код: `~/hermes-workspace` (clone outsourc-e/hermes-workspace, 6k★, zero-fork поверх vanilla hermes-agent);
Node 22 (nodesource) + pnpm (corepack). Установка шла через VLESS-прокси.

## Гочи (стоили времени — не повторять)

1. **API-сервер гейтвея выключен по умолчанию**: нужны env в `~/.hermes/.env` профиля гейтвея:
   `API_SERVER_ENABLED=true` + **`API_SERVER_KEY` обязателен** (без него сервер отказывается стартовать,
   даже на loopback) + `API_SERVER_HOST/PORT`. И запускать **`hermes gateway run`** (подкоманда!).
2. **prod-start workspace НЕ читает `.env` сам** — systemd-юнит обязан подавать `EnvironmentFile=`
   (или `set -a; . ./.env`). Без этого fail-closed guard остановит бинд на 0.0.0.0 (и это правильно).
3. `HERMES_API_TOKEN` в `.env` workspace = `API_SERVER_KEY` гейтвея (bearer).
4. snap на build-1 обрывается на больших пакетах (RU-сеть) — не тащить через snap ничего тяжёлого.

## Смоки после изменений

```bash
for s in hermes-gateway hermes-dashboard hermes-workspace; do systemctl is-active $s; done
KEY=$(grep ^API_SERVER_KEY= ~/.hermes/.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8642/v1/models | head -c 120   # API жив
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/                          # UI 200
```

## Дальше по user-friendly дорожке (план)

2. Телефон для сестры: её TG-ID → `TELEGRAM_ALLOWED_USERS` (managed-env прод-пода; ждёт ID от владельца).
3. Рой из чата: скилл «запусти рой на задачу X» в поде (через build1 → kanban swarm).
4. «Запомни как знание» из чата → knowledge record add (query уже прошит).
5. Стартовая страница-лендинг (ссылки: workspace :3000, база знаний :8100, дашборд Hermes, флот-карта).
