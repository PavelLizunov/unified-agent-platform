---
name: uap-etcd-snapshot
description: Take a routine on-demand k3s etcd snapshot and confirm it reached offsite R2. Non-destructive. Use for ad-hoc backups. RESTORE is NOT covered here (it is destructive + owner-gated).
---

# uap-etcd-snapshot

## Save + verify offsite (on uap-home-1)

```bash
ssh uap@100.106.223.120 'SNAP=uap-local-$(date -u +%Y%m%d-%H%M%S); sudo k3s etcd-snapshot save --name "$SNAP" --s3 && sudo k3s etcd-snapshot list --s3 | grep -F "$SNAP"'
```

Success means the command exits 0 and prints the exact new snapshot name from the S3 list.

## EXPECTED warnings (do NOT treat as errors)

`k3s etcd-snapshot` may print warnings about server-only flags in /etc/rancher/k3s/config.yaml. This is documented and expected (AGENTS.md -> Known Warnings, runbooks/k3s-snapshots.md).

## Offsite details

- The offsite copy is pushed by k3s-native **etcd-s3 -> Cloudflare R2** (configured per runbooks/cloudflare-r2-k3s-snapshots.md). It is NOT a separate rclone copy.
- The exact-name `etcd-snapshot list --s3` check above is the confirmation; a generic bucket listing is not sufficient.

## Out of scope

- RESTORE (cluster-reset) is destructive and owner-gated — see runbooks/restore-drill.md, do not auto-run.

Authoritative reference: runbooks/k3s-snapshots.md, runbooks/offsite-backups.md, runbooks/validation-matrix.md.
