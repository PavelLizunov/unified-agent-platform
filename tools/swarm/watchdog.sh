#!/bin/bash
# Kanban worker max-runtime watchdog (build-1, cron */15).
# Finding SIM-1 #2: a wandering local-model worker heartbeats forever without progress —
# Hermes has no max-runtime guard. This kills worker PROCESSES older than WATCHDOG_MAX_S;
# the dispatcher then handles it (protocol violation -> retry; after limit -> blocked with reason).
# Process-level on purpose: no fragile kanban.db parsing; a legit slow worker just gets retried
# (tasks are idempotent, artifacts append). ponytail: alert-and-kill only; auto-unblock stays human.
MAX=${WATCHDOG_MAX_S:-3600}
LOG=$HOME/.hermes/watchdog.log
for pid in $(pgrep -f "work kanban task t_"); do
  et=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d " ")
  [ -z "$et" ] && continue
  if [ "$et" -gt "$MAX" ]; then
    cmd=$(ps -o args= -p "$pid" | grep -oE "t_[a-f0-9]+" | head -1)
    echo "$(date -Is) KILL pid=$pid age=${et}s task=$cmd (max=${MAX}s)" >> "$LOG"
    kill "$pid"
  fi
done
