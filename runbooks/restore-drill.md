# k3s Restore Drill

## Scope

This runbook verifies that k3s embedded etcd snapshots can actually restore a cluster.

Do not run restore commands on `uap-home-1` or any live server unless you are intentionally recovering from a real
incident. The normal drill target is a disposable VM.

## Why This Exists

Listing snapshots proves that backup creation works. It does not prove recoverability.

K3s snapshots are encrypted with bootstrap data protected by the server token. Back up the snapshot and the server
token together, but never commit or print the token.

## Preconditions

- A disposable Debian 12 VM with SSH access.
- Tailscale connected if the disposable VM should use tailnet networking.
- Same k3s version as prod, or a later compatible minor version.
- A recent snapshot from `uap-home-1`.
- The original server token from `/var/lib/rancher/k3s/server/token` or `/var/lib/rancher/k3s/server/node-token`,
  stored temporarily outside git.

## Create a Fresh Snapshot

```powershell
ssh uap@100.106.223.120 'SNAP=uap-restore-drill-$(date -u +%Y%m%dT%H%M%SZ); sudo k3s etcd-snapshot save --name $SNAP'
ssh uap@100.106.223.120 'sudo k3s etcd-snapshot list | grep uap-restore-drill-'
```

Record the snapshot filename from the output.

## Copy Snapshot and Token

Use a secure temporary directory on the operator machine or transfer directly to the disposable VM.

Example shape:

```powershell
$snapshot = "REPLACE_WITH_SNAPSHOT_NAME"
New-Item -ItemType Directory -Force .\tmp | Out-Null
ssh uap@100.106.223.120 "sudo install -m 0640 /var/lib/rancher/k3s/server/db/snapshots/$snapshot /tmp/$snapshot && sudo chown uap:uap /tmp/$snapshot"
scp uap@100.106.223.120:/tmp/$snapshot .\tmp\$snapshot
ssh uap@100.106.223.120 "sudo rm -f /tmp/$snapshot"
ssh uap@100.106.223.120 "sudo cat /var/lib/rancher/k3s/server/token" > .\tmp\server-token
```

Delete the local token copy after the drill.

## Restore on Disposable VM

Prepare `/etc/rancher/k3s/config.yaml` for the disposable host. Use its own node name and tailnet IP.

Copy the snapshot and token to the disposable VM:

```powershell
scp .\tmp\$snapshot uap@DISPOSABLE_HOST:/tmp/$snapshot
scp .\tmp\server-token uap@DISPOSABLE_HOST:/tmp/server-token
```

On the disposable VM:

```bash
sudo systemctl stop k3s || true
sudo install -d -m 0700 /var/lib/rancher/k3s/server
sudo install -m 0600 /tmp/server-token /var/lib/rancher/k3s/server/token
sudo install -d -m 0700 /var/lib/rancher/k3s/server/db/snapshots
sudo install -m 0600 /tmp/REPLACE_WITH_SNAPSHOT_NAME /var/lib/rancher/k3s/server/db/snapshots/REPLACE_WITH_SNAPSHOT_NAME
sudo k3s server \
  --config /etc/rancher/k3s/config.yaml \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/REPLACE_WITH_SNAPSHOT_NAME
sudo systemctl start k3s
```

If the disposable VM does not yet have the k3s service installed, install the same pinned version first with start
disabled, then run the restore command.

## Verify

```bash
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get namespaces
sudo k3s kubectl -n flux-system get deploy
sudo k3s kubectl get secret -n flux-system sops-age
```

Pass criteria:

- API server answers.
- Restored cluster contains expected namespaces.
- Flux objects are visible.
- `sops-age` exists.

Do not join this disposable restored node back to the real cluster.

## Cleanup

```powershell
Remove-Item .\tmp\server-token -Force
```

Destroy the disposable VM after the drill or wipe `/var/lib/rancher/k3s`.

## S3 Restore Note

When restoring from S3, pass S3 configuration flags to the restore command. The Kubernetes S3 config Secret cannot be
used during restore because the API server is not available yet.
