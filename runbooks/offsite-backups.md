# Offsite Backups

## Scope

This runbook defines the next backup layer beyond local k3s snapshots.

Current state:

- Local k3s etcd snapshots exist on `uap-home-1`.
- k3s `etcd-s3` -> Cloudflare R2 (EU endpoint) is configured; a restore drill from R2 passed (2026-06-19).
- Bootstrap DR materials (server token + `encryption-config.json`, age-encrypted) are in R2 `dr/` for cross-node restore.
- Proxmox VM backups run daily to a separate physical disk on `pve-ninitux2`; the 2026-07-13 VM203
  canary archive passed an isolated restore and `qemu-img check`.

## k3s etcd Snapshots to S3

Preferred k3s path:

- Enable `etcd-s3`.
- Store S3 config in a Kubernetes Secret when the API is available.
- Keep S3 credentials encrypted with SOPS in git.
- For restore from S3, pass S3 flags directly because the Kubernetes Secret is unavailable before API restore.
- For a **cross-node** restore, keep the server token outside git. The 2026-07-12 canary drill proved that the
  snapshot + original token restore encrypted Secret values on a clean host; a separate
  `server/cred/encryption-config.json` is belt-and-suspenders, not required. See `runbooks/restore-drill.md`.

Example Secret shape:

```text
infra/k3s/examples/k3s-etcd-snapshot-s3-config.example.yaml
infra/sops/templates/k3s-etcd-snapshot-s3-config.plaintext.template.yaml
```

Do not commit real S3 credentials.

Provider-specific setup:

- `runbooks/cloudflare-r2-k3s-snapshots.md`

## Proxmox VM Backups

Live topology (2026-07-13):

- `pve-ninitux2` exports `/srv/pve-backups` from its local `/dev/sda1`.
- Only `pve-ninitux` (`192.168.0.169`) and `pve-ninitux3` (`192.168.0.171`) may mount it.
- Proxmox storage `backup-pve2` permits only `backup` content and explicitly excludes `pve-ninitux2`.
- Job `uap-critical-daily` runs at `03:15` for VMIDs `102,201,202,203` in snapshot mode, capped at
  50 MiB/s with one zstd thread and idle I/O priority.
- Retention is `keep-last=2,keep-weekly=2,keep-monthly=1`. The protected VMs currently occupy about
  62 GB before compression; the target has about 429 GB free.

This layout is intentional. Never target `nfs-share`: the UAP VM disks already live there, and a VM203
backup to that same self-mounted export hung NFS and required a host reboot on 2026-07-12. Do not add
`pve-ninitux2` to `backup-pve2`'s `nodes` list; an NFS server mounting its own export reintroduces the
shutdown-hang class.

Rebuild the NFS target on `pve-ninitux2`:

```bash
apt-get install -y nfs-kernel-server
install -d -m 0755 /etc/exports.d
install -d -o nobody -g nogroup -m 0750 /srv/pve-backups
printf '%s\n' '/srv/pve-backups 192.168.0.169(rw,sync,no_subtree_check,root_squash) 192.168.0.171(rw,sync,no_subtree_check,root_squash)' \
  > /etc/exports.d/pve-backups.exports
exportfs -ra
systemctl enable --now nfs-server
```

Recreate the cluster storage and job from either allowed Proxmox node:

```bash
pvesm add nfs backup-pve2 \
  --server 192.168.0.170 --export /srv/pve-backups --content backup \
  --nodes pve-ninitux,pve-ninitux3 --options vers=4.2 \
  --prune-backups keep-last=2,keep-weekly=2,keep-monthly=1

pvesh create /cluster/backup \
  --id uap-critical-daily --enabled 1 --schedule '03:15' \
  --storage backup-pve2 --vmid '102,201,202,203' --mode snapshot \
  --compress zstd --zstd 1 --bwlimit 51200 --ionice 8 --repeat-missed 0 \
  --prune-backups keep-last=2,keep-weekly=2,keep-monthly=1 \
  --notification-mode legacy-sendmail --mailnotification failure
```

The legacy notification mode avoids the default empty `mail-to-root` target. Add a real Proxmox
notification recipient before switching back to `notification-system`.

Weekly verification from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\ops\check-proxmox-backups.ps1 -Require
```

`uap-healthcheck.timer` on ops-1 also checks these four VMIDs every 20 minutes after `05:00
Europe/Moscow`. Missing/stale archives trigger the existing Telegram alert; a healthy set produces
one daily Telegram report with per-VM sizes, total size and remaining free space.

The 2026-07-13 restore proof used a disposable, never-started VMID on `pve-ninitux2`: `zstd -t` on the
archive, `qmrestore --storage local --unique 1`, `qemu-img check` on the restored disk, then guarded
`qm destroy`. Repeat quarterly with a fresh unused VMID. Never start the clone: its restored guest IP
matches production even though `--unique` changes the MAC.

Rollback (does not delete existing archives):

```bash
pvesh delete /cluster/backup/uap-critical-daily
pvesm remove backup-pve2
# On pve-ninitux2 only:
rm /etc/exports.d/pve-backups.exports
exportfs -ra
```

## Off-cluster node state (build-1 + ops-1)

Two always-on VMs hold earned state that is **not** a k3s node and **not** in GitOps, so
neither the etcd→R2 snapshots nor the in-cluster `hermes-agent-backup` CronJob cover them:

- **build-1** — the knowledge system SQLite registry `~/knowledge/knowledge.db` (canonical
  records + audit + sqlite-vec index) is the one irreplaceable piece. Backed up nightly to
  R2 (`uap-k3s-snapshots/knowledge/`) by `tools/backup/build1-knowledge-backup.sh` +
  its systemd timer. Consistent snapshot via `sqlite3 .backup` (WAL-safe), tarred with the
  small node-local config (`~/.config/ai-search.env`, `~/knowledge/bin/`). Install + **restore**
  procedure: `tools/backup/README.md`. Mirrors the hermes CronJob (same bucket, retention style).
- **ops-1** — the `local-model-router` config (Hermes brain endpoint
  `http://100.82.241.121:8090/v1`). Its code `tools/local-models/route.py` is in git; only the
  systemd unit is node-local — capture it out-of-band (see the ops-1 section of
  `tools/backup/README.md`). A `ROUTER_KEY`, if set, is a secret → SOPS it, do not ship plaintext.

## Verification Schedule

| Check | Frequency | Pass criteria |
|---|---|---|
| Local k3s snapshot list | daily/manual | recent snapshot listed |
| S3 snapshot list | after S3 is configured, then weekly | recent snapshot listed in S3 |
| k3s disposable restore | before claiming recovery readiness, then monthly | restored API answers |
| build-1 knowledge backup list | weekly | recent `build1-knowledge-*.tar.gz` in R2 `knowledge/` |
| build-1 knowledge restore | before relying on it, then quarterly | `PRAGMA integrity_check` = ok, `knowledge stats` sane |
| Proxmox backup list | weekly | recent VM backups exist |
| Proxmox clone restore | before relying on VM backups, then quarterly | restored clone boots and SSH works |

## Do Not

- Do not rely on a backup that has never been restored.
- Do not store k3s server token, S3 keys, Proxmox credentials, or kubeconfig in git.
- Do not test restore on the live server unless recovering from a real incident.
