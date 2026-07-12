# Offsite Backups

## Scope

This runbook defines the next backup layer beyond local k3s snapshots.

Current state:

- Local k3s etcd snapshots exist on `uap-home-1`.
- k3s `etcd-s3` -> Cloudflare R2 (EU endpoint) is configured; a restore drill from R2 passed (2026-06-19).
- Bootstrap DR materials (server token + `encryption-config.json`, age-encrypted) are in R2 `dr/` for cross-node restore.
- Proxmox VM backups are not yet configured in this repository.

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

Use Proxmox vzdump or Proxmox Backup Server for VM-level recovery:

- Schedule backups for `uap-home-1` and `uap-home-2`.
- Store backups outside the same physical host where possible.
- Configure retention/prune.
- Test restoring a VM clone, not only backup creation.

Suggested initial retention:

- Keep last 3 daily.
- Keep last 4 weekly.
- Keep last 3 monthly.

Tune after actual storage size is known.

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
