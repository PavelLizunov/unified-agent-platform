# Ansible Bootstrap

Ansible configures Linux nodes after they exist. OpenTofu can create VMs/VPS, but Ansible owns:

- Debian package baseline.
- SSH hardening.
- Tailscale package/bootstrap.
- k3s server and agent installation.
- Flux/SOPS bootstrap.
- Operational validation.

## Inventories

- `inventories/local.yml`: current local Proxmox nodes.
- `inventories/prod.example.yml`: template for future 3-server topology.

`local.yml` also declares `uap-ops-1` under `ops_nodes`. It is intentionally not part of `linux_nodes`, `k3s_servers`,
or `k3s_agents`; it is an operator machine, not a cluster node.

Copy the example inventory before editing real hosts:

```powershell
Copy-Item .\infra\ansible\inventories\prod.example.yml .\infra\ansible\inventories\prod.yml
```

Do not commit private IPs, auth keys, passwords, or vault files unless they are deliberately public examples.

## Run

From repository root:

```powershell
ansible-playbook -i .\infra\ansible\inventories\local.yml .\infra\ansible\playbooks\00-preflight.yml
ansible-playbook -i .\infra\ansible\inventories\local.yml .\infra\ansible\playbooks\site.yml
```

For a fresh host where Tailscale is not already authenticated, export an auth key outside git:

```powershell
$env:TAILSCALE_AUTH_KEY = "REPLACE_WITH_TAILSCALE_AUTH_KEY"
```

Set `tailscale_manage: true` in inventory or group vars only when Ansible should install/authenticate Tailscale.

## Safety

- k3s tokens are fetched over SSH from the first server and copied with `no_log: true`.
- `uap-home-2` is an agent in `local.yml`, not a server.
- A third server must exist before the topology can be called HA.
- Flux Git sync is still manual until a remote Git URL exists.

## Local Static Validation

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\static\validate-iac.ps1
```
