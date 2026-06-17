# k3s etcd Snapshots

## Current State

`uap-home-1` runs k3s with embedded etcd and local snapshot retention set to `7`.

Manual snapshot verified:

```text
uap-local-20260617T134555Z-uap-home-1-1781703956
1646624 bytes
```

## Create Manual Snapshot

```powershell
ssh uap@192.168.0.201 "SNAP=uap-local-$(date -u +%Y%m%dT%H%M%SZ); sudo k3s etcd-snapshot save --name $SNAP"
```

## List Snapshots

```powershell
ssh uap@192.168.0.201 "sudo k3s etcd-snapshot list"
```

The command may print warnings about server-only flags from `/etc/rancher/k3s/config.yaml`; the snapshot is
valid if it appears in `k3s etcd-snapshot list` and exists under:

```text
/var/lib/rancher/k3s/server/db/snapshots/
```

## Future Work

Add S3/offsite snapshot upload after object storage is available.
