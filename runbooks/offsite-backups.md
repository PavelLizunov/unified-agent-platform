# Offsite Backups

## Scope

This runbook defines the next backup layer beyond local k3s snapshots.

Current state:

- Local k3s etcd snapshots exist on `uap-home-1`.
- Proxmox VM backups are not yet configured in this repository.
- No S3-compatible offsite target is configured yet.

## k3s etcd Snapshots to S3

Preferred k3s path:

- Enable `etcd-s3`.
- Store S3 config in a Kubernetes Secret when the API is available.
- Keep S3 credentials encrypted with SOPS in git.
- For restore from S3, pass S3 flags directly because the Kubernetes Secret is unavailable before API restore.

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

## Verification Schedule

| Check | Frequency | Pass criteria |
|---|---|---|
| Local k3s snapshot list | daily/manual | recent snapshot listed |
| S3 snapshot list | after S3 is configured, then weekly | recent snapshot listed in S3 |
| k3s disposable restore | before claiming recovery readiness, then monthly | restored API answers |
| Proxmox backup list | weekly | recent VM backups exist |
| Proxmox clone restore | before relying on VM backups, then quarterly | restored clone boots and SSH works |

## Do Not

- Do not rely on a backup that has never been restored.
- Do not store k3s server token, S3 keys, Proxmox credentials, or kubeconfig in git.
- Do not test restore on the live server unless recovering from a real incident.
