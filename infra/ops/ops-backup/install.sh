#!/usr/bin/env bash
# Install the ops-backup timer on uap-ops-1 (run AS the uap user on ops-1).
set -euo pipefail
src="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$HOME/ops-backup" "$HOME/.config/systemd/user"
install -m 0700 "$src/backup.sh"          "$HOME/ops-backup/backup.sh"
install -m 0644 "$src/ops-backup.service" "$HOME/.config/systemd/user/ops-backup.service"
install -m 0644 "$src/ops-backup.timer"   "$HOME/.config/systemd/user/ops-backup.timer"

# Linger lets --user timers fire without an active login session.
loginctl enable-linger "$USER" >/dev/null 2>&1 || true

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable --now ops-backup.timer
systemctl --user list-timers ops-backup.timer --all --no-legend || true
echo "ops-backup timer installed."
