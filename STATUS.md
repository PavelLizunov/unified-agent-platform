# Current Status

Last updated: 2026-06-17

## Phase

- Current phase: **Stage 0P - Proxmox local bootstrap**.
- HA status: **not HA ready**. There are two local VMs; a third remote quorum member is still required for
  real 3-node k3s HA.
- k3s status: **local bootstrap is running on `uap-home-1` with `uap-home-2` joined as an agent**.

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

- Server installed on: `uap-home-1`.
- Agent installed on: `uap-home-2`.
- Version: `v1.35.5+k3s1`.
- Runtime: `containerd://2.2.3-k3s1`.
- Server internal IP: `100.106.223.120`.
- Agent internal IP: `100.94.228.67`.
- Config tracked at:
  - `infra/k3s/uap-home-1.config.yaml`
  - `infra/k3s/uap-home-2.agent.config.yaml`
- Local credential file: `kubeconfig.uap-home-1` (ignored by git).
- System pods verified Ready:
  - `coredns`
  - `local-path-provisioner`
  - `metrics-server`
- Smoke deployment verified with `registry.k8s.io/pause:3.10`.
- `uap-home-2` can reach `uap-home-1:6443` over tailnet.
- Scheduling on `uap-home-2` verified with a targeted `registry.k8s.io/pause:3.10` pod.
- Reboot test: passed. `uap-home-1` rebooted and k3s returned Ready.
- Manual etcd snapshot created and listed:
  - `uap-local-20260617T134555Z-uap-home-1-1781703956`
  - size: `1646624` bytes

## GitOps

- Flux installed: `v2.8.8`.
- Runtime controllers installed:
  - `source-controller`
  - `kustomize-controller`
  - `helm-controller`
  - `notification-controller`
- Image automation controllers are intentionally not installed.
- Flux manifests are pinned in `clusters/prod/flux-system/gotk-components.yaml`.
- SOPS/age configured:
  - public recipient stored in `.sops.yaml`;
  - private age key stored outside git on `uap-home-1`;
  - Kubernetes Secret: `flux-system/sops-age`.
- SOPS CLI installed on `uap-home-1`: `v3.13.1`.
- SOPS smoke fixture: `clusters/prod/infra/sops-smoke.sops.yaml`.
- SOPS decrypt smoke: passed with the node-local age key.
- Namespace applied from skeleton:
  - `uap-system`
- Remote Git sync is not enabled yet because no remote repository URL is configured.

## Repeatable Bootstrap

- OpenTofu/Terraform-compatible provisioning skeleton added under `infra/tofu`.
- Local Proxmox environment described at `infra/tofu/environments/local-proxmox`.
- Proxmox VM module added at `infra/tofu/modules/proxmox-vm`.
- Ansible bootstrap skeleton added under `infra/ansible`.
- Current local inventory: `infra/ansible/inventories/local.yml` uses tailnet IPs for SSH and keeps LAN IPs as metadata.
- Future 3-server template inventory: `infra/ansible/inventories/prod.example.yml`.
- Parameterized smoke-test config: `tests/smoke/uap-smoke-config.ps1`.
- Static IaC validation: `tests/static/validate-iac.ps1`.
- Local workstation currently does not have `tofu`, `terraform`, or `ansible` installed, so static validation skips
  those CLI-specific checks unless the tools are installed.

## Pending

1. Add a third server node before claiming k3s HA.
2. Decide whether the third node is a remote VPS or another independent failure domain.
3. Configure remote Git sync for Flux after a remote repository is available.
4. Install OpenTofu and Ansible on the operator machine or CI runner before using the new bootstrap layer end to end.
