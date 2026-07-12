# Observability: uap-ops-1 platform healthcheck + Telegram alerting

A lightweight, dependency-free healthcheck for the UAP platform. It runs **on `uap-ops-1`**
(tailnet `100.82.241.121`) as a `systemd --user` timer every 20 minutes, checks the things
that actually page you, and if any fail it POSTs **one** summary to Telegram. It also sends one
successful Proxmox backup report per day after the backup window.

**Why ops-1 and not a k8s CronJob:** cluster pods cannot reach the tailnet brain router
(`100.82.x`) and have no operator kubeconfig. `uap-ops-1` reaches `kubectl`, the tailnet, and the
egress proxy — so the probe has to live there. This is the same reason the local-models router and
the ops-backup timer live on ops-1, not in-cluster.

**No metrics stack.** POSIX `sh` plus existing `kubectl`, `curl`, `ssh` and coreutils. On a 2-node homelab a 20-min timer
that alerts on the real failure modes beats kube-prometheus-stack — see the ponytail note in the
script header. Add real metrics only when there is a second consumer for them.

Files (all in `infra/ops/`):

| File | Role |
|---|---|
| `uap-healthcheck.sh` | the checks + the Telegram POST |
| `uap-healthcheck.service` | `Type=oneshot`, sources `/etc/uap/healthcheck.env` |
| `uap-healthcheck.timer` | `OnCalendar=*:0/20` (every 20 min) |

## What it checks (each independent; all failures collected into one alert)

1. **Backup freshness** — `hermes-agent-backup` CronJob (`uap-system`) `.status.lastSuccessfulTime`
   is within `MAX_BACKUP_AGE_H` (default **26h** = daily 03:00 + slack). Empty/unparseable/stale → fail.
   Also catches "cluster/kubectl unreachable" (no lastSuccessfulTime returned).
2. **Brain router** — `GET http://100.82.241.121:8090/v1/models` returns 2xx (the ops-1
   local-models-router). Probed `--noproxy` so a stray `HTTP_PROXY` can't mask a local outage.
3. **Egress** — a request through the HA proxy (`http://192.168.0.202:30880`, the
   `singbox-egress-ha` NodePort on `uap-home-2`) to `https://api.telegram.org` returns any non-`000`
   HTTP code. `000` = connect failed = egress down.
4. **Pods** — no `uap-system` pod is non-`Running` or not-`Ready` (`Completed`/`Succeeded` job pods
   are ignored, e.g. the nightly backup pod).
5. **Proxmox VM backups** — after `05:00 Europe/Moscow`, VMIDs `102/201/202/203` each need a non-empty
   archive newer than 26h on `backup-pve2`. A healthy result sends one daily Telegram report with each
   archive size, total size and free target space; a state file prevents 20-minute duplicates.

The script **always exits 0** and logs to journald. A failed check is an alert, not a crash.

## The one secret the operator must supply

Everything is committed **except** the bot token + chat id. Create the env file on ops-1 (0600):

```sh
# on uap-ops-1, as the uap user
sudo install -d -m 0755 /etc/uap
sudo install -o "$USER" -g "$USER" -m 0600 /dev/null /etc/uap/healthcheck.env
cat > /etc/uap/healthcheck.env <<'EOF'
BOT_TOKEN=123456789:PASTE_TELEGRAM_BOT_TOKEN
CHAT_ID=PASTE_TELEGRAM_CHAT_ID
EOF
chmod 600 /etc/uap/healthcheck.env
```

- **Never commit this file.** It is the only secret the healthcheck needs.
- Get `BOT_TOKEN` from @BotFather; get `CHAT_ID` by messaging the bot then
  `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"` and reading `message.chat.id`
  (run that through the egress proxy from RU: `curl -x http://192.168.0.202:30880 ...`).
- Reuse the existing hermes-agent Telegram bot token if you want alerts in the same chat — it is in
  SOPS (`clusters/prod/infra/hermes-agent-*.sops.yaml`); decrypt on `uap-home-1` and copy the value
  by hand into `/etc/uap/healthcheck.env`. Do **not** wire SOPS into this timer — one 0600 env file
  is the lazier correct boundary.

## Install (on uap-ops-1, as the uap user)

Mirrors the existing `ops-backup` timer (user unit + linger). From a checkout of this repo on ops-1:

```sh
install -D -m 0700 infra/ops/uap-healthcheck.sh          "$HOME/bin/uap-healthcheck.sh"
install -D -m 0644 infra/ops/uap-healthcheck.service     "$HOME/.config/systemd/user/uap-healthcheck.service"
install -D -m 0644 infra/ops/uap-healthcheck.timer       "$HOME/.config/systemd/user/uap-healthcheck.timer"

loginctl enable-linger "$USER"        # fire without an active login session
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable --now uap-healthcheck.timer
systemctl --user list-timers uap-healthcheck.timer --all --no-legend
```

## Test it

```sh
# 1) run the checks once, right now, and watch the output (uses /etc/uap/healthcheck.env):
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user start uap-healthcheck.service
journalctl --user -u uap-healthcheck.service -n 40 --no-pager

# 2) run the script directly (identical behaviour; sources the env file itself):
~/bin/uap-healthcheck.sh

# 3) parser regression check (no network, no Telegram):
~/bin/uap-healthcheck.sh --self-test

# 4) force a failure to prove the Telegram path end-to-end (temporary override, no real outage):
ROUTER_URL=http://127.0.0.1:1/v1/models ~/bin/uap-healthcheck.sh
#   -> "brain router unreachable" fail + a Telegram message. Restore by omitting the override.
```

Healthy run prints `uap-healthcheck: all checks OK at <ts>` and sends nothing.

## Tuning

All optional; set in `/etc/uap/healthcheck.env` (systemd re-reads it each run):

| Var | Default | When to change |
|---|---|---|
| `MAX_BACKUP_AGE_H` | `26` | backup cadence changes from daily |
| `EGRESS_PROXY` | `http://192.168.0.202:30880` | the `singbox-egress-ha` NodePort moves |
| `ROUTER_URL` | `http://100.82.241.121:8090/v1/models` | router endpoint changes |
| `EGRESS_TARGET` | `https://api.telegram.org` | prefer a different reachability probe |
| `KUBECONFIG` | `$HOME/.kube/config` | non-default kubeconfig location |
| `PVE_SSH_TARGET` | `root@192.168.0.169` | Proxmox operator endpoint changes |
| `PVE_SSH_KEY` | `$HOME/.ssh/uap_proxmox_admin` | Proxmox key path changes |
| `PVE_BACKUP_STORAGE` | `backup-pve2` | backup storage ID changes |
| `PVE_BACKUP_VMIDS` | `102 201 202 203` | protected VM set changes |
| `PVE_BACKUP_MAX_AGE_H` | `26` | daily cadence or allowed delay changes |
| `PVE_REPORT_AFTER` | `0500` | report time changes (in `PVE_REPORT_TZ`) |
| `PVE_REPORT_TZ` | `Europe/Moscow` | backup schedule timezone changes |

Change the interval by editing `OnCalendar` in `uap-healthcheck.timer` (e.g. `*:0/15` for 15 min),
then `systemctl --user daemon-reload && systemctl --user restart uap-healthcheck.timer`.

The Proxmox report depends on ops-1 reaching `pve-ninitux` with the existing
`~/.ssh/uap_proxmox_admin` key. It never creates another Telegram credential; delivery reuses the
existing 0600 healthcheck environment file.
