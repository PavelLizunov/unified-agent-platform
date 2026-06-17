# OpenTofu / Terraform Provisioning

OpenTofu is the default CLI for this repository because it keeps the Terraform workflow while staying under an
open-source license. Terraform-compatible configurations are kept in `infra/tofu`; Terraform can be used when a
specific environment requires it, but examples and commands use `tofu`.

## Boundary

OpenTofu provisions infrastructure objects only:

- Proxmox VMs.
- Disks, CPU, memory, network devices.
- Cloud-init user/key/IP bootstrap.
- Outputs that can feed Ansible inventory.

OpenTofu must not configure k3s, Flux, SOPS, Tailscale, or application workloads via `remote-exec`. That work belongs
to Ansible and Flux.

## Environments

- `environments/local-proxmox`: current local Proxmox topology.
- `environments/prod-vps`: placeholder for future VPS provider modules.

The local Proxmox topology includes `uap-ops-1`, an optional operator/deploy VM for running OpenTofu, Ansible, Flux,
SOPS, and GitHub/Cloudflare setup without depending on the Windows workstation.

## Secrets

Do not commit `.tfvars`, state files, API tokens, or Proxmox passwords.

Use environment variables or a local ignored tfvars file:

```powershell
Copy-Item .\infra\tofu\environments\local-proxmox\terraform.tfvars.example .\infra\tofu\environments\local-proxmox\terraform.tfvars
```

Then edit `terraform.tfvars` locally.

## Local Validation

If OpenTofu is installed:

```powershell
cd .\infra\tofu\environments\local-proxmox
tofu fmt -check -recursive ..\..\..
tofu init
tofu validate
tofu plan
```

If OpenTofu is not installed, run the repository static checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\static\validate-iac.ps1
```
