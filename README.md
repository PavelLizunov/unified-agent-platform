# Unified HA Agent Platform

Единая отказоустойчивая платформа, позволяющая заходить с **любого** устройства владельца
(Windows 11, домашний Linux-сервер, Mac) и видеть/управлять **всеми** агентскими сессиями.
Точка входа (устройство, с которого зашёл) **не должна быть точкой отказа**: упал один узел —
система продолжает работать и переназначает работу, а не встаёт целиком.

Этот пакет — **передаваемая спецификация**. Он самодостаточен: читающий агент (Codex) не
участвовал в проектировании и должен опираться только на эти файлы.

## Статус

> **Это исходная спецификация проекта (design spec), а не сводка живого состояния.** Актуальное
> оперативное состояние — в [STATUS.md](STATUS.md); актуальная карта флота (кто на какой ноде и почему) —
> в [docs/fleet-map.md](docs/fleet-map.md). Разделы ниже фиксируют изначальный замысел и намеренно не
> переписываются под каждое изменение инфраструктуры.

- **Проектирование: завершено.** Ключевые решения приняты и зафиксированы в [DECISIONS.md](DECISIONS.md).
- **Реализация: начата.** Локальный Proxmox bootstrap поднят: `uap-home-1` работает как единственный
  k3s control-plane/server, `uap-home-2` подключён как k3s agent. Из-за бюджета владелец отложил VPS и
  построение HA на неопределённый срок; текущая стратегия — один control-plane, etcd/PVC backups в R2 и
  проверенный restore drill.

## Окружение владельца

| Узел | ОС | Роль в платформе |
|---|---|---|
| Домашний сервер | Linux | единственный k3s control-plane + agent-воркер |
| VPS-1, VPS-2 | Linux (отложены) | будущие failure domains для HA, не active owner action |
| Рабочая станция | Windows 11 | agent-воркер + Ollama (большие локальные модели) |
| Ноутбук | Mac | agent-воркер + Ollama (мелкие/демо модели) |

Уже есть: **Docker**. Согласие на переход на **k3s** получено. Рабочая папка проекта на Windows:
`C:\Users\x3d_mutant\reserch`.

## Как читать этот пакет

1. **[AGENTS.md](AGENTS.md)** — инструкция агенту-исполнителю: порядок работы, что можно и нельзя.
2. **[CLAUDE.md](CLAUDE.md)** — handoff для Claude Code: текущее состояние, команды, безопасные следующие шаги.
3. **[ARCHITECTURE.md](ARCHITECTURE.md)** — целевая архитектура, схема, стек.
4. **[DECISIONS.md](DECISIONS.md)** — принятые решения с обоснованием (ADR). **Не переоткрывать без причины.**
5. **[BUILD-PLAN.md](BUILD-PLAN.md)** — поэтапный план сборки с проверяемыми вехами.
6. **[RISKS.md](RISKS.md)** — подводные камни и их смягчение.

## Основная проверка

Перед завершением инфраструктурных изменений запускать:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1
```

Матрица проверок: [runbooks/validation-matrix.md](runbooks/validation-matrix.md).

## Целевой стек (кратко)

| Слой | Технология | Зачем |
|---|---|---|
| Сеть | Tailscale (mesh); Headscale позже опционально | доступ с любого устройства, без единого шлюза-SPOF |
| Оркестратор | k3s (HA, 3 узла) | health-checks, перезапуск, VIP «из коробки» |
| Состояние | CloudNativePG (Postgres HA) + Garage (S3) | durable-стор, артефакты и backup |
| Durable execution | Restate | «замена, а не остановка» для критичных задач |
| Шлюз моделей | LiteLLM (×2) | единый OpenAI-совместимый эндпоинт, маршрутизация, fallback, учёт |
| Агенты | Claude Code (кодинг), hermes-agent (харнесс) | Hermes-legacy (bespoke) припаркован — см. DECISIONS ADR-024 |
| Дашборд | Mission Control / Restate UI | окно во все сессии (сменный модуль, не фундамент) |
| GitOps/секреты | Flux CD + SOPS/age | декларативное применение, зашифрованные секреты в git |
| Bootstrap/IaC | OpenTofu-compatible Terraform + Ansible | repeatable provisioning и настройка указанных серверов |
| Код платформы | Go-first; Rust для daemon/proxy | лёгкие бинарники, тестируемость, контроль зависимостей |

## Текущая стратегия вместо HA-старта

VPS и построение HA отложены владельцем на неопределённый срок из-за бюджета. Третий k3s server больше не
является active owner action. Рабочая стратегия сейчас:

1. Держать один k3s control-plane (`uap-home-1`, single embedded-etcd member) и один worker (`uap-home-2`).
2. Не заявлять HA: кластер остаётся single-control-plane и переживает только process/pod-level сбои.
3. Компенсировать риск R2 backups и проверенным restore drill: etcd snapshots и hermes-agent PVC backups уходят в
   R2, а restore drill 2026-07-12 доказал восстановление canary Secret с R2-снимка.

Детали — в [BUILD-PLAN.md](BUILD-PLAN.md).
