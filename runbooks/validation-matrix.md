# Validation Matrix

This matrix defines the checks expected before an agent marks bootstrap or stability work as done.

## Local Gate

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1
```

Pass criteria:

- No whitespace errors from `git diff --check`.
- Secret scan passes.
- Static IaC validation passes.
- Current smoke tests pass against the tailnet nodes.

## Matrix

| Layer | Check | Command | When | Pass criteria |
|---|---|---|---|---|
| Repository hygiene | Whitespace and patch sanity | `git diff --check` | Every change | exit code 0 |
| Secrets | Plaintext secret scan | `tests/static/secret-scan.ps1` | Every change | no private keys, kubeconfig client data, Proxmox tokens, Tailscale auth keys |
| IaC structure | YAML, inventory, OpenTofu policy checks | `tests/static/validate-iac.ps1` | Every change | `iac-static-ok` |
| OpenTofu | Format and validate | `tests/tofu/validate-plan.ps1` | When OpenTofu/Terraform is installed | `fmt`, `init -backend=false`, `validate` pass |
| OpenTofu | Real plan | `tests/tofu/validate-plan.ps1 -RunPlan` | Before applying infra changes | reviewed plan; no surprise destroy/recreate |
| Ansible | Syntax and inventory | included in `validate-iac.ps1` when Ansible is installed | Every Ansible change | syntax check passes |
| Ansible | Idempotency | `tests/ansible/idempotency-check.ps1 -ConfirmRun` | Before relying on playbooks for repeatable bootstrap | second run reports `changed=0` |
| SSH baseline | Debian, sudo, SSH hardening | `tests/smoke/ssh-baseline.ps1` | After VM/OS changes | Debian 12+, sudo OK, password/root SSH disabled |
| k3s baseline | API, system pods, smoke deployment | `tests/smoke/k3s-local.ps1` | After k3s changes | nodes Ready; smoke deployment rolls out |
| k3s agent | Scheduling on agent | `tests/smoke/k3s-agent.ps1` | After node scheduling changes | targeted pod runs on the agent |
| Flux | Controllers and SOPS secret | `tests/smoke/flux-local.ps1` | After GitOps changes | four Flux deployments Available |
| Backup existence | Snapshot list | `tests/smoke/k3s-snapshot.ps1` | Daily/manual | expected snapshot appears |
| SOPS | Decrypt fixture | `tests/smoke/sops-decrypt.ps1` | After SOPS key changes | `sops-decrypt-ok` |
| Disaster recovery | Disposable restore | `runbooks/restore-drill.md` | Before claiming recovery readiness; then periodically | restored disposable cluster answers `kubectl` |
| HA failover | Kill one server | future Stage 1 drill | After third server joins | API and workloads survive one server loss |

## Notes

- Smoke tests default to tailnet IPs. Override with `UAP_*` environment variables for another cluster.
- Warnings from `k3s etcd-snapshot list` about server-only flags are expected in the current local config and are
  documented in `runbooks/k3s-snapshots.md`.
- A green local gate does not mean HA is ready. HA requires a third independent k3s server and a failover drill.
