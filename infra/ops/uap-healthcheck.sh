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
#   PVE_SSH_TARGET, PVE_SSH_KEY, PVE_BACKUP_STORAGE, PVE_BACKUP_VMIDS,
#   PVE_BACKUP_MAX_AGE_H, PVE_REPORT_AFTER, PVE_REPORT_TZ
#
# ponytail: POSIX sh + existing kubectl/curl/ssh/coreutils only. No framework, no metrics stack. A 20-min timer that
# alerts on the 4 things that actually page you beats kube-prometheus-stack on a 2-node homelab.

[ -r /etc/uap/healthcheck.env ] && . /etc/uap/healthcheck.env

: "${KUBECONFIG:=$HOME/.kube/config}"; export KUBECONFIG
: "${ROUTER_URL:=http://100.82.241.121:8090/v1/models}"     # ops-1 local-models-router (qwen-35b/ornith-9b)
: "${EGRESS_PROXY:=http://192.168.0.202:30880}"             # singbox-egress-ha NodePort on uap-home-2; override if it moves
: "${EGRESS_TARGET:=https://api.telegram.org}"              # any HTTPS host; telegram = same path the alert uses
: "${MAX_BACKUP_AGE_H:=26}"                                 # daily backup (03:00) + slack
: "${PVE_SSH_TARGET:=root@192.168.0.169}"
: "${PVE_SSH_KEY:=$HOME/.ssh/uap_proxmox_admin}"
: "${PVE_BACKUP_STORAGE:=backup-pve2}"
: "${PVE_BACKUP_VMIDS:=102 201 202 203}"
: "${PVE_BACKUP_MAX_AGE_H:=26}"
: "${PVE_REPORT_AFTER:=0500}"                               # Europe/Moscow, after the 03:15 job window
: "${PVE_REPORT_TZ:=Europe/Moscow}"
NS=uap-system
CRON=hermes-agent-backup

fails=""
add_fail() { fails="${fails}- $1
"; }

latest_backup() {
  printf '%s\n' "$1" | awk -F '|' -v id="$2" '
    $1 ~ ("^vzdump-qemu-" id "-") && $2 > newest { newest=$2; line=$0 }
    END { if (line) print line }
  '
}

if [ "${1:-}" = "--self-test" ]; then
  sample='vzdump-qemu-203-old.vma.zst|100|10
vzdump-qemu-102-new.vma.zst|300|30
vzdump-qemu-203-new.vma.zst|200|20'
  test "$(latest_backup "$sample" 203)" = 'vzdump-qemu-203-new.vma.zst|200|20'
  test -z "$(latest_backup "$sample" 999)"
  echo "uap-healthcheck-self-test-ok"
  exit 0
fi

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
    return 1
  fi
  _url="https://api.telegram.org/bot${BOT_TOKEN}/sendMessage"
  # RU->Telegram goes via the HA proxy; fall back to direct in case the proxy itself is what's down.
  if curl -fs -o /dev/null --max-time 20 -x "$EGRESS_PROXY" \
       --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=${_text}" "$_url" 2>/dev/null || \
     curl -fs -o /dev/null --max-time 20 \
       --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=${_text}" "$_url" 2>/dev/null; then
    return 0
  fi
  echo "uap-healthcheck: Telegram send failed (proxy and direct)" >&2
  return 1
}

# (e) Proxmox VM backups: after the daily window, require a fresh archive for each critical VM and
# send one successful size report per Moscow calendar day. The state file prevents 20-minute spam.
pve_report_ok=0
pve_lines=""
pve_total=0
pve_now=$(date +%s)
pve_hhmm=$(TZ="$PVE_REPORT_TZ" date +%H%M)
pve_date=$(TZ="$PVE_REPORT_TZ" date +%F)
if [ "$pve_hhmm" -ge "$PVE_REPORT_AFTER" ]; then
  pve_data=$(ssh -T -i "$PVE_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
    -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "$PVE_SSH_TARGET" sh -s -- "$PVE_BACKUP_STORAGE" <<'REMOTE'
set -e
storage=$1
for archive in "/mnt/pve/$storage/dump"/vzdump-qemu-*.vma.zst; do
  [ -f "$archive" ] || continue
  log=${archive%.vma.zst}.log
  grep -q 'INFO: Finished Backup of VM ' "$log" 2>/dev/null || continue
  find "$archive" -maxdepth 0 -printf '%f|%T@|%s\n'
done
printf '__FREE__|'
df -B1 --output=avail "/mnt/pve/$storage" | tail -n 1 | tr -d ' '
REMOTE
  ) || pve_data=""

  if [ -z "$pve_data" ]; then
    add_fail "Proxmox backups: cannot read $PVE_BACKUP_STORAGE via $PVE_SSH_TARGET"
  else
    pve_report_ok=1
    for id in $PVE_BACKUP_VMIDS; do
      line=$(latest_backup "$pve_data" "$id")
      if [ -z "$line" ]; then
        add_fail "Proxmox backups: VM$id has no archive on $PVE_BACKUP_STORAGE"
        pve_report_ok=0
        continue
      fi
      file=$(printf '%s' "$line" | cut -d '|' -f 1)
      epoch=$(printf '%s' "$line" | cut -d '|' -f 2 | cut -d . -f 1)
      size=$(printf '%s' "$line" | cut -d '|' -f 3)
      age_h=$(( (pve_now - epoch) / 3600 ))
      if [ "$age_h" -gt "$PVE_BACKUP_MAX_AGE_H" ]; then
        add_fail "Proxmox backups: VM$id archive is ${age_h}h old (> ${PVE_BACKUP_MAX_AGE_H}h): $file"
        pve_report_ok=0
      fi
      human=$(numfmt --to=iec-i --suffix=B "$size")
      pve_lines="${pve_lines}- VM${id}: ${human}, age ${age_h}h
"
      pve_total=$((pve_total + size))
    done

    if [ "$pve_report_ok" -eq 1 ]; then
      free=$(printf '%s\n' "$pve_data" | awk -F '|' '$1=="__FREE__" {print $2}')
      total_h=$(numfmt --to=iec-i --suffix=B "$pve_total")
      free_h=$(numfmt --to=iec-i --suffix=B "${free:-0}")
      state_dir=${XDG_STATE_HOME:-$HOME/.local/state}/uap-healthcheck
      state_file=$state_dir/proxmox-report-date
      sent_date=$(cat "$state_file" 2>/dev/null || true)
      if [ "$sent_date" != "$pve_date" ] && [ -z "$fails" ]; then
        report="Proxmox backups OK for ${pve_date}:
${pve_lines}Total latest: ${total_h}
Free on backup-pve2: ${free_h}"
        if send_telegram "$report"; then
          mkdir -p "$state_dir"
          printf '%s\n' "$pve_date" > "$state_file"
          echo "uap-healthcheck: daily Proxmox report sent for $pve_date"
        fi
      fi
    fi
  fi
fi

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ -n "$fails" ]; then
  msg="UAP healthcheck FAILED on $(hostname) at ${now}:
${fails}"
  printf '%s\n' "$msg"          # -> journald
  send_telegram "$msg" || true
else
  echo "uap-healthcheck: all checks OK at ${now}"
fi
exit 0
