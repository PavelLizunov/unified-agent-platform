# uap-ops-1 Operator Node

## Purpose

`uap-ops-1` is a disposable Linux operator node for deployment work:

- OpenTofu/Terraform plans;
- Ansible runs;
- Flux, kubectl, SOPS, age, GitHub CLI;
- encrypted secret preparation for GitHub and Cloudflare R2.

It is not a k3s node, not an etcd member, and not part of the HA claim.

## VM Profile

| Field | Value |
|---|---|
| Name | `uap-ops-1` |
| VMID | `203` |
| Proxmox node | `pve-ninitux` |
| LAN IP | `192.168.0.203/24` |
| Gateway | `192.168.0.1` |
| vCPU | `2` |
| RAM | `2048 MB` |
| Disk | `30 GB` |
| OS | Debian 12 cloud image |
| User | `uap` |

## Create VM From Proxmox Shell

Run this in the Proxmox web shell on `pve-ninitux`. It uses only public SSH keys.

```bash
set -euo pipefail

VMID=203
NAME=uap-ops-1
STORAGE=nfs-share
IMAGE="${STORAGE}:import/debian-12-genericcloud-amd64.qcow2"
BRIDGE=vmbr0
IP_CIDR=192.168.0.203/24
GW=192.168.0.1

qm status "$VMID" >/dev/null 2>&1 && {
  echo "VMID $VMID already exists"
  exit 0
}

cat >/tmp/uap-ops-keys.pub <<'EOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICBoHBbXoycbvIEhYYfvl9Ecp8nS3/U5bxw14NBUqeue claude-dev
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID+wMAOu8IYpw5SuFzEWbdJ0AINFC45dxY1txxd8zRcD claude-dev
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKlyYOxxDh3JjJeDnXA9eUdf9mpTRSCyOzvX9tg+DQPz claude-chat
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCrEPESuVIKgkG1o8UvlQ+VvD82y6eAhDHDe83CeGAZh9Jj8ySi50pmfa97U1V2cBZYo7peSRGh73k3e91VVw8pUplIiNrabM9oU8pNhKl0ZbKMIHoT4l4pJ0cewMNM+WV4P5ArYRB8DAk+mYWshH04NErryBJTuZs4nXHpktB321VlBXpNnaXwJnuCncdIiesf2XmzEls0EPCupuuiGRx7XNt6Le0XsjRlax1XKApJOZzeWbxLcTK7xfwahhHRbuEX/t1oWWU12Qd+C99nIydc7jVW+cMMA1dTl6wk/x04EeJxXQrEfzLRPvT+wIco/ORU3dBrAN0UgDGI+GAFAXSI5dBr5kO0tcgoz0DtRvELyxs9J53czcplThlRDfeo1VdHBg9HFEGQMflHMfV54tUhuUpapZOthR6WVyBxwRgfAMs8n3iIsRWPOZ/AcoYmSzSexF3xX+0ZgoqzmDQfHoeFqYQyeuDTrKVjnlT1WcJs0hE9PgeB4RNqvMEOCtOUTJbIcm6rdKkV1zxLtCEncd73Y6r697RkQ3XPKGQ3bZTIXyCXfYzLwlVZUZGXzPVCSFrolibj9LXcyvPU9DogTNHfw1gES75sVOsrS/AtuYW+IeTO+6mX0mrs2q9DCjzBwmAsLte70y3Mnzx2sqevzksfJ9KCmkJyv7xr3xzm+nNQuQ== slovn@mm4.local
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMwa9wAlEuUR6hD6AY/E1Px5sDKwBfqwH/eSLxXVJ+4J windows
EOF

qm create "$VMID" \
  --name "$NAME" \
  --memory 2048 \
  --cores 2 \
  --cpu host \
  --net0 "virtio,bridge=${BRIDGE}" \
  --scsihw virtio-scsi-single \
  --agent enabled=1 \
  --ostype l26 \
  --onboot 1

qm set "$VMID" --scsi0 "${STORAGE}:0,import-from=${IMAGE},discard=on,iothread=1"
qm resize "$VMID" scsi0 30G
qm set "$VMID" \
  --ide2 "${STORAGE}:cloudinit" \
  --boot order=scsi0 \
  --serial0 socket \
  --vga serial0 \
  --ciuser uap \
  --sshkeys /tmp/uap-ops-keys.pub \
  --ipconfig0 "ip=${IP_CIDR},gw=${GW}" \
  --nameserver "192.168.0.1 1.1.1.1" \
  --searchdomain local \
  --tags "uap;ops;managed-by-runbook"

qm start "$VMID"
rm -f /tmp/uap-ops-keys.pub
```

## Bootstrap Tools

From the repo on the workstation:

```powershell
scp .\infra\ops\bootstrap-ops-node.sh uap@192.168.0.203:/tmp/bootstrap-ops-node.sh
ssh uap@192.168.0.203 "sudo bash /tmp/bootstrap-ops-node.sh"
```

If the VM cannot download a release artifact from GitHub/CDN, copy the artifact to `/tmp` and rerun the same script.
The script checks these optional local files before downloading:

```text
/tmp/tofu_1.12.2_linux_amd64.zip
/tmp/flux_2.8.8_linux_amd64.tar.gz
/tmp/sops-v3.13.1.linux.amd64
```

Then authenticate Tailscale without putting auth keys in chat:

```powershell
ssh uap@192.168.0.203 "sudo tailscale up --hostname=uap-ops-1 --ssh=false"
```

## Verify

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\ops\check-ops-node.ps1 -Require
```

Expected:

- SSH works as `uap`;
- deploy tools exist: `git`, `ansible-playbook`, `tofu`, `kubectl`, `flux`, `sops`, `age`, `gh`, `tailscale`, `jq`;
- output contains `ops-node-ok`.

## Secrets

Do not paste GitHub or Cloudflare R2 tokens into chat.

Use the ops node shell for secret entry:

- `gh auth login` for GitHub;
- local `read -s` or `.env` files with `0600` permissions for temporary R2 values;
- SOPS-encrypted Kubernetes Secrets for anything committed to git.
