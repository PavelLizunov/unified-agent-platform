# Claude Code Handoff

This file is the current operational handoff for Claude Code. It complements `AGENTS.md`; it does not replace the
project decisions in `DECISIONS.md`.

## Read First

1. `AGENTS.md`
2. `README.md`
3. `DECISIONS.md`
4. `BUILD-PLAN.md`
5. `STATUS.md`
6. `runbooks/validation-matrix.md`

If any instruction conflicts, follow `AGENTS.md` and `DECISIONS.md`, then ask the owner before changing direction.

## Current State

- Current phase: Stage 0P, local Proxmox bootstrap.
- HA status: not HA ready.
- Reason: only two local VMs exist; a third independent k3s server is still required.
- Git branch: `master`.
- Latest known commits:
  - `eaffba8 Add validation matrix and recovery drills`
  - `753b68a Add repeatable OpenTofu and Ansible bootstrap`
  - `88e5a27 Join local k3s agent and add SOPS smoke`

## Live Nodes

Use tailnet IPs for SSH and smoke tests.

| Node | Role | LAN IP | Tailnet IP | Notes |
|---|---|---|---|---|
| `uap-home-1` | k3s server, embedded etcd | `192.168.0.201` | `100.106.223.120` | control-plane/etcd |
| `uap-home-2` | k3s agent | `192.168.0.202` | `100.94.228.67` | worker only |

Do not rely on LAN SSH as the default path. LAN SSH has shown intermittent resets; tailnet SSH is the stable path.

## Important Boundaries

- Do not claim HA readiness until a third independent k3s server is added and failover passes.
- Do not turn `uap-home-2` into a second etcd/server node by itself. A 2-member etcd cluster is not HA.
- Do not include Windows or Mac in k3s or etcd quorum. They are future external agent-workers only.
- Do not commit secrets, kubeconfigs, k3s tokens, age private keys, Proxmox credentials, Tailscale auth keys, or API keys.
- Do not use Terraform/OpenTofu `remote-exec` for k3s installation. OpenTofu provisions infra; Ansible configures OS/k3s; Flux owns Kubernetes contents.
- Do not add heavy controllers without a current milestone reason and dependency-budget note.

## Validation Command

Run this before handing work back:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1
```

Current expected result:

- `secret-scan-ok`
- `iac-static-ok`
- smoke tests pass against `100.106.223.120` and `100.94.228.67`
- `verify-local-ok`

Current workstation does not have `tofu`, `terraform`, or `ansible` installed. The static validator skips CLI-specific
checks until those tools exist.

## Useful Commands

Check git state:

```powershell
git status --short --ignored
git log --oneline --decorate -5
```

Check cluster:

```powershell
ssh uap@100.106.223.120 "sudo k3s kubectl get nodes -o wide"
ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system get deploy"
```

Run only static checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\static\secret-scan.ps1
powershell -ExecutionPolicy Bypass -File .\tests\static\validate-iac.ps1
```

Run smoke tests:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\run-all.ps1
```

## Key Files

- `STATUS.md`: current factual state.
- `infra/ansible/inventories/local.yml`: current local inventory, SSH over tailnet.
- `infra/tofu/environments/local-proxmox`: OpenTofu-compatible local Proxmox target.
- `tests/verify-local.ps1`: local validation gate.
- `runbooks/validation-matrix.md`: what to check and when.
- `runbooks/restore-drill.md`: disposable k3s restore drill.
- `runbooks/offsite-backups.md`: future S3/Proxmox backup plan.
- `clusters/prod/flux-system/gotk-components.yaml`: pinned Flux runtime.
- `clusters/prod/infra/sops-smoke.sops.yaml`: encrypted SOPS smoke fixture.

## Safe Next Tasks

Good next tasks that do not require redesign:

1. Install OpenTofu and Ansible on the operator machine or CI runner, then enable real CLI checks.
2. Run Ansible `--syntax-check` and inventory graph once Ansible is installed.
3. Import existing Proxmox VMs into OpenTofu state only after reviewing the plan carefully.
4. Configure remote Git URL and enable Flux Git sync from `gotk-sync.example.yaml`.
5. Configure S3-compatible offsite snapshot storage with SOPS-encrypted credentials.
6. Create a disposable VM and execute `runbooks/restore-drill.md`.
7. Add third independent k3s server, then run a real failover drill.

## Things That Need Owner Input

- Remote VPS provider and credentials.
- Remote Git repository URL.
- S3-compatible object storage endpoint and credentials.
- Claude/OpenRouter/API keys.
- Any destructive test: VM restore over an existing VM, node shutdown, k3s server reset, etc.

## Known Warnings

`tests/smoke/k3s-snapshot.ps1` may print warnings from `k3s etcd-snapshot list` about server-only flags in
`/etc/rancher/k3s/config.yaml`. This is currently expected and documented in `runbooks/k3s-snapshots.md`.

## Handoff Rule

When finishing a task, update files rather than relying on chat memory:

- Update `STATUS.md` for factual state changes.
- Add or update a runbook for operational procedures.
- Add tests or extend `runbooks/validation-matrix.md` for new validation expectations.
- Commit the work with a clear message.
