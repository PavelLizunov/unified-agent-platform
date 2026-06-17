# План сборки

Сборка по этапам. **Веха** каждого этапа — тест на «замена, а не остановка»: пока веха не зелёная,
к следующему этапу не переходить. Команды/версии ниже — **заготовки**, сверять с актуальной докой.

Легенда исполнителя: 👤 владелец · 🤖 агент-исполнитель.

---

## Сквозные правила реализации

- Linux-узлы по умолчанию: **Debian 12** с одинаковой базовой настройкой. Новее допустимо только после
  явного согласования, чтобы не получить разные системные профили на разных нодах.
- Сеть: **Tailscale** как основной tailnet. Hysteria Realms допускается только как аварийный/экспериментальный
  канал, не как фундамент k3s/etcd.
- SSH: после bootstrap отключить парольный вход и root-login, оставить вход по ключам через отдельного
  admin-пользователя с sudo.
- GitOps: **Flux CD + Kustomize/HelmRelease + SOPS/age**. Секреты не хранить plaintext.
- Dependency budget: каждый новый controller/CRD/Helm chart добавляется только если нужен для текущей
  вехи или закрывает явно описанный риск.
- Языки: Go-first для инфраструктурного кода, CLI, health-checks и первых durable-воркеров; Rust — для
  автономных долгоживущих daemon/proxy и критичных по безопасности/производительности частей.
- Разработка несколькими ИИ-исполнителями: Codex и Claude Code работают через git/ADR/runbooks, с явным
  ownership файлов на задачу и без параллельной правки одной области.
- Если VPS ещё нет, разрешён local-first bootstrap на одном `home-linux`. Он не закрывает HA-веху и не
  позволяет переходить к статусу `HA ready`.
- Воспроизводимый bootstrap: **OpenTofu/Terraform** создаёт VM/VPS и outputs, **Ansible** настраивает
  Debian/SSH/Tailscale/k3s/Flux, **Flux/SOPS** управляет содержимым Kubernetes. Terraform/OpenTofu не использует
  `remote-exec` для установки k3s.

---

## Этап 0L — Локальный старт на домашнем Linux 🤖

**Цель:** начать реализацию без VPS, подготовить основу так, чтобы позже без перепроектирования перейти к
3-node HA.

Предусловие: есть домашний Linux-сервер, желательно Debian 12, с SSH-доступом по ключу и установленным
Tailscale. Windows/Mac можно подключить позже; для 0L достаточно `home-linux`.

Что делаем:

1. Инициализировать git-репозиторий и базовую структуру:
   `clusters/prod`, `infra`, `apps`, `secrets`, `tests`, `runbooks`.
2. Настроить SSH hardening на `home-linux`: отдельный admin-пользователь, sudo, отключение паролей и
   root-login после проверки ключевого входа.
3. Поставить single-server k3s на `home-linux` с теми же критичными флагами, что нужны будущему кластеру:
   `--node-ip=<TAILNET_IP_HOME>`, `--flannel-iface=tailscale0`, `--tls-san=<TAILNET_IP_HOME>`,
   `--disable=traefik`, `--disable=servicelb`.
4. По возможности сразу использовать `--cluster-init`, чтобы стартовать на embedded etcd и позже добавить
   VPS server-ноды без смены модели datastore. Если сначала выбран SQLite, переход в embedded etcd фиксировать
   отдельным runbook перед добавлением VPS.
5. Подготовить Flux/SOPS skeleton, но ставить только минимальные компоненты.
6. Написать smoke-тесты: `kubectl get nodes`, `kubectl get pods -A`, запуск test Deployment/Service,
   проверка tailnet bind и базовых логов.

**Веха 0L:** `home-linux` работает как single-node k3s, kubeconfig доступен, smoke-тесты зелёные, runbook
перехода к 3-node HA описан. Это **не** HA-веха.

---

## Этап 0P — Proxmox local bootstrap 🤖

**Цель:** создать локальные Linux-серверы на Proxmox без удалённой VPS и подготовить их к будущему HA.

Предусловие: доступен Proxmox endpoint из локальной сети, известны ноды `pve-ninitux` и `pve-ninitux3`.
Пароли/API tokens не сохранять в репозиторий.

План:

1. Проинспектировать Proxmox: версии, ноды, storage, bridge, доступные ISO/templates.
2. Создать Debian 12 VM `uap-home-1` на `pve-ninitux` с запасом ресурсов.
3. Создать Debian 12 VM `uap-home-2` на `pve-ninitux3` с минимальным профилем 2-4 GB RAM.
4. Добавить public SSH keys из `infra/ssh/agent-authorized-keys.pub`.
5. Настроить admin-пользователя, SSH hardening, Tailscale.
6. Поднять single-server k3s на `uap-home-1`. `uap-home-2` сначала можно оставить подготовленной Linux-нoded
   или подключить позже, когда будет третья quorum-нода.
7. Зафиксировать repeatable path: `infra/tofu/environments/local-proxmox`, `infra/ansible/inventories/local.yml`,
   Ansible playbooks и параметризованные smoke-тесты.

**Веха 0P:** обе VM доступны по SSH-ключам, Tailscale работает, `uap-home-1` проходит single-node k3s
smoke-тесты, `uap-home-2` готова к будущему join. Это **не** HA-веха.

---

## Этап 0 — Сеть и узлы 👤

**Цель:** все машины достижимы друг с другом по mesh.

1. Завести 2 дешёвых VPS (бюджетный профиль допустим: около 1 vCPU / 1 ГБ RAM / 15 ГБ SSD; постоянно онлайн).
   - Важно: это ниже комфортного профиля k3s server-node. Этап 1 обязан доказать жизнеспособность такой
     конфигурации отказоустойчивой вехой.
   - Домашний Linux-сервер несёт основные workload; удалённые VPS — максимально лёгкий control-plane/etcd.
2. Поставить **Tailscale** на все 5 машин (дом-сервер, VPS-1, VPS-2, Windows, Mac).
   - Headscale не стартовый путь; возможен позже как отдельная миграция координатора.
3. Записать tailnet-IP и tailnet-имя каждого узла.
4. Подготовить SSH-доступ к Linux-узлам: ключи, отдельный admin-пользователь, затем отключение паролей.

**Веха:** каждая машина пингует все остальные по tailnet-имени/IP.

---

## Этап 1 — k3s HA control-plane (3 узла) 🤖

**Цель:** отказоустойчивый кластер поверх tailnet. Предусловие: Этап 0 завершён.

Бюджетный профиль:
- server-ноды: `home-linux`, `vps-1`, `vps-2`;
- пользовательские workload по умолчанию размещать на `home-linux`;
- удалённые VPS маркировать как тонкие control-plane-ноды и не планировать на них тяжёлые приложения;
- если бюджетные VPS не проходят веху, не переходить к Этапу 2: нужна замена профиля или пересмотр HA-цели.

Первая server-нода (cluster-init):
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --cluster-init \
  --node-ip=<TAILNET_IP_1> \
  --flannel-iface=tailscale0 \
  --tls-san=<TAILNET_IP_1> \
  --disable=traefik \
  --disable=servicelb" sh -
# токен для join:  cat /var/lib/rancher/k3s/server/node-token
```

Вторая и третья server-ноды (join):
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --server https://<TAILNET_IP_1>:6443 \
  --node-ip=<TAILNET_IP_N> \
  --flannel-iface=tailscale0 \
  --disable=traefik \
  --disable=servicelb" \
  K3S_TOKEN=<TOKEN> sh -
```

> ⚠️ `--node-ip` и `--flannel-iface=tailscale0` обязательны — иначе ноды за NAT не сойдутся (см. RISKS.md).

**Веха:** `kubectl get nodes` → 3 × Ready; затем выключить любой 1 узел — кластер остаётся рабочим
(`kubectl` отвечает, поды живут).

После зелёной вехи Этапа 1:
- сохранить kubeconfig с endpoint на `vps-1`, `vps-2` и `home-linux` как fallback-контексты;
- включить scheduled etcd snapshots локально; S3/offsite-настройку подключить на Этапе 2;
- подготовить GitOps-скелет (`clusters/prod`, `infra`, `apps`, `secrets`, `tests`, `runbooks`) без установки
  лишних controllers сверх Flux/SOPS.

---

## Этап 2 — Слой состояния (Postgres HA + MinIO) 🤖

**Цель:** durable-стор и хранилище артефактов с репликацией.

- **Postgres:** оператор **CloudNativePG**; кластер 1 primary + 2 replica, авто-failover.
- **MinIO:** на старте single-node на домашнем сервере + регулярный offsite backup; distributed-режим
  вынести в отдельный шаг, когда конфигурация дисков ясна.
- Секреты (пароли) — через SOPS/age и k8s Secrets, не plaintext в манифестах.

**Веха:** удалить под primary Postgres → новый primary избирается за секунды, данные на месте.
Загрузить/скачать объект из MinIO и проверить, что offsite backup создаётся и восстанавливается.

---

## Этап 3 — Шлюз моделей (LiteLLM ×2) 🤖 / ключи 👤

**Цель:** единый эндпоинт с маршрутизацией и fallback.

- Deployment LiteLLM, `replicas: 2`, за Service. Учёт/ключи — в Postgres из Этапа 2.
- 👤 владелец: запустить Ollama на Mac (мелкие модели) и Windows (большие), выдать ключи Claude + OpenRouter.

Скелет конфига (`config.yaml`):
```yaml
model_list:
  - model_name: smart-cloud           # основной
    litellm_params:
      model: anthropic/claude-...      # уточнить актуальный id
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: cloud-fallback         # запас
    litellm_params:
      model: openrouter/...
      api_key: os.environ/OPENROUTER_API_KEY
  - model_name: cheap-local            # overflow для простых задач
    litellm_params:
      model: ollama/<model>
      api_base: http://<TAILNET_IP_MAC>:11434
litellm_settings:
  fallbacks: [{"smart-cloud": ["cloud-fallback"]}]
```

**Веха:** запрос к `smart-cloud` → Claude; сломать ключ Claude → автопереход на `cloud-fallback`
(OpenRouter); запрос к `cheap-local` → уходит на Ollama по tailnet.

---

## Этап 4 — Durable-ядро + агенты + дашборд 🤖

**Цель:** «замена, а не остановка» для критичных задач; агенты-воркеры на всех узлах.

- **Restate** в кластере (durable журнал → Postgres из Этапа 2).
- Шаблон **agent-воркера** (Claude Code / Hermes / собственный worker-daemon): stateless, ходит в LiteLLM,
  состояние наружу.
  - Критичные/длинные задачи — durable workflow (Restate SDK, идемпотентные побочные эффекты).
  - Мелкие задачи — обычный вызов с перезапуском при сбое.
- Windows/Mac/Linux-воркеры цепляются к Restate по tailnet — их **не** нужно делать нодами k3s.
- Первый durable-worker писать на Go; локальный долгоживущий daemon для Windows/Mac можно писать на Rust,
  если он отвечает за heartbeat, capabilities и Ollama supervision.
- **Дашборд:** Mission Control или Restate UI (сменный модуль).

**Веха:** запустить durable-задачу на Windows-воркере → посреди выполнения выключить Windows →
задача доезжает на другом воркере с чекпойнта. Мелкая задача при отвале — просто перезапускается.

---

## Итоговая проверка платформы

- Зайти с Windows, затем с Mac, затем с Linux — в каждом случае видеть **один и тот же** набор сессий.
- Выключить любой один из 3 узлов кластера — платформа продолжает работать.
- Выключить Mac/Windows-воркер — его durable-задачи переназначаются, система не встаёт.
