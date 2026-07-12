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
- Created operator VM:
  - `uap-ops-1` / VMID `203` / `192.168.0.203`

Do not store Proxmox passwords or API tokens in this repository.

## Repeatable Provisioning Path

OpenTofu-compatible Terraform files now describe this local topology:

```text
infra/tofu/environments/local-proxmox
infra/tofu/modules/proxmox-vm
```

Use this layer for VM creation/import only. Do not use Terraform/OpenTofu `remote-exec` to install k3s.

Current VMs were created before this state existed. Import them before managing them with OpenTofu:

```powershell
cd .\infra\tofu\environments\local-proxmox
tofu init
tofu import 'module.nodes.proxmox_virtual_environment_vm.this["uap-home-1"]' pve-ninitux/201
tofu import 'module.nodes.proxmox_virtual_environment_vm.this["uap-home-2"]' pve-ninitux3/202
tofu plan
```

Review the first plan carefully. A plan that wants to recreate existing VMs is not safe to apply.

## Repeatable Configuration Path

Ansible inventory and playbooks are available under:

```text
infra/ansible
```

Local preflight:

```powershell
ansible-playbook -i .\infra\ansible\inventories\local.yml .\infra\ansible\playbooks\00-preflight.yml
```

Full local bootstrap path:

```powershell
ansible-playbook -i .\infra\ansible\inventories\local.yml .\infra\ansible\playbooks\site.yml
```

The local inventory keeps `uap-home-2` as a k3s agent. Do not move it to `k3s_servers` until a third independent
server node is ready.

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
write-kubeconfig-mode: "0600"
etcd-snapshot-retention: 7
```

Do not join `uap-home-2` as a second server until a third server is ready. A 2-member etcd cluster does not
survive loss of either member.

## Smoke Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\ssh-baseline.ps1
powershell -ExecutionPolicy Bypass -File .\tests\smoke\k3s-local.ps1
powershell -ExecutionPolicy Bypass -File .\tests\smoke\k3s-agent.ps1
powershell -ExecutionPolicy Bypass -File .\tests\smoke\run-all.ps1
powershell -ExecutionPolicy Bypass -File .\tests\static\validate-iac.ps1
```
