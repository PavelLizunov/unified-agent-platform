#!/bin/sh
# uap-healthcheck: lightweight platform healthcheck + Telegram alert. Runs ON uap-ops-1 as a
# systemd --user timer (see uap-healthcheck.service/.timer, runbook: runbooks/observability.md).
#
# WHY ops-1 and NOT a k8s pod: cluster pods cannot reach the tailnet brain router (100.82.x) and
# have no operator kubeconfig; ops-1 reaches kubectl + the tailnet + the egress proxy. That is the
# whole reason this is a VM timer, not a CronJob.
#
# Best-effort by design: a failed check is an ALERT, never a script crash -> we ALWAYS exit 0 and
# ALWAYS log to stdout (journald). Each check runs independently; all failures are collected and
# sent as ONE Telegram message.
#
# Config: /etc/uap/healthcheck.env (0600, operator-created, NEVER committed). systemd loads it via
# EnvironmentFile=; we also source it so a manual `./uap-healthcheck.sh` works identically.
#   BOT_TOKEN=...            Telegram bot token   (required to alert)
#   CHAT_ID=...              Telegram chat id     (required to alert)
# Optional overrides (defaults below are the documented live values):
#   EGRESS_PROXY, ROUTER_URL, EGRESS_TARGET, MAX_BACKUP_AGE_H, KUBECONFIG
#
# ponytail: POSIX sh + kubectl/curl/date only. No framework, no metrics stack. A 15-min timer that
# alerts on the 4 things that actually page you beats kube-prometheus-stack on a 2-node homelab.

[ -r /etc/uap/healthcheck.env ] && . /etc/uap/healthcheck.env

: "${KUBECONFIG:=$HOME/.kube/config}"; export KUBECONFIG
: "${ROUTER_URL:=http://100.82.241.121:8090/v1/models}"     # ops-1 local-models-router (qwen-35b/ornith-9b)
: "${EGRESS_PROXY:=http://192.168.0.202:30880}"             # singbox-egress-ha NodePort on uap-home-2; override if it moves
: "${EGRESS_TARGET:=https://api.telegram.org}"              # any HTTPS host; telegram = same path the alert uses
: "${MAX_BACKUP_AGE_H:=26}"                                 # daily backup (03:00) + slack
NS=uap-system
CRON=hermes-agent-backup

fails=""
add_fail() { fails="${fails}- $1
"; }

# (a) hermes-agent PVC backup succeeded within MAX_BACKUP_AGE_H (CronJob .status.lastSuccessfulTime).
last=$(kubectl -n "$NS" get cronjob "$CRON" -o jsonpath='{.status.lastSuccessfulTime}' 2>/dev/null)
if [ -z "$last" ]; then
  add_fail "backup: CronJob $CRON has no lastSuccessfulTime (never succeeded, missing, or cluster/kubectl unreachable)"
else
  last_s=$(date -d "$last" +%s 2>/dev/null)
  if [ -z "$last_s" ]; then
    add_fail "backup: cannot parse lastSuccessfulTime '$last'"
  else
    age_h=$(( ( $(date +%s) - last_s ) / 3600 ))
    [ "$age_h" -gt "$MAX_BACKUP_AGE_H" ] && \
      add_fail "backup: last success ${age_h}h ago (> ${MAX_BACKUP_AGE_H}h): $last"
  fi
fi

# (b) brain router reachable (direct; --noproxy so any HTTP_PROXY env can't mask a local outage).
curl -sf --noproxy '*' --max-time 10 -o /dev/null "$ROUTER_URL" || \
  add_fail "brain router unreachable: $ROUTER_URL"

# (c) egress up: any non-000 HTTP code through the HA proxy = the path works (000 = connect failed).
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -x "$EGRESS_PROXY" "$EGRESS_TARGET" 2>/dev/null)
[ "${code:-000}" = "000" ] && \
  add_fail "egress proxy down: $EGRESS_PROXY -> $EGRESS_TARGET (curl http_code=${code:-none})"

# (d) no uap-system pods non-Running / not-Ready (Completed/Succeeded job pods are fine).
bad=$(kubectl -n "$NS" get pods --no-headers 2>/dev/null | awk '
  { name=$1; ready=$2; status=$3
    if (status=="Completed" || status=="Succeeded") next
    if (status!="Running") { print name" ("status")"; next }
    n=split(ready,a,"/"); if (n==2 && a[1]!=a[2]) print name" ("ready" ready)"
  }')
[ -n "$bad" ] && add_fail "pods not healthy in $NS: $(printf '%s' "$bad" | tr '\n' ',' | sed 's/,$//; s/,/, /g')"

send_telegram() {
  _text=$1
  if [ -z "${BOT_TOKEN:-}" ] || [ -z "${CHAT_ID:-}" ]; then
    echo "uap-healthcheck: BOT_TOKEN/CHAT_ID unset in /etc/uap/healthcheck.env - alert NOT sent" >&2
    return 0
  fi
  _url="https://api.telegram.org/bot${BOT_TOKEN}/sendMessage"
  # RU->Telegram goes via the HA proxy; fall back to direct in case the proxy itself is what's down.
  curl -fs -o /dev/null --max-time 20 -x "$EGRESS_PROXY" \
       --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=${_text}" "$_url" 2>/dev/null || \
  curl -fs -o /dev/null --max-time 20 \
       --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=${_text}" "$_url" 2>/dev/null || \
  echo "uap-healthcheck: Telegram send failed (proxy and direct)" >&2
}

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ -n "$fails" ]; then
  msg="UAP healthcheck FAILED on $(hostname) at ${now}:
${fails}"
  printf '%s\n' "$msg"          # -> journald
  send_telegram "$msg"
else
  echo "uap-healthcheck: all checks OK at ${now}"
fi
exit 0
