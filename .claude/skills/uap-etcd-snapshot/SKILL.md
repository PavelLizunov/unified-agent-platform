---
name: uap-etcd-snapshot
description: Take a routine on-demand k3s etcd snapshot and confirm it reached offsite R2. Non-destructive. Use for ad-hoc backups. RESTORE is NOT covered here (it is destructive + owner-gated).
---

# uap-etcd-snapshot

## Save (on uap-home-1)

```bash
ssh uap@100.106.223.120 'SNAP=uap-local-$(date -u +%Y%m%d-%H%M%S); sudo k3s etcd-snapshot save --name $SNAP'
```

## EXPECTED warnings (do NOT treat as errors)

`k3s etcd-snapshot` may print warnings about server-only flags in /etc/rancher/k3s/config.yaml. This is documented and expected (CLAUDE.md -> Known Warnings, runbooks/k3s-snapshots.md).

## Offsite is automatic; ops-1 only CONFIRMS it

- The offsite copy is pushed by k3s-native **etcd-s3 -> Cloudflare R2** (configured per runbooks/cloudflare-r2-k3s-snapshots.md). It is NOT a separate rclone copy.
- Confirm the object landed (read-only) from uap-ops-1:
  ```bash
  ssh uap@100.82.241.121 'rclone lsf r2:uap-k3s-snapshots/prod/'
  ```

## Out of scope

- RESTORE (cluster-reset) is destructive and owner-gated — see runbooks/restore-drill.md, do not auto-run.

Authoritative reference: runbooks/k3s-snapshots.md, runbooks/offsite-backups.md, runbooks/validation-matrix.md.
