# Claude Code Handoff

This file is the current operational handoff for Claude Code. It complements `AGENTS.md`; it does not replace the
project decisions in `DECISIONS.md`.

## Read First

This mirrors the canonical order in `AGENTS.md`. `STATUS.md` is the source of truth for current facts; if this handoff
and `STATUS.md` disagree, `STATUS.md` wins.

1. `AGENTS.md` → `README.md` → `DECISIONS.md` → `STATUS.md` → `RISKS.md`
2. `docs/product-operating-contract.md` → `docs/infrastructure.md` → `docs/next-steps.md`
3. `docs/research/nousresearch-hermes-agent.md` + `docs/research/hermes-codex-subscription-brain.md` — why
   hermes-agent; always take the current brain/runtime from `STATUS.md`, not historical research wording
4. `runbooks/README.md` + `tools/README.md` — procedure and subsystem indexes
5. `runbooks/validation-matrix.md` + `runbooks/vibe-coding-acceptance.md` — required gates and end-to-end acceptance

`BUILD-PLAN.md`, `ARCHITECTURE.md` and the parked `hermes/` references remain useful historical/design context when a
task touches them, but they do not override the current order or live facts above.

If any instruction conflicts, follow `AGENTS.md` and `DECISIONS.md`, then ask the owner before changing direction.

## 2026-06-28 Bug-Hunt + Code-Review — RESOLVED

The 2026-06-28 Codex bug-hunt and independent code-review are actioned: see `STATUS.md` → "Post-A4 hardening
pass" for the merged-PR list. The original reports are kept for historical record (not required reading):
[BUG-HUNT-CODEX-2026-06-28.md](BUG-HUNT-CODEX-2026-06-28.md), [CODE-REVIEW-CODEX-2026-06-28.md](CODE-REVIEW-CODEX-2026-06-28.md),
[READONLY-INFRA-AUDIT-2026-06-28.md](READONLY-INFRA-AUDIT-2026-06-28.md). Historical pod-rolling PRs #35/#36 were
resolved; use `STATUS.md` rather than this handoff for their exact outcome.

## Current State

- **North star: vibe-coding** — the owner supplies ideas + infrastructure; the agent ships *verified* code. The owner
  does **NOT review code**, so the agent's own self-testing is the quality gate. (See `docs/next-steps.md`, `docs/infrastructure.md`.)
- **Accepted product contract (2026-07-14):** the owner is not an operator. Central external `hermes-agent` remains the
  foundation and sole target source of sessions/missions/events; Workspace and Telegram are synchronized views;
  build-1/Flow is the execution plane. Read `docs/product-operating-contract.md` and ADR-030 before agent-layer work.
- **Three layers, live (namespace `uap-system`):**
  - **Infra** — k3s 2-node (**NOT HA**: server `uap-home-1` + agent `uap-home-2` = single etcd member), Flux GitOps + SOPS, k3s→R2 DR.
  - **Model** — Central Hermes uses Codex `gpt-5.6-luna`; build-1 delivery follows ADR-031's automatic OpenAI-only
    Luna/Sol/Terra policy. `subfleet` + LiteLLM remain installed separate/legacy capacities, not automatic fallbacks.
  - **Agent** — external NousResearch hermes-agent is live; bespoke `hermes/hermes.py` is parked.
- **Active direction (2026-06-22/23 pivot):** adopt the **external NousResearch hermes-agent** as the vibe-coding harness.
  Brain = the **Codex/ChatGPT subscription** (`codex_app_server`, native function-calling). ADR-031 makes Luna/Sol/Terra
  the automatic coding/review routes; Claude, local inference and GPU are not fallbacks without a separate owner decision.
  **Do NOT point hermes-agent's brain at the
  subfleet endpoint — it is FC-less and every tool silently goes dark.** Rationale + citations in `docs/research/`.
- **GitOps coverage (verified):** the model+agent layer is now **fully Flux-reconciled** — `litellm.yaml`,
  `litellm-keys.sops.yaml`, `hermes.yaml`, `hermes-keys.sops.yaml`, and every hermes-agent manifest are referenced by
  `clusters/prod/infra/kustomization.yaml`. **B0 is DONE** (`docs/next-steps.md`).
- **✅ The quality gate IS enforced.** The repo is **public**, the ruleset `protect-master` is **active** (PR required +
  `static-checks` CI a **required/strict** check), so direct push to `master` is **BLOCKED**. Deploys are PR-gated
  (branch → PR → green `static-checks` → merge → Flux reconciles `master`). Human code review stays absent by design —
  the agent's self-test + CI is the gate. See `docs/next-steps.md` → Platform hardening.
- **A7 lifecycle and configured-profile acceptance are live (2026-07-17):** PRs #235/#236 are installed in Central
  Hermes and build-1, and the schema-v3 `openai-autonomy-v2` runtime passed the Telegram-bound non-toy acceptance
  canary through recovery, PR/CI/merge, post-verify and cleanup. See
  `docs/evidence/a7-lifecycle-rollout-2026-07-17.md` and
  `docs/evidence/a7-3-clean-telegram-canary-2026-07-17.md`. Generic repository intake and complete cross-channel
  chat/session history remain outside that proof.
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
| `pavels-mac-mini` | personal / agent-worker | — | `100.116.97.112` | Apple Silicon; SSH off; **always-on** |

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
- `runbooks/offsite-backups.md`: live k3s/R2 and Proxmox backup/restore procedures.
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

1. A6.0 is a pre-rollout snapshot in `docs/hermes-mission-state-map.md`; use `STATUS.md` for current live facts.
2. A6.1-A6.4 are complete through one controlled canary. The central mission runtime, fail-closed Workspace overlay
   and build-1 adapter are installed; `docs/evidence/a6-4-controlled-canary-2026-07-14.md` records the boundary.
3. Workspace and Telegram synchronize mission state and the owner question/answer resume path, but not complete
   cross-channel chat/session history. Telegram delivery is at-least-once and may duplicate after send-before-cursor
   crash. Central retains 100 recent unbound terminal missions and protects the bound mission plus active repair chains;
   completed native tasks are archived, native GC runs only while the board is idle, and private delivery state expires
   after 30 days.
4. A7.1/A7.2 and the configured-profile A7.3 acceptance canary are complete. Mission
   `a7-clean-ledger-list-20260717-a0fc5a` ran on the corrected runtime from the timer without a manual coordinator tick:
   runtime-attested Sol author, distinct exact-SHA read-only Terra review, hermes-flow-v2-pilot PR #5,
   Python/Linux/macOS/Windows CI, exact-head merge, fresh-main Rust post-verify and cleanup. The planned durable crash
   resumed without a duplicate author/candidate; Central and Workspace matched at terminal sequence 22 and the bound
   Telegram cursor reached 22. This proves the exact configured profile, not generic repository intake or complete
   cross-channel chat-session history. Evidence: `docs/evidence/a7-3-clean-telegram-canary-2026-07-17.md` and the earlier
   recovery history in `docs/evidence/a7-3-activation-delivery-canary-2026-07-15.md`.
   A separate repo-owned schema-v4 `build1-flow-pilot-registered-v4` consumer is now installed with a standing timer
   and explicit `delivery_mode: none`; Central requires `delivery: not_applicable` before completing that target;
   its exact Workspace/Telegram intake registry and timer are enabled. Ordinary Workspace delivery passed live.
   A later ordinary Telegram goal survived a controlled exact pre-turn capacity error and completed Sol/Terra
   author/review, target PR #8, multi-platform CI, merge, post-verify, cleanup, terminal sequence 27 and a verified
   canonical completion bundle. The campaign preserved its durable mission while PRs #271–#273 corrected reviewer
   recovery and Central historical-worker completion, so it is adversarial recovery evidence rather than a clean
   frozen-runtime run. Evidence: `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
   PR #275 introduces and deploys completion-bundle schema v2 for future registered ordinary missions. It
   binds the server-owned Workspace/Telegram platform and hashed source key/message to deterministic
   `mission-intake-*`, keeps existing v1 bundles valid and stores no raw channel/message identity. Central/build-1
   exact rollout and component verification passed; one new live artifact remains the evidence gate. Channel cursors
   and signing remain later fields. Evidence:
   `docs/evidence/completion-input-lineage-rollout-2026-07-18.md`.
   The live terminal message exposed the next UX gap: it only rendered `Delivery completed, merged, and verified` even
   though PR/check/merge/change facts were durable. The next small implementation should build a bounded redacted
   owner result from canonical evidence and render it identically in Workspace/Telegram; no extra model call.
   A bound `waiting_owner` Telegram mission now accepts a normal message as its idempotent source-linked answer;
   PR #264 is deployed and passed an in-pod component check. The equivalent exact-Workspace-session path is deployed
   through PR #270 and passed its in-pod component check. A real cross-channel owner question/resume path remains the
   next controlled live canary. See
   `docs/evidence/ordinary-workspace-autonomous-delivery-2026-07-18.md`.
   The answer rollout records are `docs/evidence/ordinary-bound-telegram-answer-rollout-2026-07-18.md` and
   `docs/evidence/ordinary-workspace-owner-answer-rollout-2026-07-18.md`.
5. ADR-031 replaces per-attempt model approvals. Luna/Sol/Terra selection, reasoning effort, retries, normal tests/VMs,
   PR/CI/merge and repo-defined deploy/post-verify are standing-approved platform duties; ordinary spend is not a
   dangerous operation. Claude, local inference/GPU, a new provider/credential, destructive tests against
   non-disposable state and work outside the mission remain gated. `openai-autonomy-v2` and the schema-v3 profile ran
   live. The same PR number
   and pushed head are durable identity;
   final failure validates the durable PR number/head/base under a live claim and preserves an open exact PR/branch as
   bounded evidence because GitHub has no conditional close; an already closed PR's unchanged branch is lease-deleted.
   CI persistence is bounded, repair pushes use an exact prior-head lease,
   initial push/PR-create and repair-push response loss converge, and compatible v1 in-progress routes/PR identities
   resume.
   Reviewer execution is deployed through a parent-bound transient user-systemd unit with strict
   read-only filesystem/home, hidden unrelated `/proc`, private tmp, explicit model/Codex runtime write paths and
   masked common credentials/user-runtime IPC. PR #266 and installed exact-wrapper probe are green. The first real
   attempt found an `After=`/Type=oneshot parent deadlock; PR #271 keeps `BindsTo=` without that ordering edge. Its
   restart preserved the same candidate but exposed a permanent reviewer `reconciling` checkpoint. PR #272 is merged
   and installed with the guarded reviewer-only convergence transition; the same mission then completed a real
   runtime-attested Terra review of the exact candidate inside the corrected transient unit. Author ambiguity remains
   fail-closed. Evidence: `docs/evidence/reviewer-os-isolation-rollout-2026-07-18.md`.
6. Run `tests/ops/check-ops-node.ps1 -Require` and `tests/ops/check-ops-deploy-path.ps1 -Require` after any ops-node changes.
7. Import existing Proxmox VMs into OpenTofu state only after reviewing the plan carefully.
8. Cross-review update: GitHub branch protection/least privilege and the 2026-07-12 cross-node canary Secret
   restore are done. Owner accepted the current R2 credential scope/lifecycle as-is; do not rotate or alter it
   without a new decision. Off-homelab age-key escrow remains open.
9. (DONE 2026-06-19) S3 offsite snapshots configured with a SOPS-encrypted Secret; see STATUS.md -> Offsite Backups.
10. (DONE 2026-07-12) Cross-node restore and exact Secret-decrypt verification passed; see
    `runbooks/restore-drill.md`.

## Things That Need Owner Input

No owner input is currently required for the accepted A7 fixed-profile path. Ask only when scope actually needs:

- a new provider, credential or external authority not already configured;
- a destructive test against non-disposable state or an irreversible action, such as overwriting a live VM restore
  target, node shutdown or production k3s reset; repo-defined hermetic/disposable drills need no per-run approval;
- a change to a closed topology/security/architecture decision;
- the separately deferred VPS/HA or off-homelab age-key escrow decisions.

Git, S3/R2, non-RU egress and the current OpenAI route are already configured. Claude/local inference/GPU are not
automatic fallbacks and require a separate owner decision.

## Known Warnings

`tests/smoke/k3s-snapshot.ps1` may print warnings from `k3s etcd-snapshot list` about server-only flags in
`/etc/rancher/k3s/config.yaml`. This is currently expected and documented in `runbooks/k3s-snapshots.md`.

## Handoff Rule

When finishing a task, update files rather than relying on chat memory:

- Update `STATUS.md` for factual state changes.
- Add or update a runbook for operational procedures.
- Add tests or extend `runbooks/validation-matrix.md` for new validation expectations.
- Commit the work with a clear message.
