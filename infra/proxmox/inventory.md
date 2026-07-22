# Proxmox Inventory

The machine-readable source of truth is
[`infra/ops/proxmox-machines.txt`](../ops/proxmox-machines.txt). The existing ops-1 healthcheck
compares that file with the live cluster every 20 minutes and checks every `tailnet` entry. This page
records topology and intent; it is no longer a planned-only VM list.

## Endpoint

- UI/API: `https://192.168.0.169:8006/`
- Scope: local LAN only.
- Secrets: do not store Proxmox passwords or API tokens in this repository.

## Physical Nodes

| Proxmox node | Role | Resource policy |
|---|---|---|
| `pve-ninitux` | primary local node | may allocate generous resources |
| `pve-ninitux2` | backup target and lightweight test LXC host | excluded from its own NFS backup target |
| `pve-ninitux3` | build/worker and service host | avoid build/worker disk contention |

## Managed targets

| VM | Proxmox node | Role | Target resources |
|---|---|---|---|
| `uap-home-1` | `pve-ninitux` | primary k3s server, main local workload node | VMID 201, `192.168.0.201`, 4 vCPU, 8 GB RAM, 80 GB disk |
| `uap-home-2` | `pve-ninitux3` | k3s agent | VMID 202, tailnet `uap-home-2` |
| `uap-ops-1` | `pve-ninitux` | operator/deploy authority | VMID 203, tailnet `uap-ops-1` |
| `uap-build-1` | `pve-ninitux3` | builds and delivery coordinator | VMID 102, tailnet `uap-build-1` |
| `windows-brat` | `pve-ninitux` | VPNRouter Windows test target | VMID 100, tailnet `windows-brat` |
| `debian-xfce` | `pve-ninitux` | VPNRouter Debian test target | VMID 101, tailnet `debian-xfce` |
| `vpnctld` | `pve-ninitux3` | vpnctl production control plane | VMID 119, LAN `192.168.0.236`, required tailnet `vpnctld` |

## Notes

- Two local servers plus one remote VPS can form a 3-member etcd quorum, but this topology does not survive
  full local-site failure.
- If `uap-home-1` and `uap-home-2` are VMs on different physical Proxmox nodes, they are useful for local
  failover testing. If they share storage/network/power, that shared domain remains a platform risk.
- Public SSH keys for created servers live in `infra/ssh/agent-authorized-keys.pub`.
- Proxmox hosts and the `ingress` LXC remain LAN-only intentionally. Tailscale is required for
  active UAP build/test/deploy guests, not for every unrelated, legacy, game or template workload.
