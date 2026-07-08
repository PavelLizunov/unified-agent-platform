# Карта флота — что на какой ноде и ПОЧЕМУ

Все машины хоумлаба и логика размещения. **Часть железа общая между двумя проектами** (UAP-агент и
разработка приложения VPNRouter) — эти машины помечены «×2 роли».

## Платформа UAP (агент Hermes)

| Роль | Хост | Железо | Always-on | Что держит | tailnet |
|---|---|---|---|---|---|
| **ЯДРО** | `uap-home-1` | 4c/8GB (VM, pve-ninitux) | да | k3s control-plane + etcd, Flux, LiteLLM, **VLESS-эгресс** | `100.106.223.120` |
| **ВОРКЕР** | `uap-home-2` | 6c/8GB (VM, pve-ninitux3) | да | **Hermes-агент** (мозг, лимит 4Gi), subfleet-мост, бэкапы | `100.94.228.67` |
| **ОПЕРАТОР** | `uap-ops-1` | 2c/2GB (VM) | да | git-push + gh + kubectl, **роутер моделей**, SOPS | `100.82.241.121` |
| **СТРОЙКА** | `uap-build-1` | 8c/16GB (VM, pve-ninitux3, **Ubuntu 22.04**, LAN `192.168.0.99`) | да | UAP-сборки (cargo/make), кодинг, репо-работа, тяжёлый compute | `100.85.56.31` |
| **GPU** ×2 роли | `desktop-m922ij2` | RTX 5060 Ti 16GB, Win | **НЕТ** | **Qwen-35B** — единственный мозг платформы | `100.114.172.40` |
| **МАК** ×2 роли | `pavels-mac-mini` (`mm4.local`) | M4/16GB | да | **Ornith-9B** (кодер / запасной мозг) | `100.116.97.112` |

## Разработка приложения VPNRouter (тест-стенд)

| Роль | Хост | Железо | Питание | Что держит | Доступ |
|---|---|---|---|---|---|
| **DEV BOX** ×2 роли | `desktop-m922ij2` | это ЖЕ GPU-машина, Win | по вкл. | код `C:\Project\VPNRouter`, сборка, тулинг `C:\vmsetup\`, DPAPI-креды | локально |
| **windows-brat** | Proxmox VMID **100**, pve-ninitux | Win10 LTSC 2019 | по вкл. | ГЛАВНЫЙ таргет: packaged-app + live + UI-verify | RDP 3389 / WinRM 5985, LAN `192.168.0.106` |
| **debian-xfce** | Proxmox VMID **101**, pve-ninitux | Debian 12 + XFCE | по вкл. | Linux (.deb) таргет, guest-agent есть | pve-guest-exec / ssh (ключ `C:\vmsetup\testvm_key`), LAN DHCP |
| **МАК** ×2 роли | `mm4.local` (= UAP МАК) | M4/16GB | да | DMG-билды (`build-mac.sh`), + **Android** по USB (`adb` serial 54499112209) | ssh `slovn@100.116.97.112` (⚠ `zsh -lc`, не `bash -lc`) |

Потоки VPNRouter: **DEV BOX** (код/сборка Win+Linux пакетов) → **МАК** (DMG-билд + Android) → билды тянутся
внутрь **windows-brat / debian-xfce** (VM сами PULL'ят ZIP из GitHub-релиза) → UI-verify там. Все тесты —
ТОЛЬКО на тест-VM, НИКОГДА на dev box.

## Общее железо (double-duty — вот что «дублировалось»)
- **GPU-десктоп `desktop-m922ij2`**: UAP `Qwen-35B` (мозг) **И** VPNRouter dev box (код + сборка + тулинг) **И**
  Claude Code. Одна физическая машина, три шляпы. Не always-on.
- **МАК `mm4.local` / `pavels-mac-mini` (`100.116.97.112`)**: UAP `Ornith-9B` **И** VPNRouter DMG-билд + Android-хост.
  Одна машина. (В tailnet напрямую только она; тест-VM VPNRouter достаются через мак-туннель или мак как subnet-router.)

## ⚠️ Конфликт IP — развести
**`uap-build-1` (Ubuntu, always-on) и `debian-xfce` (Debian, on-demand) оба на `192.168.0.99`.** build-1 сейчас
держит .99; debian-xfce берёт IP по DHCP → при его старте либо получит другой адрес, либо конфликт. Починка:
дать build-1 статику вне DHCP-пула, ИЛИ закрепить debian-xfce на другом адресе. Пока debian-xfce выключен —
не мешает, но полагаться на «.99 = debian-xfce» нельзя (это адрес build-1).

## Proxmox-хосты (гипервизоры)
- **pve-ninitux** (`192.168.0.169`) — держит ЯДРО (uap-home-1) + VPNRouter тест-VM (windows-brat, debian-xfce).
  Он же — power-control тест-VM (scoped token `root@pam!claude-testvm`, роль PVEVMAdmin на /vms/100,101).
- **pve-ninitux3** — держит ВОРКЕР (uap-home-2) + СТРОЙКУ (uap-build-1, 16GB). Отсюда и теснота: build-1 съедает
  память хоста, поэтому home-2 не расширить дальше 8GB и тяжёлое лучше слать на уже-выделенный build-1.

## Почему так разнесено (логика UAP)
1. **Критичность изолирована:** etcd + эгресс (уронят всё) — на стабильном ЯДРЕ; ВОРКЕР держит то, что может падать.
2. **Деплой вне кластера:** write-ключ git только на ОПЕРАТОРЕ → сломается кластер, с него всё равно восстановишь; роутер там же (поды не достают tailnet-модели, а ОПЕРАТОР достаёт).
3. **Ресурсы под задачу:** тяжёлое — на большой СТРОЙКЕ; модели — на железе с нужным кремнием (Qwen→GPU, Ornith→МАК).

## Про имена
Роль-ярлыки (ЯДРО/ВОРКЕР/…) — для понимания; реально хосты не переименованы (имена зашиты в ssh/tailnet/k3s/Flux/SOPS).
