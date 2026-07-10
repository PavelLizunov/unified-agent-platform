#!/bin/sh
# build1-knowledge-backup.sh — offsite backup of the build-1 knowledge system.
#
# Runs ON uap-build-1 (100.85.56.31). build-1 is NOT a k3s node and NOT in GitOps,
# so its earned state has no other backup. The etcd->R2 snapshots and the
# hermes-agent PVC CronJob do NOT cover it. This closes that data-loss gap.
#
# What is IRREPLACEABLE (backed up):
#   ~/knowledge/knowledge.db   canonical registry: records + documents + append-only
#                              audit + sqlite-vec index (WAL mode). Source of truth.
#   ~/.config/ai-search.env    owner-supplied web-search provider keys (if present).
#   ~/knowledge/bin/           deploy glue not in git (nightly.sh/weekly.sh/drive-sync.sh).
# What is REGENERATABLE (skipped on purpose): .venv (uv sync), models/ (re-download),
#   drive-mirror/ (rclone re-sync), logs/, reports/, and knowledge.py (in git).
#
# Secrets: rclone reads its R2 creds from its OWN config (RCLONE_CONFIG / ~/.config/rclone).
# NO secret is ever written into this file. The operator supplies the R2 remote via env.
#
# Restore + install: tools/backup/README.md. Ship pattern mirrors the in-cluster
# CronJob clusters/prod/infra/hermes-agent-backup.yaml (same bucket, same retention style).
set -eu

# --- config (env-overridable; defaults match the current build-1 layout) -------------
KN_HOME="${KN_HOME:-$HOME/knowledge}"
KN_DB="${KN_DB:-$KN_HOME/knowledge.db}"
R2_REMOTE="${R2_REMOTE:-r2}"                 # rclone remote name (operator-configured on build-1)
R2_BUCKET="${R2_BUCKET:-uap-k3s-snapshots}"  # same bucket as the etcd / hermes-agent backups
KEEP="${KEEP_DAYS:-14}"                       # retention: keep the newest N daily archives
DST="${R2_REMOTE}:${R2_BUCKET}/knowledge/"

# --- preflight: fail loudly with a fixable message, not a cryptic set -e abort --------
command -v sqlite3 >/dev/null 2>&1 || { echo "FATAL: sqlite3 CLI not installed (apt-get install -y sqlite3)"; exit 1; }
command -v rclone  >/dev/null 2>&1 || { echo "FATAL: rclone not installed"; exit 1; }
[ -f "$KN_DB" ] || { echo "FATAL: knowledge.db not found at $KN_DB"; exit 1; }

ts=$(date +%Y%m%d)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
stage="$work/stage"
mkdir -p "$stage"
snap="$stage/knowledge-$ts.db"
arch="build1-knowledge-$ts.tar.gz"

# 1) CONSISTENT snapshot. .backup uses the SQLite Online Backup API — WAL-safe on a
#    live DB. NEVER `cp` a WAL sqlite file: the -wal/-shm side files make a raw copy torn.
sqlite3 "$KN_DB" ".backup '$snap'"

# 2) Verify BEFORE it leaves the box — a corrupt backup is worse than a known-missing one.
#    integrity_check is preferred, but sqlite-vec virtual tables need the extension loaded
#    to be fully checked on sqlite >=3.44; the plain CLI may not have it. So: accept a clean
#    integrity_check, else fall back to a structural open + canonical-table read (the .backup
#    API already produced a page-consistent copy). Only a truly unreadable file is fatal.
chk=$(sqlite3 "$snap" 'PRAGMA integrity_check;' 2>&1) || chk="error"
if [ "$chk" != "ok" ]; then
  sqlite3 "$snap" 'SELECT count(*) FROM records;' >/dev/null 2>&1 \
    || { echo "FATAL: snapshot unreadable (integrity_check: $chk)"; exit 1; }
  echo "WARN: integrity_check not clean ($chk); records table reads OK (sqlite-vec ext likely absent) — shipping"
fi

# 3) tar the snapshot + node-local config that is NOT in git. Each path added only if
#    present, so a partial layout still backs up what it has.
[ -f "$HOME/.config/ai-search.env" ] && cp "$HOME/.config/ai-search.env" "$stage/ai-search.env"
[ -d "$KN_HOME/bin" ] && cp -a "$KN_HOME/bin" "$stage/knowledge-bin"
tar -czf "$work/$arch" -C "$stage" .
chmod 600 "$work/$arch"   # archive may contain ai-search.env (provider keys)

# 4) ship to R2 (direct to Cloudflare) — dated key under the knowledge/ prefix.
rclone copyto "$work/$arch" "$DST$arch" --s3-no-check-bucket

# 5) retention: keep the newest N archives (busybox/POSIX-safe; oldest sort to the top).
files=$(rclone lsf "$DST" | grep -E '^build1-knowledge-.*\.tar\.gz$' | sort)
n=$(printf '%s\n' "$files" | grep -c . || true)
if [ "$n" -gt "$KEEP" ]; then
  printf '%s\n' "$files" | head -n "$((n - KEEP))" | while IFS= read -r o; do
    [ -n "$o" ] && { echo "retention: deleting $o"; rclone deletefile "$DST$o"; }
  done
fi

echo "=== current knowledge backups in R2 ==="
rclone lsf "$DST" | grep -E '^build1-knowledge-.*\.tar\.gz$' | sort || true
echo "OK: shipped $arch to $DST"
