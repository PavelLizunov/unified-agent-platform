# Карта флота — что на какой ноде и ПОЧЕМУ

Все машины хоумлаба и логика размещения. **Часть железа общая между двумя проектами** (UAP-агент и
разработка приложения VPNRouter) — эти машины помечены «×2 роли».

## Платформа UAP (агент Hermes)

| Роль | Хост | Железо | Always-on | Что держит | tailnet |
|---|---|---|---|---|---|
| **ЯДРО** | `uap-home-1` | 4c/8GB (VM, pve-ninitux) | да | k3s control-plane + etcd, Flux, LiteLLM, **VLESS-эгресс** | `100.106.223.120` |
| **ВОРКЕР** | `uap-home-2` | 6c/8GB (VM, pve-ninitux3) | да | **Hermes-агент** (Codex brain, лимит 4Gi), subfleet-мост, бэкапы | `100.94.228.67` |
| **ОПЕРАТОР** | `uap-ops-1` | 2c/2GB (VM) | да | git-push + gh + kubectl, **fallback-роутер моделей**, SOPS | `100.82.241.121` |
| **СТРОЙКА** | `uap-build-1` | 8c/16GB (VM, pve-ninitux3, **Ubuntu 22.04**, LAN `192.168.0.99`) | да | UAP-сборки (cargo/make), кодинг, репо-работа, тяжёлый compute | `100.85.56.31` |
| **OWNER WORKSTATION** | `desktop-m922ij2` | RTX 5060 Ti 16GB, Win | **НЕТ** | рабочая машина владельца; Qwen только по адресному разрешению | `100.114.172.40` |
| **МАК** ×2 роли | `pavels-mac-mini` (`mm4.local`) | M4/16GB | да | **Ornith-9B** (кодер / запасной мозг) | `100.116.97.112` |

## Разработка приложения VPNRouter (тест-стенд)

| Роль | Хост | Железо | Питание | Что держит | Доступ |
|---|---|---|---|---|---|
| **OWNER DEV BOX** | `desktop-m922ij2` | рабочая Windows владельца | по вкл. | код и локальный owner-tooling; **не Hermes target** | только владелец |
| **windows-brat** | Proxmox VMID **100**, pve-ninitux | Win10 LTSC 2019 | по вкл. | ГЛАВНЫЙ таргет: packaged-app + live + UI-verify | **tailnet `100.115.182.0`**, RDP 3389 / WinRM 5985, LAN `192.168.0.106` |
| **debian-xfce** | Proxmox VMID **101**, pve-ninitux | Debian 12 + XFCE | по вкл. | Linux (.deb) таргет, guest-agent есть | **tailnet `100.81.162.66`** (через VLESS-прокси, см. ниже), pve-guest-exec / ssh (ключ `C:\vmsetup\testvm_key`), LAN `192.168.0.100` |
| **МАК** ×2 роли | `mm4.local` (= UAP МАК) | M4/16GB | да | DMG-билды (`build-mac.sh`), + **Android** по USB (`adb` serial 54499112209) | ssh `slovn@100.116.97.112` (⚠ `zsh -lc`, не `bash -lc`) |

Потоки VPNRouter: owner DEV BOX может готовить код/сборки вручную; Hermes ведёт repo-работу через build-1 и
назначенные targets. Билды тянутся внутрь **windows-brat / debian-xfce** → UI-verify там. Все Windows/Linux
live/UI-тесты — ТОЛЬКО на тест-VM, НИКОГДА на owner workstation.

## Общее железо (double-duty — вот что «дублировалось»)
- **Owner workstation `desktop-m922ij2`**: рабочая Windows владельца с Qwen и локальным dev-tooling. Она не входит
  в доступный Hermes fleet. Даже Qwen health-check/call требует нового разрешения для конкретного агента и действия;
  общее owner-window разрешение не подходит.
- **МАК `mm4.local` / `pavels-mac-mini` (`100.116.97.112`)**: UAP `Ornith-9B` **И** VPNRouter DMG-билд + Android-хост.
  Одна машина.

## Тест-VM теперь в tailnet напрямую (2026-07-08)
`windows-brat` и `debian-xfce` заведены в тайлнет со своими IP — доступ такой же прямой, как к остальным нодам
(больше не нужен мак-туннель / subnet-router).
- Ставили через **apt-репо `pkgs.tailscale.com`** (маркетинговый `tailscale.com` в RU заблокирован = 000, а репо пакетов = 200); Windows MSI = `pkgs.tailscale.com/stable/tailscale-setup-1.98.8-amd64.msi`. `tailscale up --accept-dns=false` — не трогаем DNS тест-VM.
- ⚠️ **`debian-xfce` держится только через VLESS-прокси.** RU-DPI душит Cloudflare-фронтованный трафик до ~1 КБ/с после ~24 КБ, а `controlplane.tailscale.com` за Cloudflare → свежая нода не могла докачать начальный netmap за 120с и падала в offline (уже-синканные ноды выживают на мелких инкрементах). Фикс — tailscaled ходит через `192.168.0.202:30880` (тот же VLESS-egress, что у build-1 для cargo), systemd drop-in `/etc/systemd/system/tailscaled.service.d/proxy.conf` (`HTTPS_PROXY` + `NO_PROXY=192.168.0.0/16,100.64.0.0/10`). Детали — память `uap-tailnet-cloudflare-throttle`.
- `windows-brat` пока держится БЕЗ прокси (Connected). Если начнёт отваливаться — тот же `HTTPS_PROXY`-фикс.

## LAN-адреса тест-VM (DHCP, могут дрейфовать)
- `uap-build-1` = **`192.168.0.99`** (Ubuntu, always-on).
  Для read-only cluster routing на нём есть отдельный ключ `~/.ssh/cluster_ops` и strict-host aliases
  `ops-1` (`100.82.241.121`) / `home-1` (`100.106.223.120`); приватный ключ в git не хранится.
- `windows-brat` вызывается с build-1 командой `windows-brat [PowerShell]` через NTLM/WinRM. Исходник:
  `tools/windows/windows-brat`; credential-файл `~/.config/windows-brat.json` обязан быть `0600` и в git не
  хранится. Без аргументов команда возвращает bounded health JSON. Это command route, не GUI-автоматизация:
  WinRM не видит интерактивный RDP desktop, а удалённый токен `tester` не повышается через UAC.
- `windows-brat` = **`192.168.0.106`**, `debian-xfce` = **`192.168.0.100`**. Конфликта нет (в хендоффе стоял
  устаревший `.99` для debian — это адрес build-1; актуальный — `.100`). Обе на DHCP → адреса могут меняться.

## Proxmox-хосты (гипервизоры)
- **pve-ninitux** (`192.168.0.169`) — держит ЯДРО (uap-home-1) + VPNRouter тест-VM (windows-brat, debian-xfce).
  Он же — power-control тест-VM (scoped token `root@pam!claude-testvm`, роль PVEVMAdmin на /vms/100,101).
- **pve-ninitux2** (`192.168.0.170`) — отдельный backup-диск/NFS target и лёгкие LXC-тестеры
  `vpnr-deb12`/`vpnr-alpine`; сами LXC пока доступны только через LAN/Proxmox control path.
- **pve-ninitux3** — держит ВОРКЕР (uap-home-2) + СТРОЙКУ (uap-build-1, 16GB). Отсюда и теснота: build-1 съедает
  память хоста, поэтому home-2 не расширить дальше 8GB и тяжёлое лучше слать на уже-выделенный build-1. Здесь же
  работает `vpnctld` (VMID 119, LAN `192.168.0.236`, tailnet `100.88.198.106`), production deploy target проекта
  `vpnctl`. Его `tailscaled` использует тот же VLESS proxy `192.168.0.202:30880`, потому что direct initial netmap
  стабильно обрывался через две минуты; service API `18402/tcp` разрешён на LAN и `tailscale0`.

Полный проверяемый список VM/LXC и политика tailnet находятся в `infra/ops/proxmox-machines.txt`. Существующий
`uap-healthcheck.timer` на ops-1 каждые 20 минут сверяет его с Proxmox и Tailscale; новая или переехавшая машина
вызывает alert до явной классификации.

## Почему так разнесено (логика UAP)
1. **Критичность изолирована:** etcd + эгресс (уронят всё) — на стабильном ЯДРЕ; ВОРКЕР держит то, что может падать.
2. **Деплой вне кластера:** write-ключ git только на ОПЕРАТОРЕ → сломается кластер, с него всё равно восстановишь; роутер там же (поды не достают tailnet-модели, а ОПЕРАТОР достаёт).
3. **Ресурсы под задачу:** тяжёлое — на большой СТРОЙКЕ; разрешённый ручной model fallback — Ornith на МАКе.

## Про имена
Роль-ярлыки (ЯДРО/ВОРКЕР/…) — для понимания; реально хосты не переименованы (имена зашиты в ssh/tailnet/k3s/Flux/SOPS).
