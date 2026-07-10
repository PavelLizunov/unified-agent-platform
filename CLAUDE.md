# Claude Code Handoff

This file is the current operational handoff for Claude Code. It complements `AGENTS.md`; it does not replace the
project decisions in `DECISIONS.md`.

## Read First

This mirrors the **canonical read-order in `AGENTS.md` → TL;DR** (both files list the same sequence and the
same two orientation indexes — `runbooks/README.md` and `tools/README.md`). `STATUS.md` is the source of truth
for current facts; if this handoff and `STATUS.md` disagree, `STATUS.md` wins.

1. `AGENTS.md` (its TL;DR has the layer-status table + this exact read-order)
2. `README.md`
3. `DECISIONS.md`
4. `BUILD-PLAN.md`
5. `STATUS.md`
6. `runbooks/validation-matrix.md`

**Model/agent layer + the 2026-06 pivot — read these before touching anything model/agent/coding:**

7. `docs/infrastructure.md` — consolidated fleet + what-runs-where + target architecture
8. `docs/next-steps.md` — the hermes-agent pilot plan + the still-open foundation work
9. `docs/research/nousresearch-hermes-agent.md` + `docs/research/hermes-codex-subscription-brain.md` — why hermes-agent; the original "brain = Codex" is now the **local-models router** (`qwen-35b`, fallback `ornith-9b`), cloud tier OFF — see `STATUS.md`
10. `hermes/README.md` + `hermes/docs/claude-code-autonomous-reference.md` — the parked bespoke agent + the Claude Code headless reference

**Top-down orientation indexes (read to find the right procedure/tool fast):**

11. `runbooks/README.md` — table of every runbook (purpose + when-to-use trigger)
12. `tools/README.md` — the `tools/` subsystems (purpose | entrypoint | owning runbook | self-test)

If any instruction conflicts, follow `AGENTS.md` and `DECISIONS.md`, then ask the owner before changing direction.

## 2026-06-28 Bug-Hunt + Code-Review — RESOLVED

The 2026-06-28 Codex bug-hunt and independent code-review are actioned: see `STATUS.md` → "Post-A4 hardening
pass" for the merged-PR list. The original reports are kept for historical record (not required reading):
[BUG-HUNT-CODEX-2026-06-28.md](BUG-HUNT-CODEX-2026-06-28.md), [CODE-REVIEW-CODEX-2026-06-28.md](CODE-REVIEW-CODEX-2026-06-28.md),
[READONLY-INFRA-AUDIT-2026-06-28.md](READONLY-INFRA-AUDIT-2026-06-28.md). Two pod-rolling PRs (#35, #36) remain
**owner-gated** — do not merge them yourself; see `STATUS.md`.

## Current State

- **North star: vibe-coding** — the owner supplies ideas + infrastructure; the agent ships *verified* code. The owner
  does **NOT review code**, so the agent's own self-testing is the quality gate. (See `docs/next-steps.md`, `docs/infrastructure.md`.)
- **Three layers, live (namespace `uap-system`):**
  - **Infra** — k3s 2-node (**NOT HA**: server `uap-home-1` + agent `uap-home-2` = single etcd member), Flux GitOps + SOPS, k3s→R2 DR.
  - **Model** — `subfleet` (the Claude subscription as an OpenAI **chat** API; drops `tool_calls`) + **LiteLLM** v1.89.0.
    subfleet is **retained for the owner's OTHER projects** (a Telegram bot + web sessions); redundant for in-repo coding.
  - **Agent** — bespoke `hermes/hermes.py` ("Hermes-legacy"; prompt-based ReAct/ReWOO; NodePort `:30890`). **PARKED.**
- **Active direction (2026-06-22/23 pivot):** adopt the **external NousResearch hermes-agent** as the vibe-coding harness.
  Brain = a **Codex/ChatGPT subscription** (`codex_app_server`, native function-calling) OR a **local FC model** on the
  RTX 5060 Ti; coding = `claude -p` (Claude Max) + `codex exec` as skills. **Do NOT point hermes-agent's brain at the
  subfleet endpoint — it is FC-less and every tool silently goes dark.** Rationale + citations in `docs/research/`.
- **GitOps coverage (verified):** the model+agent layer is now **fully Flux-reconciled** — `litellm.yaml`,
  `litellm-keys.sops.yaml`, `hermes.yaml`, `hermes-keys.sops.yaml`, and every hermes-agent manifest are referenced by
  `clusters/prod/infra/kustomization.yaml`. **B0 is DONE** (`docs/next-steps.md`).
- **✅ The quality gate IS enforced.** The repo is **public**, the ruleset `protect-master` is **active** (PR required +
  `static-checks` CI a **required/strict** check), so direct push to `master` is **BLOCKED**. Deploys are PR-gated
  (branch → PR → green `static-checks` → merge → Flux reconciles `master`). Human code review stays absent by design —
  the agent's self-test + CI is the gate. See `docs/next-steps.md` → Platform hardening.
- Git branch `master`. For exact history run `git log --oneline -8` (this file is not the source of truth for hashes).
  Plan fact-check (2026-06-18, `STATUS.md`): Garage (ADR-019), Restate→S3 (ADR-020), RU egress (ADR-018),
  k3s-over-Tailscale (ADR-021). The ad-hoc egress + Vaultwarden on `uap-ops-1` (2 GB non-cluster VM) remain a
  blast-radius/SPOF concern (`REVIEW-CODEX.md`).

## Live Nodes

Use tailnet IPs for SSH and smoke tests.

| Node | Role | LAN IP | Tailnet IP | Notes |
|---|---|---|---|---|
| `uap-home-1` | k3s server, embedded etcd | `192.168.0.201` | `100.106.223.120` | control-plane/etcd |
| `uap-home-2` | k3s agent | `192.168.0.202` | `100.94.228.67` | worker only |
| `uap-ops-1` | operator VM | `192.168.0.203` | `100.82.241.121` | not a k3s node; deploy path verified from ops |
| `desktop-m922ij2` | workstation / **GPU host** | — | `100.114.172.40` | Win 11, 32c/32GB, **RTX 5060 Ti 16GB**; **NOT always-on**; future local-FC-model host + agent-worker |
| `pavels-mac-mini` | personal / agent-worker | — | `100.116.97.112` | Apple Silicon; SSH off; **NOT always-on** |

Full fleet + roles: `docs/infrastructure.md`. The only GPU is on the **not-always-on** Windows desktop, so a
local-model brain on the RTX is only available when it is on (hence Codex-sub is the durable brain).

Do not rely on LAN SSH as the default path. LAN SSH has shown intermittent resets; tailnet SSH is the stable path.
Exception: Windows-to-`uap-ops-1` tailnet SSH intermittently timed out after enrollment, so workstation-to-ops checks
currently default to LAN until that is resolved. `uap-ops-1` itself can SSH to `uap-home-1` and `uap-home-2` over
tailnet and can run `kubectl` against the cluster.

## Git Remote Readiness

- GitHub `origin` on `uap-ops-1` is SSH; pushes use a repo-scoped read-WRITE deploy key (`uap-ops-1 push`), Flux
  pulls via a separate read-ONLY deploy key. `gh` is **authenticated** on `uap-ops-1` (device-flow, account
  `PavelLizunov`, scopes `repo,read:org,gist,workflow`) for gh-api ops (rulesets, CI inspection). Commit identity on
  ops-1 is `UAP Agent <slovnmi@gmail.com>`. Flux Git sync is ACTIVE; STATUS.md is the source of truth.
- The **local Windows workstation** now has a **read-only `origin`** (the public GitHub URL; added 2026-06-23 after
  the repo went public) so it can `git fetch`/sync — but **pushes still go via `uap-ops-1`** (the write deploy key
  lives there; Windows has no push creds). `-IncludeReadiness` may still report `s3-env-missing` *from the
  workstation* (S3 creds live in SOPS / on ops-1) — EXPECTED. **Deploys are PR-based** (direct push to master is
  blocked by the ruleset — see ADR-026 + the `uap-commit-push` skill).
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
- `runbooks/hermes-access.md`: how to talk to Hermes from any device (REPL `hermes` per-OS, dashboard `/login`, Telegram).

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
