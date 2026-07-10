# Observability: uap-ops-1 platform healthcheck + Telegram alerting

A lightweight, dependency-free healthcheck for the UAP platform. It runs **on `uap-ops-1`**
(tailnet `100.82.241.121`) as a `systemd --user` timer every 20 minutes, checks the four things
that actually page you, and if any fail it POSTs **one** summary to Telegram.

**Why ops-1 and not a k8s CronJob:** cluster pods cannot reach the tailnet brain router
(`100.82.x`) and have no operator kubeconfig. `uap-ops-1` reaches `kubectl`, the tailnet, and the
egress proxy — so the probe has to live there. This is the same reason the local-models router and
the ops-backup timer live on ops-1, not in-cluster.

**No metrics stack.** POSIX `sh` + `kubectl` + `curl` + `date`. On a 2-node homelab a 15-min timer
that alerts on the 4 real failure modes beats kube-prometheus-stack — see the ponytail note in the
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

# 3) force a failure to prove the Telegram path end-to-end (temporary override, no real outage):
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

Change the interval by editing `OnCalendar` in `uap-healthcheck.timer` (e.g. `*:0/15` for 15 min),
then `systemctl --user daemon-reload && systemctl --user restart uap-healthcheck.timer`.

## Known gap this does NOT cover

Data-loss gaps outside `uap-system`: the `uap-build-1` `knowledge.db` and the ops-1 router config
have no backup and are not in GitOps. This healthcheck watches the in-cluster backup + brain +
egress + pods only. Backing up build-1/ops-1 state is tracked separately.
