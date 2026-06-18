# Архитектура

## Базовый принцип: две независимые плоскости

Главный источник путаницы в задаче — смешивание двух разных проблем. Они проектируются раздельно
и соединяются только в одной точке (агент дёргает модель через общий эндпоинт).

- **Плоскость A — сессии и доступ:** где живёт рабочая сессия и как зайти в неё с любого устройства.
- **Плоскость B — модели и вычисления:** какая LLM на каком железе и как переключаться при отвале.

---

## Плоскость A — сессии и единая точка входа

**Ключевой факт:** сессия живёт на хост-процессе, а клиент (терминал на ноутбуке) — это окно в неё.

1. **Сетевой фундамент — Tailscale mesh-VPN**. Каждое устройство получает стабильное имя и достижимо
   напрямую отовсюду; трафик P2P-шифрованный, а при невозможности direct-соединения есть relay fallback.
   Это и есть «зайти с любого устройства без единого шлюза». Self-hosted Headscale остаётся возможным
   путём роста, если владелец позже захочет свой coordinator.
2. **Единый control-plane (мозг)** живёт в k3s-кластере и виден по mesh с любого устройства.
3. **Дашборд** (Mission Control / Restate UI) — окно во все сессии. Сменный модуль, не фундамент.

**Hysteria Realms** не является сетевым фундаментом платформы: это допустимый аварийный/экспериментальный
канал доступа или proxy, но не underlay для k3s/etcd.

**Честная граница:** «сессия переживает смерть собственного хоста» — НЕТ без тяжёлой машинерии
(live-migration). Реалистичная цель: **система не встаёт целиком**. Узел умер → его задачи
переназначаются (для durable — продолжаются с чекпойнта; для остальных — перезапускаются). Это и есть
«замена, а не остановка» на уровне системы.

---

## Плоскость B — модели и вычисления

Единый шлюз — **LiteLLM proxy** (OpenAI-совместимый эндпоинт). Все агенты ходят в него и не знают,
какое железо реально обслужило запрос.

- **Облако — основной компьютинг** (уже высокодоступно силами провайдера):
  `default → Claude API`, `fallback → OpenRouter`.
  > ⚠️ Из РФ Anthropic/OpenAI/OpenRouter напрямую недостижимы — облачный egress идёт через не-РФ ноду или
  > VLESS-прокси (см. [ADR-018](DECISIONS.md)).
- **Локальные модели — дешёвый overflow для простых задач** ради экономии токенов Claude
  (`cheap-local → Ollama` на Mac/Windows по tailnet). HA локальному слою не нужен: упал — задача
  уходит в облако.
- **Failover** через fallback-цепочки LiteLLM (`fallbacks` + `routing_strategy`): бэкенд упал (connection error / 429 / 404) →
  автоматически следующий. Накладные расходы ~35 мс/запрос.
- **Решение «простое → локальное» принимает агент** явными правилами; LiteLLM маршрутизирует по имени
  группы моделей, а не по смыслу задачи (см. ADR-006).

---

## HA-топология

```
[ Tailscale mesh ] ── заходишь с Win/Mac/Linux, всё достижимо по имени
        │
   ╔════ k3s HA control-plane (3 server-ноды, etcd-кворум) ═══════════════╗
   ║  дом-сервер  +  VPS-1  +  VPS-2     ← переживает падение любого 1     ║
   ║                                                                      ║
   ║  • Postgres HA (CloudNativePG: 1 primary + 2 replica, авто-failover) ║
   ║  • Garage (артефакты / снапшоты)                                     ║
   ║  • Restate   ← durable execution: «замена, а не остановка»           ║
   ║  • LiteLLM ×2 → Claude | OpenRouter | cheap-local (правила + учёт)   ║
   ║  • Dashboard (Mission Control / Restate UI) ← окно (сменный модуль)  ║
   ╚══════════════════════════════════════════════════════════════════════╝
        │ tailnet            │ tailnet              │ tailnet
   [ дом-сервер ]       [ Windows ]            [ Mac ]
   agent-воркеры        agent-воркеры          agent-воркеры
                        + Ollama (большие)     + Ollama (демо/мелкие)
   всё в LiteLLM; durable: Restate (лог+RocksDB+S3-снапшоты) · Postgres (LiteLLM/учёт) · Garage (S3) · git
```

Топология «1 дом + 2 VPS» = ровно 3 server-ноды → кворум выдерживает падение **любого одного** узла,
включая полное падение дома (2 VPS держат кворум).

## HA-механизм по компонентам

| Компонент | Как достигается отказоустойчивость |
|---|---|
| Сеть | P2P-mesh; существующие линки переживают падение координатора |
| k3s control-plane | 3 server-ноды, embedded etcd, кворум 2/3 |
| Postgres | CloudNativePG: 1 primary + 2 replica, автоматический failover primary |
| Garage (S3) | на старте single-node + offsite backup; распределённый режим / erasure coding позже, когда ясна раскладка дисков |
| Restate | durable журнал в реплицируемом сторе; воркер упал → задача на другом |
| LiteLLM | 2 реплики за Service; состояние (ключи/учёт) в Postgres |
| Агенты | stateless; всё состояние снаружи; любой узел поднимает задачу |
| Облако-инференс | HA силами провайдера + межпровайдерный fallback |
| Локальный инференс | **best-effort, без HA** — намеренно (overflow) |

## Исполнительная платформа и GitOps

Платформа исполняется на **k3s**, а не на Docker Compose и не на полной vanilla Kubernetes-сборке.
Причина: нужен Kubernetes API, CRD/операторы, probes, scheduling и декларативный desired state, но без
лишней операционной тяжести.

GitOps-слой: **Flux CD + Kustomize/HelmRelease + SOPS/age**. Репозиторий должен быть читаемым для ИИ:
манифесты, overlays, encrypted secrets, tests и runbooks лежат в git; применение идёт через reconciliation.
Каждый новый controller/CRD добавляется только если он закрывает конкретную веху или риск.

## Stateless-агенты: где живёт состояние

Узел = одноразовый воркер. Всё durable-состояние — снаружи:

- история/чекпойнты задачи → журнал Restate + Postgres;
- рабочие артефакты → Garage (S3-совместимо);
- исходный код → git как источник правды (агенты часто коммитят/пушат).

## Внешние agent-воркеры

Linux control-plane-ноды входят в k3s. Windows 11 и Mac **не** являются Kubernetes-нодами: они запускают
Ollama и внешний agent-worker/worker-daemon, подключённый по tailnet к Restate/LiteLLM. Воркер публикует
capabilities (модели, GPU/CPU, RAM, online-status), держит heartbeat и может исчезать без влияния на
etcd-кворум.

Такой воркер может быть реализован на Go или Rust. По умолчанию инфраструктурный glue-код пишется на Go;
Rust предпочтителен для автономных долгоживущих daemon/proxy и security/performance-sensitive частей.

## Роль Hermes / Mission Control (контекст)

- **Hermes Agent** (Nous Research) — открытый агент-рантайм для локального исполнения, цепляется к
  Ollama / LM Studio / llama.cpp. Это то, что *крутится внутри* сессии-воркера, а не инфраструктура.
- **Mission Control** — дашборд оркестрации агентов (task dispatch, мульти-агент, учёт трат, RBAC;
  поддерживает Claude SDK, CrewAI, LangGraph). **Важно:** один self-hosted дашборд на SQLite, без
  нативного кластеринга — сам по себе НЕ HA. Поэтому он = окно поверх HA-ядра, а фундамент — Restate.

## Источники (на момент проектирования, 2026-06)

- Hermes Agent / NVIDIA: https://blogs.nvidia.com/blog/rtx-ai-garage-hermes-agent-dgx-spark/
- Mission Control: https://hermesatlas.com/projects/builderz-labs/mission-control
- k3s HA embedded etcd: https://docs.k3s.io/datastore/ha-embedded
- k3s requirements: https://docs.k3s.io/installation/requirements
- Tailscale pricing/free personal plan: https://tailscale.com/pricing
- Hysteria Realms: https://v2.hysteria.network/docs/advanced/Realms/
- Flux SOPS: https://fluxcd.io/flux/guides/mozilla-sops/
- Restate concepts / SDKs: https://docs.restate.dev/foundations/key-concepts
- LiteLLM routing/load balancing: https://docs.litellm.ai/docs/routing-load-balancing
- LiteLLM fallbacks: https://docs.litellm.ai/docs/proxy/load_balancing
