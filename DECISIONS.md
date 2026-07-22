# Принятые решения (ADR)

Эти вопросы **закрыты** на этапе проектирования. Исполнитель следует им и не переоткрывает без явного
согласования с владельцем. Формат: Контекст · Решение · Обоснование · Отвергнутые альтернативы · Последствия.

---

## ADR-001 — Облако как основной компьютинг, локальное как overflow

> **Частично заменён (2026-06-23):** модельный слой пересмотрен — не «raw Anthropic API + Ollama», а Claude через
> subfleet/LiteLLM (ADR-023); мозг агента = Codex / **локальная FC-модель** на RTX (ADR-025). Читай как исторический
> контекст, не как текущий путь.

- **Контекст:** есть облачные LLM (Claude, OpenRouter) и локальное железо (Ollama на Mac/Windows).
- **Решение:** основной слой вычислений — **облако**. Локальные модели используются только для
  **делегирования простых задач** ради экономии токенов Claude.
- **Обоснование:** облако уже высокодоступно силами провайдера → не нужно строить HA для основного
  компьютинга. Локальное даёт экономию на простом (классификация, извлечение, суммаризация, рутинный код).
- **Отвергнуто:** «локальное — основа» (потребовало бы HA-инференс на железе, которое то включено,
  то выключено).
- **Последствия:** локальному слою **HA не нужен** (упал → задача уходит в облако). Маршрутизация
  по сложности — забота агента, не LiteLLM (см. ADR-006).

## ADR-002 — Mesh-VPN как сетевой фундамент

- **Контекст:** нужен доступ с любого устройства ко всему, без единой обязательной точки входа.
- **Решение:** **Tailscale** как стартовый сетевой фундамент. Self-hosted **Headscale** остаётся возможным
  путём роста, если владелец позже захочет свой coordinator.
- **Обоснование:** стабильные имена, P2P-шифрование, достижимость за NAT; существующие линки переживают
  падение координатора. Убирает «шлюз-SPOF».
- **Отвергнуто:** центральный SSH-бастион (сам становится SPOF); ручной VPN.
- **Последствия:** все узлы и сервисы адресуются по tailnet-именам/IP. k3s и воркеры биндятся на tailnet.

## ADR-003 — k3s HA на 3 always-on узлах (дом + 2 VPS)

- **Контекст:** цель — **настоящий HA** (не быстрый recovery). Есть один домашний Linux-сервер.
- **Решение:** k3s с **3 server-нодами**: домашний сервер + 2 дешёвых VPS (embedded etcd, кворум 2/3).
- **Обоснование:** настоящий HA control-plane требует нечётного числа ≥3 always-on узлов (кворум etcd).
  Топология «1 дом + 2 VPS» переживает падение любого одного, включая полное падение дома.
- **Отвергнуто:** один домашний сервер (это recovery, не HA — падение машины = простой);
  Windows/Mac в кворуме (их выключают → кворум разваливается); managed-облако целиком (владелец
  предпочёл своё железо).
- **Последствия:** нужны 2 VPS постоянно онлайн. Windows/Mac — только воркеры, не ноды кластера.
  Внимание к латентности etcd между домом и VPS (см. RISKS.md).

## ADR-004 — Durable execution (Restate), но гибридно

> **Статус (2026-06-23):** state-слой (Restate/Postgres/Garage) — всё ещё **design-only**; магистраль сместилась на
> вайб-кодинг через hermes-agent (ADR-022/024). Не считать Restate текущей работой без согласования с владельцем.

- **Контекст:** при отвале узла задача агента не должна теряться — для важных задач.
- **Решение:** **Restate** как durable-движок. Durable-режим включается **только для критичных/длинных**
  задач; мелкие задачи перезапускаются с нуля.
- **Обоснование:** durable execution даёт «замена, а не остановка» на уровне задачи (другой узел
  продолжает с чекпойнта). Restate проще Temporal в эксплуатации (один сервис со встроенным durable-стором
  vs тяжёлый бэкенд). Делать durable для всего — лишняя сложность написания агентов (идемпотентность).
- **Отвергнуто:** Temporal (тяжелее для личного сетапа; оставлен как путь роста); «всё durable»
  (избыточно); «ничего durable» (важные задачи терялись бы).
- **Последствия:** агенты для durable-задач пишутся под Restate SDK с идемпотентными побочными эффектами.
  Durable-журнал Restate хранится в **собственном сторе** (Bifrost-лог + локальный RocksDB + async-снапшоты в
  S3-совместимый объект-стор), а **не в Postgres** — детали и исправление прежней формулировки см. в [ADR-020](#adr-020).

## ADR-005 — Агенты как stateless-воркеры

- **Контекст:** узлы (особенно Windows/Mac) приходят и уходят.
- **Решение:** агент = **stateless-воркер**; всё durable-состояние снаружи (Restate + Postgres + Garage + git).
- **Обоснование:** иначе «HA» бутафорский — агент умрёт вместе с узлом. Stateless-воркер позволяет любому
  узлу поднять задачу.
- **Отвергнуто:** stateful-агенты с локальным состоянием.
- **Последствия:** нужен общий доступ к коду (git) и артефактам (Garage/S3); локальная ФС узла — эфемерна.

## ADR-006 — LiteLLM как шлюз; маршрутизация по сложности — на агенте

> **Уточнён (2026-06-23):** LiteLLM-группы реализованы как `smart-cloud`/`balanced-cloud`/`cheap-cloud`/… поверх
> **subfleet** (Claude-подписка), не Ollama-`cheap-local` по умолчанию (ADR-023). Главное: мозгу hermes-agent нужен
> **native function-calling** — subfleet (chat-only, дропает `tool_calls`) им быть НЕ может (ADR-025).
>
> **Superseded для текущего Flow (2026-07-15):** ADR-031 заменил эту model-routing часть на автоматическую
> OpenAI-only Luna/Sol/Terra policy; Claude, OpenRouter и local inference не являются fallback. Текст ниже исторический.

- **Контекст:** нужен единый эндпоинт, fallback и маршрутизация «простое → дёшево, сложное → Claude».
- **Решение:** **LiteLLM proxy** (×2 реплики). Группы моделей: `smart-cloud` (Claude),
  `cloud-fallback` (OpenRouter), `cheap-local` (Ollama). Выбор группы делает **агент явными правилами**
  (для старта); каскад / авто-роутер — опционально позже.
- **Обоснование:** LiteLLM маршрутизирует по имени группы, а не по смыслу задачи. Явные правила —
  предсказуемо и без лишних компонентов.
- **Отвергнуто:** ожидание, что LiteLLM сам определит сложность (он этого не делает); сразу
  semantic-router/RouteLLM (лишний компонент и риск ошибочной маршрутизации на старте).
- **Последствия:** в коде агента — правила выбора группы; учёт трат и ключи централизованы в LiteLLM+Postgres.

## ADR-007 — Дашборд = сменный модуль

- **Контекст:** нужен единый интерфейс «видеть все сессии + правила».
- **Решение:** дашборд (Mission Control или Restate/Temporal UI) — **окно поверх HA-ядра**, не фундамент.
- **Обоснование:** Mission Control на SQLite/один узел — сам по себе не HA; завязывать на него
  архитектуру нельзя. Фундамент — Restate + слой состояния.
- **Отвергнуто:** Mission Control как ядро системы.
- **Последствия:** дашборд можно заменить, не трогая ядро. На старте допустимо взять то, что быстрее завести.

## ADR-008 — k3s как исполнительная платформа, не Docker Compose и не vanilla Kubernetes

- **Контекст:** платформой будут управлять и владелец, и ИИ-агенты. Нужны декларативность, проверяемые
  вехи, HA control-plane и минимальная эксплуатационная сложность.
- **Решение:** использовать **k3s** как основную исполнительную платформу: Kubernetes API, embedded etcd,
  CRD/операторы, Helm/Kustomize/GitOps, но с меньшим количеством ручной обвязки, чем у vanilla Kubernetes.
- **Обоснование:** Docker Compose удобен для одного хоста, но слаб как HA-платформа: нет полноценного
  scheduling, operators, probes, cluster state и отказоустойчивого control-plane. Vanilla Kubernetes
  даёт те же декларативные примитивы, но требует больше решений до старта (CNI, ingress, LB, runtime,
  certs, upgrades). k3s сохраняет Kubernetes-декларативность и лучше подходит для малого homelab/edge HA.
- **Отвергнуто:** Docker/Compose как фундамент (это быстрый recovery, не HA); vanilla Kubernetes/kubeadm
  как стартовая база (операционно тяжелее для личной платформы).
- **Последствия:** инфраструктура описывается Kubernetes-манифестами/HelmRelease/Kustomize и проверяется
  через dry-run, schema validation и отказоустойчивые smoke-тесты. Docker остаётся допустимым только как
  локальный runtime/упаковка, не как оркестратор HA-платформы.

## ADR-009 — Tailscale как сетевой фундамент; Hysteria Realms только запасной канал

- **Контекст:** рассматривался вариант Hysteria Realms для NAT traversal и доступа к домашнему хосту без
  публичного IP.
- **Решение:** сетевой фундамент остаётся **Tailscale**. Hysteria Realms допускается только как
  аварийный/экспериментальный канал доступа или отдельный proxy, но не как underlay для k3s/etcd.
- **Обоснование:** Hysteria Realms решает узкую задачу: rendezvous + UDP hole punching для Hysteria
  proxy. Это не полноценная L3 mesh-сеть с identity, ACL, stable names, tags, policy tests и удобной
  Kubernetes-интеграцией. У NAT hole punching есть классы сетей, где соединение не устанавливается.
  Tailscale даёт tailnet, MagicDNS, ACL/grants, direct/relay fallback и лучше ложится на эксплуатацию ИИ.
- **Отвергнуто:** Hysteria Realms как основа кластера; публичный best-effort rendezvous как продовая
  зависимость.
- **Последствия:** k3s, Restate, LiteLLM, Ollama и agent-воркеры адресуются по tailnet. Hysteria можно
  документировать как break-glass доступ, но он не должен входить в etcd/control-plane критический путь.

## ADR-010 — Бюджетный профиль VPS допускается только через веху

- **Контекст:** идеальный минимум для k3s server-node с embedded etcd выше, чем бюджет на удалённые VPS.
  Доступны удалённые VPS порядка 1 vCPU / 1 GB RAM / 15 GB SSD, а локальные ресурсы не ограничены.
- **Решение:** разрешить **бюджетный HA-профиль**: домашний Linux-сервер несёт основные workload, две
  удалённые VPS участвуют в control-plane/etcd-кворуме в максимально лёгком режиме. Это решение считается
  принятым только если зелёная веха Этапа 1 проходит на реальном железе.
- **Обоснование:** цель проекта — личная платформа с реальным бюджетом владельца. Лучше проверить
  минимальную конфигурацию в контролируемой вехе, чем заранее требовать недоступные VPS. При этом нельзя
  скрывать риск: 1 GB RAM для server-node ниже комфортного и может не выдержать etcd/k3s под нагрузкой.
- **Отвергнуто:** считать 1 GB / 1 CPU универсально достаточным; переносить тяжёлые workload на дешёвые
  VPS; увеличивать число слабых VPS вместо нечётного устойчивого кворума.
- **Последствия:** на удалённые VPS не планировать пользовательские workload; тяжёлые компоненты
  размещать на домашнем сервере; включить жёсткие resource limits и мониторинг. Если Этап 1 не проходит,
  владелец выбирает: увеличить VPS, вынести дом из кворума и взять 3-й VPS, либо принять режим recovery
  вместо HA.

## ADR-011 — Минимизация зависимостей и GitOps через Flux + SOPS

- **Контекст:** каждый дополнительный controller/CRD/Helm chart увеличивает поверхность атаки, нагрузку на
  слабые VPS и сложность работы ИИ-агентов.
- **Решение:** вводится dependency budget. По умолчанию ставятся только компоненты, без которых нельзя
  пройти текущую веху. Для GitOps выбран **Flux CD + Kustomize/HelmRelease + SOPS/age**.
- **Обоснование:** Flux компактнее и тише для личной платформы, чем UI-ориентированные альтернативы, и
  хорошо работает с декларативным репозиторием. SOPS/age позволяет хранить секреты в git в зашифрованном
  виде; ИИ видит структуру, но не получает plaintext-секреты.
- **Отвергнуто:** ставить Argo CD, Longhorn, Rook/Ceph, kube-prometheus-stack, cert-manager, external-dns,
  Tailscale Operator и другие controllers на старте без явной необходимости для вехи.
- **Последствия:** каждый новый third-party компонент требует краткого обоснования: какую веху закрывает,
  какие ресурсы потребляет, какие CRD/RBAC добавляет, как обновляется и как удаляется. Предпочтение —
  open source, upstream charts/images, закреплённые версии и минимальные RBAC.

## ADR-012 — Языковая политика: Go-first, Rust для критичных компонентов

- **Контекст:** код платформы будут писать и сопровождать ИИ-агенты; важны лёгкость бинарей, тестируемость,
  безопасность и низкая когнитивная сложность.
- **Решение:** основной язык для инфраструктурного кода — **Go**. **Rust** разрешён и предпочтителен для
  автономных долгоживущих воркеров, сетевых daemon/proxy и security/performance-sensitive компонентов.
  Python допускается для одноразовых скриптов/анализа, но не как основной runtime.
- **Обоснование:** Go ближе к Kubernetes-экосистеме, быстрее пишется и проще ревьюится ИИ-агентами.
  Rust строже и безопаснее по памяти, но дороже в разработке; его строгая типизация полезна там, где цена
  runtime-ошибки выше цены разработки. Большинство рисков платформы лежит в идемпотентности, retry,
  RBAC, сетевой маршрутизации и конфигурации, а не только в memory safety.
- **Отвергнуто:** один язык для всего любой ценой; Python/TypeScript как основной runtime для постоянных
  системных воркеров; Rust для всего glue-кода без явной необходимости.
- **Последствия:** CLI, bootstrap tools, health-checks, Kubernetes/GitOps helpers и первые Restate
  durable-воркеры пишутся на Go. Локальный worker-daemon для Windows/Mac можно проектировать на Rust,
  если он долго живёт, следит за Ollama, публикует capabilities и держит heartbeat.

## ADR-013 — Linux-only control-plane, Windows/Mac как внешние agent-воркеры

- **Контекст:** локальные модели должны использовать железо Windows и Mac, но эти устройства могут
  выключаться и не подходят для etcd-кворума.
- **Решение:** k3s control-plane и Kubernetes-ноды — только Linux. Windows 11 и Mac — **внешние
  agent-воркеры по tailnet**, не Kubernetes-ноды.
- **Обоснование:** k3s ориентирован на Linux; Windows worker nodes в Kubernetes возможны, но это отдельная
  сложная ветка с ограничениями и не решает задачу локального Ollama лучше, чем внешний воркер. Mac как
  Kubernetes-нода фактически потребует Linux VM. Для локальных моделей нужен не kubelet, а устойчивый
  агент, который регистрирует capabilities и ходит в Restate/LiteLLM по tailnet.
- **Отвергнуто:** Windows/Mac в etcd-кворуме; Windows/Mac как k3s-ноды ради доступа к Ollama.
- **Последствия:** Windows/Mac запускают Ollama и agent-worker/worker-daemon, слушают только tailnet-IP,
  публикуют heartbeat/capabilities и могут исчезать без влияния на кластер. Durable-задачи при отвале
  продолжаются через Restate на другом доступном воркере.

## ADR-014 — Совместная разработка несколькими ИИ-исполнителями

- **Контекст:** платформу будут реализовывать не только Codex, но и Claude Code. Оба агента могут читать
  спецификацию, писать код, запускать команды и предлагать изменения.
- **Решение:** Codex и Claude Code считаются равноправными ИИ-исполнителями, но работают через общий
  контракт: git как источник правды, явное владение задачей/файлами, малые изменения, обязательные
  проверки и запрет на молчаливое перепроектирование ADR.
- **Обоснование:** несколько агентов ускоряют работу, но без координации легко получить конфликтующие
  правки, разные архитектурные трактовки и утечку секретов в промпты/логи. Общие правила важнее выбора
  конкретного агента.
- **Отвергнуто:** параллельная правка одних и тех же файлов без ownership; использование локального
  состояния агента как источника правды; “устные” решения без фиксации в ADR/BUILD-PLAN/RISKS.
- **Последствия:** каждый агент перед работой читает AGENTS.md и актуальные ADR, фиксирует область
  изменения, не трогает чужие незавершённые файлы, оставляет проверяемый результат. Секреты не передаются
  агентам plaintext и не попадают в репозиторий, логи или prompt-контекст.

## ADR-015 — Local-first bootstrap без VPS

- **Контекст:** владелец хочет начать реализацию с одного домашнего Linux-сервера, без удалённых VPS.
- **Решение:** разрешить **local-first bootstrap**: поднять один k3s server на `home-linux`, подготовить
  SSH/Tailscale/GitOps/SOPS/runbooks/tests и первые сервисы разработки. Этот режим не считается HA и не
  закрывает Этап 1.
- **Обоснование:** ждать VPS не обязательно, чтобы начать делать полезную работу: можно подготовить
  повторяемый bootstrap, проверить k3s, зафиксировать версии, skeleton репозитория, тесты и runbooks.
  По документации k3s single-node кластер можно использовать как стартовую точку; для будущего HA нужно
  перевести/держать datastore в embedded etcd и добавить ещё server-ноды.
- **Отвергнуто:** называть один домашний сервер отказоустойчивой платформой; строить полноценный стек так,
  будто VPS уже есть; завязывать архитектуру на single-node recovery.
- **Последствия:** статус до появления VPS — `local bootstrap`, не `HA ready`. Компоненты ставятся только
  если они нужны для подготовки и легко переносятся в будущий 3-node профиль. Этап 1 становится зелёным
  только после добавления двух VPS и прохождения failover-вехи.

## ADR-016 — Proxmox local-first topology

- **Контекст:** у владельца есть локальный Proxmox с двумя физическими нодами: `pve-ninitux` как основная
  и `pve-ninitux3` как запасная с ограниченным бюджетом ресурсов. Удалённая VPS может появиться позже.
- **Решение:** разрешить старт с двух локальных VM: `uap-home-1` на `pve-ninitux` и `uap-home-2` на
  `pve-ninitux3`. После появления удалённой VPS целевая quorum-топология может быть
  `uap-home-1 + uap-home-2 + uap-vps-1`.
- **Обоснование:** две локальные Proxmox-ноды позволяют начать с реальных Linux-серверов, проверить
  provisioning, SSH hardening, k3s bootstrap и частичный failover до покупки удалённой VPS.
- **Отвергнуто:** считать две локальные VM полноценной защитой от отказа дома; держать только две
  server-ноды etcd как “почти HA” на длительный срок.
- **Последствия:** до появления третьей ноды нельзя заявлять k3s HA. Топология `2 local + 1 remote`
  переживает отказ любой одной ноды, но не переживает полный отказ локальной площадки.

## ADR-017 — OpenTofu/Terraform + Ansible как воспроизводимый bootstrap-слой

- **Контекст:** платформу нужно быстро разворачивать на указанных серверах, а не только вручную повторять
  текущий локальный bootstrap. При этом важно не смешивать создание VM/VPS, настройку ОС и GitOps-содержимое
  Kubernetes в один хрупкий скрипт.
- **Решение:** использовать **OpenTofu-compatible Terraform-конфигурации** для provisioning и **Ansible** для
  configuration management. OpenTofu — путь по умолчанию из-за open-source модели; Terraform совместим и допустим
  как CLI-альтернатива. Flux/SOPS остаётся владельцем Kubernetes-содержимого после bootstrap.
- **Обоснование:** OpenTofu/Terraform лучше всего описывает низкоуровневую инфраструктуру: VM, диски, сеть,
  cloud-init и outputs. Ansible лучше подходит для повторяемой настройки Debian, SSH, Tailscale, k3s и Flux
  поверх уже доступного SSH. Разделение упрощает тестирование: `tofu validate/plan`, `ansible --syntax-check`,
  idempotency-run и smoke-тесты кластера проверяют разные уровни.
- **Отвергнуто:** настраивать k3s через Terraform `remote-exec`; держать всё в одном bash/PowerShell-скрипте;
  создавать отдельный custom bootstrap tool до появления реальной сложности, которую не закрывают OpenTofu/Ansible.
- **Последствия:** граница слоёв фиксируется в репозитории:
  - `infra/tofu` — только provisioning и outputs;
  - `infra/ansible` — OS/Tailscale/k3s/Flux/SOPS bootstrap;
  - `clusters/prod` — GitOps-содержимое Kubernetes;
  - `tests` — static checks и smoke-тесты.
  Секреты для Proxmox/VPS/Tailscale/Ansible Vault не коммитятся; `.tfvars`, state и vault helpers игнорируются.

## ADR-018 — Egress к облачным LLM через цензуроустойчивый прокси

- **Контекст:** домашняя площадка находится в России, откуда `api.anthropic.com`, `api.openai.com` и
  `openrouter.ai` напрямую недостижимы (сетевые блокировки + гео-ограничения провайдеров). OpenRouter эту
  блокировку не обходит. Это не было учтено в исходном дизайне Плоскости B — пробел зафиксирован фактчеком 2026-06.
- **Решение:** исходящий трафик к облачным LLM идёт только через отдельный egress-путь, изолированный от
  k3s/etcd/Flux. Два режима:
  - **План A (предпочтителен, когда есть зарубежная нода):** реплики LiteLLM закрепляются на не-РФ k3s-ноде
    (`nodeSelector`/affinity) и ходят в Anthropic/OpenRouter напрямую; агенты идут в LiteLLM по tailnet.
    Цензуроустойчивый прокси в пути API при этом не нужен.
  - **План B (нужен на Stage 0P, пока зарубежной ноды нет):** в кластере поднимается egress-шлюз
    `xray-egress` (Xray-core, **VLESS + XTLS-Vision + REALITY**, ≥2 реплики), отдающий SOCKS5/HTTP-прокси;
    LiteLLM направляет в него egress (`HTTPS_PROXY` / per-model client). VLESS-сервер — на дешёвой не-РФ VPS.
- **Обоснование:** в зарубежный egress нуждается только LiteLLM, поэтому туннелируется именно LLM-трафик, а не
  весь нод — иначе k3s/etcd/Flux получают лишнюю латентность и точку отказа. VLESS+REALITY — текущий
  best-practice против DPI РФ/КН (маскировка под реальный TLS-сайт, без своего домена/серта).
- **Отвергнуто:** гнать весь исходящий трафик кластера через прокси; полагаться на OpenRouter как обход
  блокировки; ставить egress-прокси в путь etcd/Flux.
- **Последствия:** egress становится SPOF Плоскости B → держать ≥2 эндпоинта в разных ASN/странах + health-check.
  Исторический `cheap-local` fallback для текущего Flow superseded ADR-031: маршрут делает bounded retry и fail-closed,
  а local inference/GPU остаётся owner-gated. Секреты VLESS
  (UUID, REALITY-ключи, адрес сервера) — через SOPS/age, не в git. Зарубежная VPS из Этапа 0 получает двойную
  роль (кворум + egress), что повышает её приоритет. Для Plan A egress-нода должна быть **адекватного профиля**
  (НЕ «тонкий» 1 ГБ etcd-VPS — см. BUILD-PLAN, Этап 2 → размещение). Связанный риск — достижимость самого
  Tailscale из РФ (см. RISKS): Headscale из «опции роста» становится хеджем.

## ADR-019 — Объектное хранилище: Garage вместо MinIO

- **Контекст:** в исходном дизайне S3-совместимым хранилищем (артефакты, чекпойнты, snapshot-таргет, бэкапы)
  был MinIO. К 2026-06 MinIO community-edition фактически свёрнут: админ-консоль вырезана (сер. 2025),
  официальные образы остановлены (окт. 2025), режим maintenance (дек. 2025), GitHub-репозиторий
  заархивирован (фев. 2026) — без дальнейших security-патчей.
- **Решение:** объектное хранилище — **Garage** (Deuxfleurs, AGPLv3): один статический бинарь, ~1 ГБ RAM,
  ARM-friendly, рассчитан на geo-distributed-кластеры из неравных нод. Разворачивается как обычный StatefulSet
  без оператора/CRD. Альтернатива при необходимости Apache-2.0 / иного профиля нагрузки — **SeaweedFS**.
- **Обоснование:** Garage легче и проще MinIO для маленькой self-hosted-площадки, активно поддерживается, не
  тянет операторов и CRD (укладывается в dependency budget, ADR-011). Подходит как S3-таргет для k3s
  etcd-снапшотов, артефактов и **async-снапшотов Restate** (ADR-020).
- **Отвергнуто:** оставлять архивный MinIO (нет патчей); ставить Rook/Ceph (тяжёлый набор, уже отвергнут в
  ADR-011) на старте.
- **Последствия:** Этап 2 и связанные runbook'и переписываются под Garage. Erasure coding включается отдельным
  шагом, когда ясна раскладка дисков (EC стартует с 2 дисков; 4/нода — рекомендация, не минимум); на старте
  допустим однонодовый Garage + offsite-бэкап. Замечание: у Garage нет S3 Object Lock — если понадобится
  WORM-ретенция бэкапов, это отдельное решение.

## ADR-020 — Модель durable-хранилища Restate (не Postgres)

- **Контекст:** BUILD-PLAN и ARCHITECTURE местами указывали, что durable-журнал Restate пишется в Postgres из
  Этапа 2. Фактчек 2026-06 показал, что это ошибка: Restate так не работает.
- **Решение:** durable-слой Restate описывается корректно: источник правды — quorum-реплицированный
  write-ahead log (**Bifrost**); состояние материализуется в **локальный эфемерный RocksDB** на каждой ноде,
  детерминированно выводимый из лога; периодические **async-снапшоты** RocksDB уходят в **S3-совместимый
  объект-стор** (Garage, ADR-019). Метадата-стор — внутренний Raft. Внешний Postgres Restate **не использует**.
- **Обоснование:** так устроен Restate (подтверждено офиц. документацией). Postgres из Этапа 2 остаётся за
  LiteLLM (ключи/учёт) и потенциальным бэкендом дашборда, но не за журналом Restate.
- **Отвергнуто:** маппить durable-журнал Restate на CloudNativePG.
- **Последствия:** зависимость durable-ядра Restate — на объект-стор (Garage), не на Postgres; правки внесены в
  ADR-004, ARCHITECTURE и BUILD-PLAN. Версия runtime фиксируется (v1.6.x); лицензия: runtime — **BSL**
  (source-available, не OSI), SDK — MIT; k8s-HA — через `restate-operator`.

## ADR-021 — k3s поверх Tailscale: flannel-iface, не нативный vpn-auth

- **Контекст:** для k3s поверх tailnet за NAT есть три варианта меж-нодной/etcd-связности.
- **Решение:** использовать **flannel поверх интерфейса `tailscale0`** (`--flannel-iface=tailscale0` +
  `--node-ip=<tailnet-ip>` + `--advertise-address=<tailnet-ip>` + `--tls-san=<tailnet-ip>`) — стабильный,
  проверенный путь, на котором уже работает локальный bootstrap.
- **Обоснование:** нативный k3s `--vpn-auth` (Tailscale-интеграция) в середине 2026 всё ещё **experimental** и
  не годится как фундамент HA; Tailscale Kubernetes Operator решает Ingress/egress, но **не является CNI** для
  меж-нодного/etcd-трафика.
- **Отвергнуто:** нативный `--vpn-auth tailscale` как основа кластера; Tailscale Operator как замена CNI.
- **Последствия:** число etcd-членов держать **нечётным** (≥3 на разных площадках). При выходе `--vpn-auth` из
  experimental — пересмотреть отдельным ADR.

## ADR-022 — Северная звезда: вайб-кодинг; self-test = гейт качества

- **Контекст:** владелец даёт идеи + инфраструктуру и **не ревьюит сгенерированный код**.
- **Решение:** основная цель платформы — **вайб-кодинг**: агент превращает идею в *проверенный* развёрнутый код. Раз
  человек код не смотрит, **собственная самопроверка агента (тесты/прогон/верификация) И ЕСТЬ контроль качества**.
- **Обоснование:** без ревью единственный заслон от регрессии — автоматический гейт; «готово» = тесты зелёные, а не
  «выглядит правильно».
- **Отвергнуто:** полагаться на ручное ревью владельца; honor-system без enforcement.
- **Последствия:** гейт обязан быть **enforced** (ADR-026), покрывать **код**, а не только infra-YAML, и каждое
  изменение приезжает со своими тестами. См. `docs/next-steps.md` (Platform hardening).

## ADR-023 — Модельный бэкенд: subfleet за LiteLLM (чат), не мозг агента

- **Контекст:** нужен доступ к Claude-подписке как к API.
- **Решение:** **subfleet** оборачивает Claude-подписку в OpenAI-совместимый **чат**-API (спавнит `claude` CLI на
  запрос), за ним **LiteLLM** как шлюз. subfleet **сохраняется для ДРУГИХ проектов владельца** (Telegram-бот +
  веб-сессии).
- **Обоснование:** subfleet даёт чат, но **дропает `tool_calls`** (CLI — монолитный агент, не сырая модель), поэтому
  для in-repo кодинга он **избыточен** — кодинг идёт через `claude -p` напрямую.
- **Отвергнуто:** делать subfleet/LiteLLM основным путём вайб-кодинга; направлять на него мозг hermes-agent (он
  FC-less → все тулзы молча отключаются — доказано тестом эндпоинта: `finish_reason=stop, tool_calls=null`).
- **Последствия:** OpenAI-мост subfleet не на критическом пути проекта; переиспользуем его egress + headless-auth.

## ADR-024 — Харнесс вайб-кодинга: внешний NousResearch hermes-agent (bespoke Hermes припаркован)

- **Контекст:** нужен агент-харнесс с телефоном, памятью, скиллами, субагентами, cron.
- **Решение:** принять **внешний `NousResearch/hermes-agent`** (MIT) как харнесс. Наш bespoke `hermes/hermes.py`
  (**«Hermes-legacy»**) **припаркован** как фоллбэк.
- **Обоснование:** hermes-agent уже делает всё нужное (Telegram outbound long-poll — дружелюбно к RU/NAT, локальная
  SQLite/FTS-память, субагенты, cron, песочница) **и содержит встроенный скилл `claude -p`** — автономный
  кодинг-воркер, который мы собирались строить. Перебивает по возможностям, поддерживается Nous.
- **Отвергнуто:** достраивать bespoke Hermes до полноценного харнесса с нуля. (Имя «Hermes» — совпадение; это РАЗНЫЕ
  проекты — конвенция: Hermes-legacy vs hermes-agent.)
- **Последствия:** новые силы — в hermes-agent. Цитаты/детали: `docs/research/nousresearch-hermes-agent.md`.

## ADR-025 — Мозг hermes-agent: Codex codex_app_server ИЛИ локальная FC-модель; кодинг = claude -p + codex exec

- **Контекст:** hermes-agent **требует нативный function-calling** и не имеет prompt-based фоллбэка.
- **Решение:** мозг = **ChatGPT/Codex-подписка** через рантайм **`codex_app_server`** (нативный FC, без API-ключа,
  OAuth) **или** **локальная FC-модель** (Hermes/Qwen, vLLM `--tool-call-parser hermes`, ≥64k ctx) на RTX 5060 Ti.
  Кодинг = скиллы **`codex exec`** (основная текущая ёмкость подписки: x20) + **`claude -p`**
  (второй движок; текущая подписка не Max), с обязательной записью точного model ID отдельно от тарифа/квоты.
- **Обоснование:** Codex CLI — управляемый app-server, его можно поставить мозгом; Claude-CLI такого рантайма в
  hermes-agent не имеет. GPU-десктоп не круглосуточный → Codex-подписка = надёжный основной мозг, локальная модель =
  резерв.
- **Отвергнуто:** Claude-подписка как мозг (FC-less); платный API как мозг по умолчанию (дорого на оркестрации);
  impersonation-прокси к Codex (бан-риск).
- **Последствия:** мозг — одна строка конфига (сменный); egress нужен для Codex/Claude из РФ. Цитаты:
  `docs/research/hermes-codex-subscription-brain.md`.

## ADR-026 — Репозиторий публичный; CI-гейт обязателен через ruleset (деплой через PR)

- **Контекст:** при «агент шипит неревьюенный код» Flux (`prune:true`) катит в кластер **что угодно из `master`** —
  любой push = cluster-admin RCE; на приватном free-репо rulesets/branch-protection недоступны (нужен Pro —
  проверено: API `403`).
- **Решение:** репозиторий сделан **публичным** (история предварительно проверена — реальных секретов нет, только
  ложняки: паттерны самого сканера + ссылка на префикс токена в доке), включён бесплатный **ruleset
  `protect-master`** (id 18025090): на `master` обязателен **PR + зелёный `static-checks`**; force-push и удаление
  ветки заблокированы.
- **Обоснование:** это **enforce**-ит ADR-022 (тесты = гейт), закрывает RCE-дыру **бесплатно** и делает репо
  публичным портфолио/референсом. Pro ($4/мес) и приватность держать смысла не было.
- **Отвергнуто:** GitHub Pro на приватном репо; оставить `master` без enforcement; CI-gated deploy-ветка (сложнее
  без выгоды, когда репо уже публичный).
- **Последствия:** **прямой `git push origin master` отклоняется** (включая deploy-key ops-1) — все изменения через
  PR (`ветка → push → gh pr create → CI → gh pr merge → Flux`); обновлён скилл `uap-commit-push`; закрыт residual
  «branch protection» в STATUS/BACKLOG. CI = `.github/workflows/ci.yml`.

## ADR-027 — Временный fail-closed compatibility patch для pinned hermes-agent

- **Контекст:** в закреплённом внешнем `NousResearch/hermes-agent` v0.18.0 подтверждены дефекты интеграции:
  password-only dashboard provider ошибочно запускает OAuth/SSO route (M9), а Codex `exec_command` с результатом
  `[exit N]` не классифицируется как failure и не включает loop guardrail (M11). Дополнительный behavioral-тест
  показал, что `codex_app_server` принимает turn без terminal assistant response за success, а quiet CLI возвращает
  exit 0 для `partial`/`completed=False` (M9/M11/M12). Telegram/dashboard UAT также выявил два upstream-дефекта:
  Codex `userMessage` повторно сохраняется поверх уже durable user-turn, а новый dashboard-chat не записывает
  `session_id` в URL, поэтому reload не посылает `session.resume` и сессия закрывается как `ws_orphan_reap`.
- **Решение:** сохранить официальный image digest и перед стартом gateway копировать затронутые upstream-файлы
  в `emptyDir`, применять к копиям идемпотентный GitOps-owned patch и монтировать их обратно через `subPath`.
  Patch обязан применяться только к точно известным исходным фрагментам и останавливать initContainer при любом
  несовпадении; оба контракта покрываются hermetic mechanism-тестом. После появления upstream-исправления patch
  удаляется одновременно с обновлением image digest.
- **Обоснование:** это минимальный обратимый мост без форка, собственного image/registry и изменения s6 entrypoint.
- **Отвергнуто:** оставить известные behavioral FAIL; лечить prompt/config; собирать постоянный fork; делать
  непроверяемый runtime monkeypatch.
- **Последствия:** обновление image digest требует сначала удалить patch либо подтвердить его fail-closed
  fingerprint; до этого compatibility layer является явно учтённым временным долгом.
  Для `codex_app_server`, где внутренним tool loop владеет subprocess Codex, те же thresholds применяются к
  `item/completed` событиям адаптера; при достижении порога активный Codex turn прерывается контролируемо. Turn,
  завершившийся после tool result без terminal assistant response, становится partial и retire-ит Codex session;
  quiet CLI возвращает non-zero для failed, partial и incomplete results. Echoed Codex `userMessage` не входит в
  durable transcript, а dashboard сохраняет текущий `session_id` как `?resume=` сразу после `session.info`.

## ADR-029 — Central Hermes Workspace split (2026-07-14)

- **Контекст:** the tailnet-only Workspace on `uap-build-1` must present the central k3s hermes-agent while the local build-1 services remain the Hermes Flow v2 Kanban dispatcher and CLI/orchestrator infrastructure.
- **Решение:** central k3s Hermes is the user-facing Workspace backend; local build-1 Hermes remains Flow infrastructure. Workspace uses a small, exact-commit, fail-closed external overlay. There is no permanent upstream fork.
- **Обоснование:** this keeps one user-facing dashboard/Kanban source of truth and avoids duplicating the dispatcher or maintaining a fork.
- **Отвергнуто:** exposing build-1's local models/game/update surface in the central UI; replacing the local Flow dispatcher; a permanent fork or custom image.
- **Последствия:** the overlay is reversible and must be removed when upstream provides equivalent switches/auth support. The central gateway API is exposed only on the tailnet NodePort with its bearer key from SOPS; dashboard password session cookies remain in Workspace process memory.

## ADR-028 — Hermes Flow v2: Kanban, quota-aware routing и независимое review

> **Маршрутизация заменена ADR-031 (2026-07-15):** Kanban, guarded worktrees, SHA-bound review и CI-гейты
> сохраняются; Claude/quota gate и owner approval для выбора Luna/Sol/Terra больше не являются рабочим путём.

- **Контекст:** восьмичасовая Spark Runner mission дала пять зелёных PR, но прошла через 22 отдельные
  `chat/--resume`-сессии, 713 последовательных tool calls и активные подсказки внешнего monitor. Отдельный
  reviewer-agent и Hermes Kanban swarm не использовались; Claude Code вызывался как редактор, а не verifier.
  Один checkpoint попал не в тот репозиторий, четыре сессии завершились tool guardrail. При этом UAP уже
  доказал Kanban DAG, verifier, retries и durable artifacts в изолированном пилоте.
- **Решение:** multi-checkpoint/длинные coding missions исполняются через родной Hermes Kanban swarm, не
  цепочкой `chat --resume`. Роли разделены: orchestrator строит DAG, author пишет только в allowlisted worktree,
  read-only reviewer другой model family проверяет фактический diff/тесты, required CI остаётся финальным
  детерминированным гейтом. Author создаёт `summary.json`, reviewer — `verification.json`, привязанный к точному
  HEAD SHA; новый commit инвалидирует review. Merge разрешён только при `verdict=accept`, зелёном CI и совпадении
  reviewed SHA. Terminal state наступает только после merge, подтверждения default branch и cleanup ветки/worktree.
  При `codex exec --sandbox workspace-write` author только меняет файлы и запускает тесты: реальный commit из
  явного allowlist создаёт orchestrator после повторной проверки. Копировать/подменять `.git` запрещено; заявленный
  SHA принимается только если его возвращает `git rev-parse HEAD` внутри guarded worktree.
- **Маршрутизация:** Codex x20 — основная coding capacity; exact Spark используется там, где он является gate.
  Claude Code — независимый reviewer/второй engine, но при известном исчерпании квоты не запускается: circuit
  breaker переводит маршрут в Codex или `review_blocked`. Локальные модели разрешены только для явно одобренных
  low-risk задач; они не заменяют cloud-review для infra/security. Model ID, тариф и quota state — разные поля.
- **Ограничения:** cross-family review остаётся нормой. По решению владельца от 2026-07-13 для `standard_code`
  при `quota_blocked` Claude разрешён явно маркированный `same_provider_degraded` fallback: reviewer запускается
  read-only в отдельной Codex-сессии на другой exact model. Для infra/security/secrets этот fallback запрещён.
  Reviewer не правит код. Максимум два
  review/fix цикла, затем честный `blocked`. Перед записью обязательны guard-проверки repo root, remote, branch и
  worktree. Нельзя делать расходующий пустой Claude probe; интерактивный `/usage` или реальный rate-limit response
  только обновляют circuit breaker.
- **Обоснование:** переиспользуется уже работающий Kanban вместо нового workflow engine. Cross-model review снижает
  коррелированные ошибки, SHA binding убирает stale approval, а hard repo guard закрывает весь класс CP6 misroute.
- **Отвергнуто:** новый orchestrator/БД/GitHub App; self-review той же моделью и той же сессией как эквивалент
  независимого review;
  бесконечные retries; парсинг недокументированного quota API; запуск локальных моделей без разрешения владельца.
- **Последствия:** контракт и команды описаны в `runbooks/hermes-flow-v2.md`; машинная политика —
  `tools/swarm/flow-policy.json`; stdlib validator/circuit breaker — `tools/swarm/flow_contract.py`. Сначала
  отдельный безопасный pilot repo и behavioral gates; production/Flux меняются только отдельным PR после пилота.

## ADR-030 — Единый Hermes mission plane и автономный Product Operating Contract

- **Контекст:** владелец задаёт продуктовую цель, но не является разработчиком, оператором, ревьюером или ручным
  тестировщиком. Workspace и Telegram должны быть двумя синхронными окнами одной системы. ADR-029 оставил central
  Hermes пользовательским backend Workspace, но сохранил local build-1 Hermes как отдельную Flow infrastructure;
  фактически это даёт два контура состояния и не обеспечивает единый путь goal → mission → workers → verified result.
- **Решение:** принять [`docs/product-operating-contract.md`](docs/product-operating-contract.md) как нормативный
  продуктовый контракт. Внешний NousResearch `hermes-agent` из ADR-024 остаётся основой агентного слоя и **единственным
  источником истины** для sessions, missions, status и events. Workspace и Telegram являются представлениями одного
  central Hermes. Flow/Kanban, swarm, coding agents, test VM и `uap-build-1` становятся execution plane центральной
  mission и возвращают события под тем же `mission_id`; они не имеют второго пользовательского mission store.
- **Уточнение ADR-029/028:** сохраняются central Workspace backend, reversible overlay, Kanban/DAG, guarded worktrees,
  quota-aware routing и SHA-bound review. Отменяется только смысл независимого local Hermes control/state plane.
  Build-1 остаётся always-on executor/dispatcher, но не второй точкой управления. Любое несовместимое изменение
  upstream Hermes сначала доказывается узким adapter/overlay; новый replacement-orchestrator не создаётся, пока
  невозможность расширить Hermes не подтверждена тестом и отдельным ADR.
- **Автономность:** постановка mission разрешает обычные repo-contract workers, тесты, review, PR/CI и
  deploy/release/post-verify. Отдельное согласие сохраняется для новой model/provider policy, Windows/GPU, destructive
  tests, credentials/external authority и необратимых продуктовых/архитектурных решений.
- **Инженерная форма:** сначала модульный монолит и минимальные зависимости; сервис выделяется только по доказанной
  границе isolation/scaling/security/lifecycle. Не переписывать Hermes и существующий Python wholesale. Новые
  production daemons/state machines — Rust по умолчанию, малые infra tools — Go, существующий Workspace UI — его
  TypeScript/web stack. Новый Electron запрещён по умолчанию.
- **Отвергнуто:** заменить Hermes отдельным Rust control plane; поддерживать два независимых Hermes mission stores;
  превращать владельца в оператора; автоматически использовать личный GPU; строить новый dashboard до исправления
  mission/event contract.
- **Последствия:** текущий runtime ещё не соответствует ADR. Миграция идёт малыми PR по Phase A6 в
  `docs/next-steps.md`; сначала contract/state mapping и offline tests, затем один central mission, build-1 executor
  adapter, синхронные Workspace/Telegram views и только после этого controlled end-to-end canary. Spark Runner остаётся
  остановленным до отдельного решения владельца.
  Successful delivery также должна оставлять проверяемый машиной, а не только вручную написанный evidence record.
  Для зарегистрированного профиля coordinator после Central terminal, cleanup и archive записывает owner-only closed
  JSON bundle: mission/route/runtime hashes, постоянного размера systemd invocation hash-chain, exact Git и PR/CI
  identities, runtime-derived author/reviewer attestations, post-verify, cleanup и Central projection. Bundle имеет
  canonical SHA-256 и отдельный semantic verifier; restart либо воспроизводит ещё не зафиксированный bundle, либо
  только проверяет уже сохранённый. Systemd identity доказывает service boundary, но сама по себе не доказывает timer
  origin и не заменяет signed GitHub attestation, channel cursors или live canary. Не реализованные `deploy/release`
  modes по-прежнему fail-closed; bundle для pilot допустим только при явном `delivery_mode: none`.
  Bundle schema v2 для нового registered ordinary intake дополнительно связывает server-owned channel
  (`workspace`/`telegram`), full source-key SHA-256 и source-message SHA-256 с детерминированным `mission-intake-*`;
  raw channel/message identity в evidence не пишется. Verifier сохраняет closed-schema совместимость с уже
  выпущенными v1 bundles.

## ADR-031 — Автоматическая OpenAI-only маршрутизация без оператора

- **Контекст:** первая `codex-quality-v1` policy оставляла Claude в стандартном маршруте и возвращала
  `owner_approval_required` для Sol/Terra. Это противоречило ADR-030: владелец снова выбирал модель и разрешал
  обычные повторы вместо постановки одной продуктовой цели.
- **Решение:** рабочий delivery route использует только уже доступную ChatGPT/Codex-подписку и три постоянно
  разрешённых маршрута: `standard` = Luna author / Sol reviewer, `complex` = Sol / Terra, `escalated` = Terra / Sol.
  Платформа детерминированно выбирает сложность, reasoning effort, retry и escalation. Все reviewer runs используют
  отдельную read-only session, exact candidate SHA и runtime-derived model/sandbox attestation. Один OpenAI provider
  является принятой продуктовой политикой, а не degraded mode.
  Author и reviewer дополнительно запускаются внутри parent-bound transient user-systemd units. Linux mount/proc
  namespace делает filesystem/home read-only, скрывает unrelated processes, маскирует common credential stores и
  удаляет control-plane credential environment. Author может писать только в свой disposable worktree, mission-local
  model home и Codex runtime home; reviewer — только в последние два, а его exact-SHA checkout остаётся read-only.
  Ошибка установки любой границы fail-closed останавливает model turn; новый сервис или provider не создаётся.
  `openai-autonomy-v2` считает failed author gate, independent-review rejection, required-CI failure или истечение
  bounded CI timeout одним quality-failure signal. Дополнение от 2026-07-16 явно подтверждено владельцем: ошибка
  компиляции/теста до commit является таким же сигналом недостаточной текущей route, поэтому следующий bounded author
  retry автоматически повышает модель без отдельного вопроса владельцу. Диагностика перед сохранением, логированием и
  передачей следующей модели redacted и ограничена по размеру:
  после первого сбоя следующий цикл получает `complex`, после второго — `escalated`. Coordinator сохраняет раздельные
  счётчики причины и не просит владельца исправлять CI. До первого commit/PR исчерпание author-gate retries сохраняет
  только redacted bounded diagnostics и завершается после локальной очистки без несуществующего PR evidence. После
  создания PR coordinator повторно использует тот же PR/branch: номер PR, head SHA и base branch являются durable
  identity, а repair push использует exact-head lease. Обычный профиль сохраняет три bounded correction retries;
  сложный профиль может зафиксировать до семи, а canonical contract fail-closed отклоняет `review_cycle > 8`.
  GitHub не предоставляет server-side compare-and-swap для unsafe PR-close, поэтому после исчерпания профильного
  bounded budget coordinator с действующим Kanban claim
  повторно проверяет identity и сохраняет
  открытый failed PR вместе с exact remote branch как bounded evidence, не пытаясь закрыть его после локального
  read/check. Если PR уже закрыт внешне, совпадающая branch/SHA удаляется exact lease. Локальный disposable state
  удаляется, delivery публикуется как failed, mission завершается честным failure.
  Capacity — operational failure, а не quality signal. Точная известная capacity-ошибка из terminal Codex envelope
  или stderr допускает два bounded same-model retry; до появления candidate author затем переключает только весь
  следующий уже разрешённый tuple (`standard` → `complex` → `escalated`). После candidate SHA reviewer route
  заморожен и повторяется в новой read-only session на том же exact SHA. Исчерпание текущего burst сохраняет
  restart-safe `not_before` и автоматически начинает следующий bounded round с capped backoff; owner question не
  создаётся и quality counters не меняются. На время cooldown coordinator переводит exact Kanban task в `scheduled`,
  освобождая конечный claim TTL, а при наступлении `not_before` автоматически создаёт новый exact run той же task.
  Текст из prompt, agent/tool output, неточное сообщение, начавшийся turn
  или изменившийся worktree не разрешают fallback: такой результат остаётся fail-closed/ambiguous, чтобы не запустить
  второго writer. Claude, local/GPU и произвольная actor pair не являются capacity fallback.
- **Граница полномочий:** расход подписки или денег, выбор Luna/Sol/Terra, штатные workers/tests/VM, PR/CI/merge и
  предусмотренный repo-contract deploy/release не требуют подтверждения. Owner gate остаётся только для реальной
  опасности или новой власти: destructive/необратимая потеря данных, выход за поставленную цель, изменение закрытой
  architecture/security boundary, новые credentials/external authority, новый provider/Claude, local inference/GPU
  и destructive/chaos/failover test с риском для недиспозабельного состояния.
- **Pre-execution owner question:** `architecture_change` — единственный текущий owner-gated signal, который
  coordinator может самостоятельно разрешить после ответа: сначала создаётся inert sticky-blocked root, затем один
  deterministic `mission.question`. Central принимает только точное `APPROVE`; approval связывается с exact
  mission/goal/policy и тем же root до любого model turn. Потерянный HTTP response повторяет тот же producer event.
  `destructive`, credentials/external authority, new provider/Claude и local/GPU не становятся разрешёнными от
  свободного текста и по-прежнему fail-closed до отдельной capability/setup границы.
- **Обоснование:** это убирает владельца из execution loop, использует уже оплаченный надёжный маршрут и сохраняет
  независимость review через session/SHA/read-only/runtime boundaries без нового сервиса или провайдера.
- **Отвергнуто:** Claude как default reviewer; подтверждение каждой более сильной OpenAI-модели; локальная модель как
  автоматический fallback; semantic-router или новый workflow engine.
- **Последствия:** `delivery_model_policy` является OpenAI-only и fail-closed для неизвестных/опасных capability;
  прежние quota-aware `route`/`quota-set` и Claude/local routes удалены из исполняемого Flow contract. A7 coordinator
  обязан использовать `delivery-route`. Raw CI logs не становятся durable prompt/state: сохраняются только bounded
  check-name/outcome metadata, а author повторно запускает repo-contract gates. ADR-028 superseded только в части
  model routing/review-mode; ADR-030 owner gates уточнены этой ADR.

## ADR-032 — Зарегистрированные проекты и owner-safe выбор репозитория

- **Контекст:** ordinary Workspace/Telegram intake был доказан только для одного заранее выбранного delivery profile.
  Владелец не мог безопасно выбрать `vpnctl`, `VPNRouter` или другой уже разрешённый репозиторий: передача пути либо
  `dispatch_profile` из браузера/сообщения разрушила бы server-owned authority, а запуск модели только для определения
  репозитория добавил бы недетерминированность до durable mission.
- **Решение:** Central Hermes хранит закрытый `HERMES_MISSION_PROJECTS` catalog. Каждая запись связывает публичные
  `project_id`/label/repository/aliases с точным server-owned schema-v4 profile и `delivery_mode`. Workspace показывает
  вкладку **«Проекты и доступы»** и передаёт только выбранный `project_id`; Central заново проверяет его. Telegram
  выбирает проект по точному зарегистрированному alias либо сохраняет redacted intake draft и задаёт один
  детерминированный вопрос. Ответ продолжает исходный source message; отдельный durable selection receipt защищает
  restart и delayed replay. Voice note сначала проходит существующий Hermes STT; при неуспешной транскрибации mission
  не создаётся.
- **Граница полномочий:** catalog разрешает обычные code/tests/review/PR/CI/merge операции по repo contract. Он не
  разрешает произвольный filesystem path, model/provider, shell command, credential, deploy/release либо destructive
  operation. Добавление проекта или изменение его execution boundary остаётся repo-owned reviewable change.
- **Инженерная форма:** используются существующие MissionStore SQLite, Hermes handlers, Workspace settings и systemd
  coordinator templates. Новый service, dashboard, workflow engine, dependency или model classifier не создаётся.
- **Последствия:** multiple registered projects получают независимые standing timers; одна ordinary goal может быть
  принята только после exact project resolution. Legacy single-route env остаётся временным backward-compatible
  fallback. Полная cross-channel chat transcript и arbitrary repository discovery по-прежнему не заявляются.

## ADR-033 — Контролируемый web research через отдельный Codex session

- **Контекст:** Central Hermes нужен веб-поиск только для явных owner research goals. Глобальный browser, произвольный
  shell egress или legacy `ai-search` на build-1 расширяют полномочия coding workers и не дают механических bounds.
  Закреплённый Hermes v0.18 уже содержит Brave provider, но стандартные Brave Search API Terms (2026-02-11) запрещают
  долговременное хранение Search Results, тогда как UAP обязан сохранять итог и цитаты в Central/Workspace/Telegram.
- **Решение:** отдельный MCP tool `research_session` запускает установленный Codex `0.142.0` как ephemeral
  `codex --search --model gpt-5.3-codex-spark exec` в read-only sandbox без shell tool, user config/MCP и с очищенным окружением. Spark использует
  отдельный лимит для bounded text-only search; итоговый анализ остаётся в Central Hermes. Для запуска во
  временный `CODEX_HOME` копируется только существующий Codex auth, который удаляется вместе с child session. Facade ограничивает goal,
  DNS allowlist и число источников, требует HTTPS, валидирует typed JSON result, атомарно сохраняет нормализованный
  итог на Hermes PVC по детерминированному request id и повторяет только один transient failure. Raw subprocess
  stdout/stderr и credential values не сохраняются и не возвращаются.
- **Trust boundary:** web content всегда маркируется `untrusted_external_content` и остаётся ниже owner/system
  instructions. Transient rate/transport outage возвращает retryable typed error без owner question. Обычные
  `codex exec`/`claude -p` coding workers не получают `--search`, новый network access или новый credential.
- **Отвергнуто:** глобально включить Hermes/Browser search; дать build-1 shell произвольный egress; новый search
  service/MCP router; Brave key при несовместимом default retention contract; provider auto-fallback.
- **Последствия:** Central сохраняет нормализованный result, а существующие Hermes channel sessions возвращают его
  в originating Workspace или Telegram; одинаковый request из второго канала idempotently получает тот же result.
  Brave остаётся исследованным, но неактивным кандидатом; его включение требует отдельного owner-provided credential
  и письменного retention права/Order Form, после чего эта ADR пересматривается. Текущий путь не требует нового setup.

## ADR-034 — Отдельная Central media mission через Codex subscription image generation

- **Контекст:** обычная image goal не является coding delivery и не должна попадать в author/reviewer Flow. На live
  worker Codex CLI `0.142.0` реально сообщает `image_generation=stable`, системный `$imagegen`,
  `modelProvider/capabilities/read.imageGeneration=true` под текущим ChatGPT OAuth и типизированный
  `imageGeneration` result с `savedPath`.
- **Решение:** консервативно распознанная text-to-image goal создаёт отдельную capability
  `media.image.generate` и отдельный app-server thread внутри существующего Central Hermes process. Разрешён только
  `openai-codex` + `codex_app_server` + встроенный `$imagegen`/`gpt-image-2`; Claude, local/GPU, FAL, OpenRouter и
  платный Image API не являются fallback. Central хранит bounded artifact metadata в том же mission log, а bytes —
  owner-only под `$HERMES_HOME/media-artifacts/<mission-id>/`. Telegram получает local image через существующий
  adapter, Workspace — через authenticated Central artifact route.
- **Надёжность:** один source message создаёт один mission и один media claim. После начала turn повторный запрос не
  генерирует заново; истёкший/неоднозначный claim завершается явной ошибкой. При успехе принимается ровно один
  completed image item, только PNG/JPEG/WebP до 25 MiB, с SHA-256 и проверкой перед каждым download.
- **Граница:** subscription-auth image editing пока **не заявляется**. Pinned Hermes app-server adapter превращает
  attached image в текстовый marker, а его `openai-codex` image backend объявляет text-only и
  `max_reference_images: 0`. Edit goal должна fail closed до появления проверенного subscription path с реальным
  image input; платный API не подключается автоматически.
- **Отвергнуто:** отдельный media service/workflow engine; переиспользование coding author/reviewer; прямой вызов
  private ChatGPT HTTP endpoint из Hermes plugin; автоматический повтор неоднозначной генерации; выбор провайдера
  моделью.
- **Поправка (2026-07-21, topology):** владелец утвердил один bot + один private forum supergroup с двумя topics
  (Code и Images). Точный server-owned allowlist `HERMES_MISSION_MEDIA_TOPICS` содержит пары
  `{"chat_id","thread_id"}` (Telegram `message_thread_id` уникален только внутри chat). Обычный текст/голос в
  настроенной паре детерминированно создаёт `media.image.generate` без `$imagegen` и без выбора проекта; модель
  не угадывает capability. Пустой/отсутствующий allowlist = маршрутизация отключена (fail-closed); malformed
  конфигурация блокирует owner turn. Явный `$imagegen`/`/image`/`/imagine` продолжает работать в любом topic.
  Fallback два bot — только если live topic canary не пройдёт; для него потребуется явная bot/account identity
  в channel scope и отдельное решение.

## ADR-035 — One-click onboarding нового проекта через детерминированный checkpoint driver

- **Контекст:** ADR-032 позволяет владельцу выбирать только уже зарегистрированный `ready`-проект. Создание нового
  GitHub-репозитория всё ещё требует ручного bootstrap: шаблона, CI, schema-v4 delivery profile, build-1 checkout и
  timer, live canary и отдельного изменения catalog status. Передача shell-команд, filesystem paths или profile из
  browser нарушила бы server-owned boundary, а выполнение механических правок моделью создало бы ненужную
  circular dependency.
- **Решение:** существующая Workspace-вкладка «Проекты и доступы» получает одну owner-authenticated операцию
  «Создать и подготовить». Browser передаёт только bounded `name`, `description` и preset из закрытого набора
  `rust|go|python|web`. Central хранит один idempotent onboarding request и пять forward-only checkpoint:
  `requested → repository_ready → runtime_ready → canary_passed → ready` либо явный `failed`. Один постоянный
  build-1 oneshot timer продвигает не более одного request за tick. Driver выполняет только детерминированные
  GitHub/git/systemd/Flux действия; model routing, review, CI repair и terminal semantics не дублирует.
- **Source of truth:** новый repository всегда имеет owner `PavelLizunov`, private visibility, server-owned template,
  commands и path boundary. Catalog/profile добавляются механическим UAP PR сначала как `setup_required`. Новый
  профиль устанавливается атомарно без остановки timers других проектов. Только обычная delivery mission с
  independent exact-SHA review, required GitHub-hosted macOS CI, merge, post-verify и проверенным completion evidence
  разрешает второй механический PR `setup_required → ready`; Flux ConfigMap остаётся authoritative readiness.
- **Полномочия:** нажатие кнопки является явным разрешением создать один named repository и выполнить bootstrap,
  PR/CI/merge и canary. Существующая server-side GitHub identity переиспользуется только если preflight доказывает
  нужные capability; иначе новый credential provisioning остаётся отдельным однократным owner setup. Credential не
  попадает в browser, model environment, prompt или repository. Обычные OpenAI routing/retry/spend и разрешённые
  PR/merge не создают дополнительных owner questions.
- **Надёжность:** request identity выводится из owner scope и repository slug, а полный payload связан hash; повтор
  HTTP/click возвращает тот же request, несовпадающий payload является collision. Каждый side effect сначала
  reconciles по GitHub/git/systemd/Flux/Central authority. Workspace может сохранить будущий project cookie сразу,
  но intake остаётся fail-closed, пока catalog status не `ready`.
- **Отложено:** direct execution на личном Mac mini, public repositories, arbitrary templates/commands, deploy/release
  и production credentials. В первой версии macOS означает только disposable GitHub-hosted runner. Отдельный
  onboarding dashboard, per-request service instance, новый workflow engine и model-generated catalog/profile
  отклонены.

## ADR-036 — Conversational admission и setup-чат существующего проекта

- **Контекст:** ordinary Workspace/Telegram intake после ADR-032 превращает почти любое сообщение владельца в coding
  mission. Поэтому вопросы «посмотри», «можем ли», «какие риски» нельзя обсудить до старта работы. Одновременно полный
  GitHub inventory показывает `setup_required`-репозитории, но интерфейс только блокирует их и не даёт начать настройку.
- **Решение:** текстовый owner turn создаёт mission только при консервативно распознанной явной команде на изменение
  (`исправь`, `интегрируй`, `настрой`, `запусти` и эквиваленты) либо при явном `/run`/`/mission`. Остальные сообщения идут
  в обычный Central Hermes chat; `/discuss` является явным escape hatch. Ответ на уже открытый mission question,
  незавершённый выбор проекта и media capability сохраняют прежний детерминированный intake независимо от формулировки.
  Это небольшой server-owned lexical gate, а не model classifier и не новый router.
- **Настройка существующего проекта:** карточка `setup_required` получает действие «Настроить в чате». Workspace хранит
  только HttpOnly `setup_project_id`, Central повторно разрешает его по authoritative catalog и добавляет в чат
  server-owned read-only context: точный repository, summary и test targets. Обсуждение может читать и анализировать
  репозиторий, но не меняет catalog status и не получает execution profile.
- **Разрешение на выполнение:** явная команда внутри setup-чата создаёт обычную mission в готовом проекте `uap` с
  server-generated goal на настройку указанного репозитория. Результат остаётся repo-owned reviewable изменением:
  schema-v4 profile, точные checks, catalog/runtime, PR, независимое review и CI. `setup_required → ready` разрешён только
  после установки runner/timer и реального canary; модель не может напрямую сгенерировать и активировать профиль.
- **Граница:** cookie или текст браузера не задают repository path, shell commands, credentials, profile либо статус.
  Не создаются новый service, workflow engine, setup database и второй mission plane. Голосовой legacy intake пока
  сохраняет прежнее поведение; единый admission для расшифрованного голоса требует отдельного проверенного изменения.
- **Отклонено:** стартовать mission на каждое сообщение; спрашивать подтверждение перед каждой ясной командой; делать
  `setup_required` selectable; автоматически объявлять произвольный существующий репозиторий `ready` по model-generated
  profile; отдельный setup dashboard/agent/service.
