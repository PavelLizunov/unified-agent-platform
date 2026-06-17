# Proxmox Local Bootstrap Runbook

## Scope

This runbook describes the local bootstrap path for the Unified HA Agent Platform on Proxmox.
It is not the final HA topology. The local bootstrap exists to prepare reproducible Linux nodes before a
remote quorum member is available.

## Inventory

- Proxmox endpoint: `https://192.168.0.169:8006/`
- Primary Proxmox node: `pve-ninitux`
- Spare Proxmox node: `pve-ninitux3`
- Created VMs:
  - `uap-home-1` / VMID `201` / `192.168.0.201`
  - `uap-home-2` / VMID `202` / `192.168.0.202`

Do not store Proxmox passwords or API tokens in this repository.

## Baseline Checks

```powershell
ssh uap@192.168.0.201 "hostname; id; sudo -n true && echo sudo-ok"
ssh uap@192.168.0.202 "hostname; id; sudo -n true && echo sudo-ok"
```

Expected:

- Debian 12.
- User `uap` exists.
- Passwordless sudo works.
- SSH password auth is disabled.
- Root SSH login is disabled.

## Tailscale

Tailscale is installed and authorized.

```bash
sudo tailscale up --hostname=uap-home-1 --ssh=false
sudo tailscale up --hostname=uap-home-2 --ssh=false
```

After login:

```bash
tailscale status
tailscale ip -4
```

Record the tailnet IPs in `STATUS.md` or the future inventory file.

## k3s Local Bootstrap

Install k3s only after Tailscale is online. Use the tailnet IP and interface, not the LAN IP, for the k3s
node identity.

Current `uap-home-1` config:

```yaml
cluster-init: true
node-name: uap-home-1
node-ip: 100.106.223.120
advertise-address: 100.106.223.120
flannel-iface: tailscale0
tls-san:
  - 100.106.223.120
  - uap-home-1.tail9fd337.ts.net
disable:
  - traefik
  - servicelb
secrets-encryption: true
write-kubeconfig-mode: "0644"
etcd-snapshot-retention: 7
```

Do not join `uap-home-2` as a second server until a third server is ready. A 2-member etcd cluster does not
survive loss of either member.

## Smoke Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\ssh-baseline.ps1
powershell -ExecutionPolicy Bypass -File .\tests\smoke\k3s-local.ps1
```
