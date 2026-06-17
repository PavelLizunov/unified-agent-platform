# Proxmox Inventory

## Endpoint

- UI/API: `https://192.168.0.169:8006/`
- Scope: local LAN only.
- Secrets: do not store Proxmox passwords or API tokens in this repository.

## Physical Nodes

| Proxmox node | Role | Resource policy |
|---|---|---|
| `pve-ninitux` | primary local node | may allocate generous resources |
| `pve-ninitux3` | spare local node | keep minimal, target 2-4 GB RAM for UAP VM |

## Planned UAP VMs

| VM | Proxmox node | Role | Target resources |
|---|---|---|---|
| `uap-home-1` | `pve-ninitux` | primary k3s server, main local workload node | VMID 201, `192.168.0.201`, 4 vCPU, 8 GB RAM, 80 GB disk |
| `uap-home-2` | `pve-ninitux3` | secondary local k3s server / future HA quorum member | VMID 202, `192.168.0.202`, 2 vCPU, 4 GB RAM, 32 GB disk |
| `uap-vps-1` | remote provider, later | third k3s server / quorum member | budget profile |

## Notes

- Two local servers plus one remote VPS can form a 3-member etcd quorum, but this topology does not survive
  full local-site failure.
- If `uap-home-1` and `uap-home-2` are VMs on different physical Proxmox nodes, they are useful for local
  failover testing. If they share storage/network/power, that shared domain remains a platform risk.
- Public SSH keys for created servers live in `infra/ssh/agent-authorized-keys.pub`.
