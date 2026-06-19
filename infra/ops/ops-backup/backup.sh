#!/usr/bin/env bash
# ops-backup: age-encrypted offsite backup of uap-ops-1 stateful services to R2.
#
# Backs up: Vaultwarden data (consistent sqlite snapshot + identity key),
# ~/.secrets (sing-box / VLESS egress config), and ~/.config/systemd/user units.
# The archive is age-encrypted to the SOPS recipient before upload, so R2 only
# ever holds ciphertext. Decryption requires the age PRIVATE key, kept in an
# off-homelab escrow (see runbooks/uap-ops-services-backup.md).
#
# CAVEAT (REVIEW-CODEX.md #1): the R2 credential on this host can also delete
# these objects. Until the R2 token is bucket-scoped + a lifecycle/versioning
# policy exists, an ops-1 compromise can erase these backups. This script closes
# the "no backup exists" gap; it does not by itself fix the blast-radius gap.
set -euo pipefail

AGE_RECIPIENT="age1ellxh9rynjv2n2sau9mekpt3qmt7r9w7t7zqjj6plx3nd2d0cg9sys9s85"
R2_PREFIX="r2:uap-k3s-snapshots/ops-backup"
KEEP=14

ts="$(date -u +%Y%m%dT%H%M%SZ)"
host="$(hostname)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stage="$work/stage"
mkdir -p "$stage"

# 1) Vaultwarden: consistent sqlite snapshot (handles -wal/-shm) + identity key.
vw="$HOME/vaultwarden/data"
if [ -d "$vw" ]; then
  mkdir -p "$stage/vaultwarden"
  if [ -f "$vw/db.sqlite3" ]; then
    sqlite3 "$vw/db.sqlite3" ".backup '$stage/vaultwarden/db.sqlite3'"
  fi
  for f in rsa_key.pem rsa_key.pub.pem config.json; do
    [ -f "$vw/$f" ] && cp -a "$vw/$f" "$stage/vaultwarden/"
  done
  for d in attachments sends; do
    [ -d "$vw/$d" ] && cp -a "$vw/$d" "$stage/vaultwarden/"
  done
fi

# 2) ops egress secrets + systemd --user units + serve recovery hint.
mkdir -p "$stage/ops"
[ -d "$HOME/.secrets" ] && cp -a "$HOME/.secrets" "$stage/ops/secrets"
[ -d "$HOME/.config/systemd/user" ] && cp -a "$HOME/.config/systemd/user" "$stage/ops/systemd-user"
if command -v tailscale >/dev/null; then
  tailscale serve status > "$stage/ops/tailscale-serve-status.txt" 2>/dev/null || true
fi

# 3) tar -> integrity-check -> age-encrypt -> upload.
tar="$work/ops-$host-$ts.tar.gz"
tar -czf "$tar" -C "$stage" .
tar -tzf "$tar" >/dev/null   # fail before upload if the archive is corrupt
age -r "$AGE_RECIPIENT" -o "$tar.age" "$tar"
rclone copyto "$tar.age" "$R2_PREFIX/ops-$host-$ts.tar.gz.age"

# 4) retention: keep the most recent $KEEP, delete older.
old="$(rclone lsf "$R2_PREFIX/" 2>/dev/null | grep -E '\.tar\.gz\.age$' | sort | head -n "-$KEEP" || true)"
if [ -n "$old" ]; then
  while IFS= read -r o; do
    [ -n "$o" ] && rclone deletefile "$R2_PREFIX/$o"
  done <<< "$old"
fi

echo "ops-backup: uploaded $R2_PREFIX/ops-$host-$ts.tar.gz.age"
