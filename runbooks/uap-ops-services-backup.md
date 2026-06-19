# uap-ops-1 Services Backup & Recovery

`uap-ops-1` runs stateful services that are **not** in GitOps and were previously not backed up
(REVIEW-CODEX.md: "No backup automation for the Vaultwarden SQLite DB", "No documented recovery procedure for
ops-1 services if VM dies"). This runbook closes that gap.

## What is backed up

A daily `systemd --user` timer (`ops-backup.timer`) runs `~/ops-backup/backup.sh`, which collects:

- **Vaultwarden** `~/vaultwarden/data`: a consistent `sqlite3 .backup` of `db.sqlite3` (handles `-wal`/`-shm`),
  plus `rsa_key.pem` (JWT identity key), `config.json`, and `attachments/`, `sends/` if present.
- **Egress secrets** `~/.secrets`: sing-box / VLESS client config (`sb-client.json`, etc.).
- **systemd --user units** `~/.config/systemd/user`: the `sing-box-egress` and `vaultwarden` service definitions.
- A `tailscale serve status` snapshot, so the HTTPS exposure can be re-created.

The archive is **age-encrypted to the SOPS recipient** (`age1ellxh9...`) before upload, so R2 holds only
ciphertext. It lands in `r2:uap-k3s-snapshots/ops-backup/ops-<host>-<UTC>.tar.gz.age`, retaining the last 14.

Source of truth for the scripts/units: `infra/ops/ops-backup/` in this repo.

## Install / re-install (run as `uap` on uap-ops-1)

```bash
cd ~/unified-agent-platform/infra/ops/ops-backup
./install.sh
# verify
systemctl --user list-timers ops-backup.timer --all
```

Run an immediate backup (does not wait for the timer):

```bash
systemctl --user start ops-backup.service
journalctl --user -u ops-backup.service -n 20 --no-pager
rclone lsf r2:uap-k3s-snapshots/ops-backup/
```

## Restore (rebuild ops-1, or recover a lost service)

Prerequisite: the age **private** key from the off-homelab escrow (NOT on the homelab). See
`runbooks/restore-drill.md` — the same key decrypts the `dr/` materials and these backups.

```bash
# 1. fetch the latest archive
rclone lsf r2:uap-k3s-snapshots/ops-backup/ | sort | tail -1   # pick newest
rclone copyto r2:uap-k3s-snapshots/ops-backup/<name>.tar.gz.age /tmp/ops.tar.gz.age

# 2. decrypt with the escrow private key, then extract
age -d -i /path/to/escrow/keys.txt -o /tmp/ops.tar.gz /tmp/ops.tar.gz.age
mkdir -p /tmp/ops && tar -xzf /tmp/ops.tar.gz -C /tmp/ops

# 3. restore Vaultwarden (stop the container first)
systemctl --user stop vaultwarden.service
cp -a /tmp/ops/vaultwarden/db.sqlite3 ~/vaultwarden/data/db.sqlite3
cp -a /tmp/ops/vaultwarden/rsa_key.pem ~/vaultwarden/data/rsa_key.pem
chmod 600 ~/vaultwarden/data/rsa_key.pem
systemctl --user start vaultwarden.service

# 4. restore egress secrets + units
cp -a /tmp/ops/ops/secrets/.      ~/.secrets/
cp -a /tmp/ops/ops/systemd-user/. ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart sing-box-egress.service

# 5. re-create the Tailscale Serve exposure (see tailscale-serve-status.txt for the prior config)
tailscale serve --bg --https=443 http://127.0.0.1:8222

# 6. shred the staging copies (they contain plaintext secrets)
shred -u /tmp/ops.tar.gz.age /tmp/ops.tar.gz
rm -rf /tmp/ops
```

## Verification schedule

| Check | Frequency | Pass criteria |
|---|---|---|
| ops-backup timer active | weekly | `systemctl --user list-timers ops-backup.timer` shows a next run |
| ops-backup object exists | weekly | a recent `ops-<host>-*.tar.gz.age` in `r2:.../ops-backup/` |
| ops-backup decrypt+extract | quarterly | archive decrypts with the escrow key and `tar -tzf` lists Vaultwarden + secrets |

## Caveats

- **Blast radius (REVIEW-CODEX.md #1):** the R2 credential on ops-1 can also delete these objects. Until the R2
  token is bucket-scoped and a lifecycle/versioning policy exists, an ops-1 compromise can erase the backups.
- These backups protect against VM/disk loss; they do **not** replace migrating these services into the cluster
  (Stage 3), which is the durable fix for the ops-1 SPOF.
