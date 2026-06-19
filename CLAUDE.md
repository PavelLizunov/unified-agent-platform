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
- For exact history, run `git log --oneline --decorate -5`; this file should not be treated as the source of truth for
  commit hashes after another agent has committed.
- Plan fact-checked 2026-06-18 (see `STATUS.md` -> Plan Fact-Check): MinIO -> Garage (ADR-019), Restate -> S3 not
  Postgres (ADR-020), RU LLM egress (ADR-018), k3s-over-Tailscale flannel-iface (ADR-021).
- Live since 2026-06-19 (see STATUS.md): Flux GitOps sync; VLESS LLM egress (sing-box on `uap-ops-1`); k3s
  etcd-s3 -> Cloudflare R2 offsite backups + a restore drill; Vaultwarden on `uap-ops-1`. CAVEAT: egress + Vaultwarden
  run ad-hoc on `uap-ops-1` (a 2 GB non-cluster VM) — blast-radius/SPOF + secrets-at-rest issues are flagged in
  `REVIEW-CODEX.md` (2026-06-19 cross-review). Address those before Stage 2.

## Live Nodes

Use tailnet IPs for SSH and smoke tests.

| Node | Role | LAN IP | Tailnet IP | Notes |
|---|---|---|---|---|
| `uap-home-1` | k3s server, embedded etcd | `192.168.0.201` | `100.106.223.120` | control-plane/etcd |
| `uap-home-2` | k3s agent | `192.168.0.202` | `100.94.228.67` | worker only |
| `uap-ops-1` | operator VM | `192.168.0.203` | `100.82.241.121` | not a k3s node; deploy path verified from ops |

Do not rely on LAN SSH as the default path. LAN SSH has shown intermittent resets; tailnet SSH is the stable path.
Exception: Windows-to-`uap-ops-1` tailnet SSH intermittently timed out after enrollment, so workstation-to-ops checks
currently default to LAN until that is resolved. `uap-ops-1` itself can SSH to `uap-home-1` and `uap-home-2` over
tailnet and can run `kubectl` against the cluster.

## Git Remote Readiness

- GitHub `origin` IS configured on `uap-ops-1` (private repo, read-only SSH deploy key for Flux; `gh` authed there).
  Flux Git sync is ACTIVE. STATUS.md is the source of truth for deployed state.
- The **local Windows workstation** has no `origin` and no S3 env, so `tests/verify-local.ps1 -IncludeReadiness`
  still reports `git-remote-missing` / `s3-env-missing` *from the workstation* — this is EXPECTED: origin + S3 creds
  live on `uap-ops-1` and in SOPS, not on Windows.
- Windows SSH key fingerprint `SHA256:YLFbDMRbeUldpLQW8dmMihAQbRgCVBhmQGTW98rgm9c` (comment `windows`); the
  workstation does not run sshd (TCP 22 closed), so node->workstation SSH is unavailable.

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
- optional `-IncludeOps` also runs `tests/ops/check-ops-deploy-path.ps1`
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
ssh uap@192.168.0.203 "kubectl get nodes -o wide"
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
- `runbooks/flux-remote-git.md`: how to enable Flux Git sync after a real remote exists.
- `runbooks/cloudflare-r2-k3s-snapshots.md`: Cloudflare R2 setup flow for k3s snapshots.
- `runbooks/llm-egress-vless.md`: cloud LLM egress from RU via non-RU node or VLESS+REALITY (ADR-018).
- `runbooks/garage-object-store.md`: Garage S3 object store, replaces archived MinIO (ADR-019).
- `runbooks/uap-ops-node.md`: create and bootstrap the optional operator VM.
- `infra/ops/bootstrap-ops-node.sh`: installs deploy tools on `uap-ops-1`.
- `infra/ops/configure-github-flux.sh`: after `gh auth login` on `uap-ops-1`, creates/reuses the GitHub repo,
  pushes `master`, creates a read-only Flux deploy key, and prepares the Flux sync manifest.
- `tests/ops/check-ops-node.ps1`: verifies deploy tools on `uap-ops-1`.
- `tests/ops/check-ops-deploy-path.ps1`: verifies `uap-ops-1` can reach the cluster with kubectl and SSH.
- `clusters/prod/flux-system/gotk-components.yaml`: pinned Flux runtime.
- `clusters/prod/infra/sops-smoke.sops.yaml`: encrypted SOPS smoke fixture.

## Safe Next Tasks

Good next tasks that do not require redesign:

1. Run `tests/ops/check-ops-node.ps1 -Require` and `tests/ops/check-ops-deploy-path.ps1 -Require` after any ops-node changes.
2. Import existing Proxmox VMs into OpenTofu state only after reviewing the plan carefully.
3. Work the 2026-06-19 cross-review (`REVIEW-CODEX.md`): reduce `uap-ops-1` blast radius (rotate R2 token to a
   bucket-scoped key, GitHub branch protection + least-privilege token, separate backup creds from interactive
   rclone), prove cross-node Secret restore with a canary, set explicit S3 retention.
4. (DONE 2026-06-19) S3 offsite snapshots configured with a SOPS-encrypted Secret; see STATUS.md -> Offsite Backups.
5. (DONE 2026-06-19) Restore drill executed; secret-decrypt verification still pending — see `runbooks/restore-drill.md`.
6. Add third independent k3s server, then run a real failover drill.

## Things That Need Owner Input

- Remote VPS provider and credentials.
- Remote Git repository URL.
- S3-compatible object storage endpoint and credentials.
- Non-RU VLESS+REALITY egress endpoint (VPS abroad) for cloud LLM access from Russia (ADR-018).
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
