# Current Status

Last updated: 2026-06-17

## Phase

- Current phase: **Stage 0P - Proxmox local bootstrap**.
- HA status: **not HA ready**. There are two local VMs; a third remote quorum member is still required for
  real 3-node k3s HA.
- k3s status: **single-node local bootstrap is running on `uap-home-1`**.

## Proxmox

- Endpoint: `https://192.168.0.169:8006/` (local LAN only).
- Proxmox version observed: `8.4.1`.
- Online nodes:
  - `pve-ninitux`
  - `pve-ninitux3`
- Offline node observed:
  - `pve-ninitux2`
- Shared storage used: `nfs-share`.
- Bridge used: `vmbr0`.
- Storage change made: `nfs-share` content types now include `import` so cloud images can be imported.

## Created VMs

| VMID | Name | Proxmox node | IP | Resources | Status |
|---|---|---|---|---|---|
| 201 | `uap-home-1` | `pve-ninitux` | `192.168.0.201` | 4 vCPU, 8 GB RAM, 80 GB disk | running |
| 202 | `uap-home-2` | `pve-ninitux3` | `192.168.0.202` | 2 vCPU, 4 GB RAM, 32 GB disk | running |

## Tailnet

| Device | Tailnet name | Tailnet IP |
|---|---|---|
| `uap-home-1` | `uap-home-1.tail9fd337.ts.net` | `100.106.223.120` |
| `uap-home-2` | `uap-home-2.tail9fd337.ts.net` | `100.94.228.67` |
| Windows | `desktop-m922ij2.tail9fd337.ts.net` | `100.114.172.40` |
| Mac | `pavels-mac-mini.tail9fd337.ts.net` | `100.116.97.112` |

## VM Baseline

- OS: Debian 12 (bookworm).
- User: `uap`.
- SSH keys: from `infra/ssh/agent-authorized-keys.pub`.
- SSH hardening:
  - `PasswordAuthentication no`
  - `PermitRootLogin no`
- `sudo -n true`: verified for user `uap`.
- `qemu-guest-agent`: installed and active.
- Tailscale: installed and authenticated.

## k3s

- Installed on: `uap-home-1`.
- Version: `v1.35.5+k3s1`.
- Runtime: `containerd://2.2.3-k3s1`.
- Node internal IP: `100.106.223.120`.
- Config tracked at: `infra/k3s/uap-home-1.config.yaml`.
- Local credential file: `kubeconfig.uap-home-1` (ignored by git).
- System pods verified Ready:
  - `coredns`
  - `local-path-provisioner`
  - `metrics-server`
- Smoke deployment verified with `registry.k8s.io/pause:3.10`.
- `uap-home-2` can reach `uap-home-1:6443` over tailnet.

## Pending

1. Keep `uap-home-2` prepared for future join; do not run a 2-member etcd quorum as HA.
2. Add a third server node before claiming k3s HA.
3. Decide whether the third node is a remote VPS or another independent failure domain.
4. Later: install Flux/SOPS skeleton after local k3s bootstrap is stable.
