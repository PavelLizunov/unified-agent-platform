# Cloudflare R2 for k3s Snapshots

## Why R2

Cloudflare R2 is the preferred near-free offsite target for the current scale:

- 10 GB-month free storage.
- 1M Class A operations and 10M Class B operations per month in the free tier.
- No egress fees.
- S3-compatible API.

This is intended for k3s etcd snapshots, not full Proxmox VM backups.

## Owner Inputs Needed

The owner must create the R2 bucket and provide:

- account id;
- bucket name;
- access key id;
- secret access key.

Do not paste keys into chat or commit them.

## Endpoint Shape

Cloudflare R2 S3 endpoint:

```text
https://<account-id>.r2.cloudflarestorage.com
```

Region can normally be `auto` for R2.

## Create Encrypted Secret

Use the plaintext template only as temporary stdin or a temporary file:

```powershell
Copy-Item .\infra\sops\templates\k3s-etcd-snapshot-s3-config.plaintext.template.yaml .\tmp\k3s-etcd-snapshot-s3-config.yaml
```

Fill placeholders locally, then encrypt:

```powershell
sops --encrypt `
  --encrypted-regex '^(data|stringData)$' `
  .\tmp\k3s-etcd-snapshot-s3-config.yaml `
  > .\clusters\prod\infra\k3s-etcd-snapshot-s3-config.sops.yaml
Remove-Item .\tmp\k3s-etcd-snapshot-s3-config.yaml -Force
```

Do not commit the plaintext temp file.

## Apply Secret

Before k3s can upload snapshots to S3, the Secret must exist in `kube-system`:

```powershell
scp .\clusters\prod\infra\k3s-etcd-snapshot-s3-config.sops.yaml uap@100.106.223.120:/tmp/k3s-etcd-snapshot-s3-config.sops.yaml
ssh uap@100.106.223.120 "SOPS_AGE_KEY_FILE=/home/uap/.config/sops/age/keys.txt sops -d /tmp/k3s-etcd-snapshot-s3-config.sops.yaml | sudo k3s kubectl apply -f -; rm -f /tmp/k3s-etcd-snapshot-s3-config.sops.yaml"
```

## Enable k3s S3 Snapshot Config

After the Secret exists, enable these k3s server config fields through Ansible or manual config:

```yaml
etcd-s3: true
etcd-s3-config-secret: k3s-etcd-snapshot-s3-config
```

Pass only those two S3 flags in k3s config. If other `etcd-s3-*` flags are set, k3s ignores the Secret.

## Verify

```powershell
ssh uap@100.106.223.120 'SNAP=uap-s3-smoke-$(date -u +%Y%m%dT%H%M%SZ); sudo k3s etcd-snapshot save --name $SNAP --s3'
ssh uap@100.106.223.120 "sudo k3s etcd-snapshot list --s3 | grep uap-s3-smoke-"
```

Pass criteria:

- snapshot save exits 0;
- `etcd-snapshot list --s3` shows the new snapshot.

## Restore Warning

The Kubernetes S3 config Secret cannot be used during restore because the API server is not available yet. For S3
restore, pass S3 settings directly to the restore command as described in `runbooks/restore-drill.md`.
