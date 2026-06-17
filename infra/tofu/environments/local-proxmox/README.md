# Local Proxmox Environment

This environment describes the current local Proxmox bootstrap target:

- `uap-home-1` on `pve-ninitux`.
- `uap-home-2` on `pve-ninitux3`.
- `uap-ops-1` on `pve-ninitux` as the optional operator/deploy node.

`uap-home-1`, `uap-home-2`, and `uap-ops-1` already exist at the moment. Import existing VMs into state before
allowing OpenTofu to manage them, or use this environment as the repeatable template for recreating the same topology.

## Import Existing VMs Later

Do this only after credentials are moved to a local ignored `terraform.tfvars` or environment variables:

```powershell
tofu init
tofu import 'module.nodes.proxmox_virtual_environment_vm.this["uap-home-1"]' pve-ninitux/201
tofu import 'module.nodes.proxmox_virtual_environment_vm.this["uap-home-2"]' pve-ninitux3/202
tofu import 'module.nodes.proxmox_virtual_environment_vm.this["uap-ops-1"]' pve-ninitux/203
tofu plan
```

Review the plan carefully. Do not apply a plan that destroys or recreates the current VMs unless that is intended.

## Fresh Create Later

Requirements:

- Debian 12 genericcloud image exists as `nfs-share:import/debian-12-genericcloud-amd64.qcow2`.
- `nfs-share` can hold VM disks.
- Static LAN IPs are free.
- Proxmox credentials are provided outside git.
