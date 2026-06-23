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
| Git remote | Read remote branch | `tests/git/check-git-remote.ps1 -GitUrl <url>` | Before enabling Flux sync | `git-remote-ok` |
| S3 env | Required offsite variables exist | `tests/s3/check-s3-env.ps1` | Before creating S3 Secret | `s3-env-ok` |
| Ops node | Deploy tools installed | `tests/ops/check-ops-node.ps1 -Require` | After creating `uap-ops-1` | `ops-node-ok` |
| Ops node | Cluster deploy path | `tests/ops/check-ops-deploy-path.ps1 -Require` | After copying kubeconfig to `uap-ops-1` | `ops-deploy-path-ok` |
| Ansible | Syntax and inventory | included in `validate-iac.ps1` when Ansible is installed | Every Ansible change | syntax check passes |
| Ansible | Idempotency | `tests/ansible/idempotency-check.ps1 -ConfirmRun` | Before relying on playbooks for repeatable bootstrap | second run reports `changed=0` |
| SSH baseline | Debian, sudo, SSH hardening | `tests/smoke/ssh-baseline.ps1` | After VM/OS changes | Debian 12+, sudo OK, password/root SSH disabled |
| k3s baseline | API, system pods, smoke deployment | `tests/smoke/k3s-local.ps1` | After k3s changes | nodes Ready; smoke deployment rolls out |
| k3s agent | Scheduling on agent | `tests/smoke/k3s-agent.ps1` | After node scheduling changes | targeted pod runs on the agent |
| Flux | Controllers and SOPS secret | `tests/smoke/flux-local.ps1` | After GitOps changes | four Flux deployments Available |
| **Agent logic** | hermes unit tests | `python -m unittest discover -s hermes/tests -p 'test_*.py'` | Every `hermes/` change | 41 tests pass — **CI-enforced** (`static-checks`) |
| **GitOps build** | kustomize builds clean | `kustomize build clusters/prod` | Every `clusters/**` change | exit 0 — **CI-enforced** |
| **Secrets (CI)** | gitleaks + `*.sops.yaml` encrypted | CI `static-checks` (gitleaks, `.gitleaks.toml`) | Every push/PR | no leaks; committed SOPS files contain `ENC[…]` — **CI-enforced** |
| Backup existence | Snapshot list | `tests/smoke/k3s-snapshot.ps1` | Daily/manual | expected snapshot appears |
| Offsite backup | etcd snapshot in R2 | `rclone lsf r2:uap-k3s-snapshots/prod/` (on uap-ops-1) | weekly | recent snapshot object present |
| ops-1 services backup | Vaultwarden + egress secrets archive in R2 | `rclone lsf r2:uap-k3s-snapshots/ops-backup/` (on uap-ops-1) | weekly | recent `ops-*.tar.gz.age` present; see `runbooks/uap-ops-services-backup.md` |
| SOPS | Decrypt fixture | `tests/smoke/sops-decrypt.ps1` | After SOPS key changes | `sops-decrypt-ok` |
| Disaster recovery | Disposable restore (+ canary Secret decrypt) | `runbooks/restore-drill.md` | Before claiming recovery readiness; then quarterly | restored cluster answers `kubectl` AND a known canary Secret decrypts |
| HA failover | Kill one server | future Stage 1 drill | After third server joins | API and workloads survive one server loss |

## Notes

- Smoke tests default to tailnet IPs. Override with `UAP_*` environment variables for another cluster.
- Warnings from `k3s etcd-snapshot list` about server-only flags are expected in the current local config and are
  documented in `runbooks/k3s-snapshots.md`.
- A green local gate does not mean HA is ready. HA requires a third independent k3s server and a failover drill.
- **CI is the enforced gate (2026-06-23):** the rows marked *CI-enforced* run in GitHub Actions
  (`.github/workflows/ci.yml`, job `static-checks`) on every push/PR; the `protect-master` ruleset **requires** that
  check green before a PR can merge to `master` (deploys are PR-based — ADR-026). The PowerShell smoke tests need the
  tailnet + age key, so they stay a workstation/ops-1 job, not CI.
