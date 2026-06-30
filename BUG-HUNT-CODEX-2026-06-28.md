# Codex Bug-Hunt Handoff for Claude Code

Date: 2026-06-28

This is a read-only bug-hunt result for the post-A4 hermes-agent / coding-worker implementation. It is written for Claude Code as an actionable handoff. Do not treat this as an ADR; fixes that change architecture still need owner approval.

## CLAUDE CODE: read this first

- The owner asked for a bug-hunt, not implementation. The next worker may implement fixes from this file.
- Start by syncing the local checkout with remote before editing: during this audit, local `master` was at `88be55a`, while GitHub `master` had already advanced to `a469aff`.
- The local worktree had `STATUS.md` dirty, but the diff matched the already-published remote commit `a469aff` (`docs(status): A4 north-star demo passed...`). Do not overwrite that blindly.
- Avoid destructive/live cluster mutations unless the owner explicitly approves them. Full smoke tests create/delete Kubernetes test resources.

## What Passed

- `powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1 -SkipSmoke` -> passed.
- `python tests\static\test_validate_iac_orphans.py` -> 4/4 passed.
- `python -m unittest discover -s hermes\tests -p 'test_*.py'` -> 41 tests passed.
- `git diff --check` -> passed.
- GitHub ruleset check via API: `protect-master` is active, public repo, PR required, `static-checks` required with strict status policy.
- Live read-only cluster snapshot:
  - `hermes-agent` 1/1 Running, 0 restarts.
  - `singbox-egress-ha` 1/1 Running, 0 restarts.
  - `hermes-agent-backup` last successful at `2026-06-27T03:01:54Z`.
  - `hermes-agent-data` PV currently has reclaim policy `Retain`.

Not run:

- Full smoke (`tests\smoke\run-all.ps1`) because it creates/deletes Kubernetes resources.
- Local `kustomize build clusters/prod` because this Windows checkout does not have `kustomize` or `kubectl`; CI `static-checks` on remote was green.

## Findings

### P1 - Source-of-truth docs are stale and contradictory

Files still saying the old world:

- `STATUS.md` says the quality gate is not enforced and LiteLLM/Hermes are not fully GitOps-owned.
- `CLAUDE.md` says the same and still points B0 as open for LiteLLM/Hermes GitOps coverage.
- `docs/next-steps.md` still says the quality gate is unenforced and A4 is pending.
- `docs/infrastructure.md` still says LiteLLM/Hermes are not reconciled.

Reality observed by this audit:

- GitHub repo is public.
- Ruleset `protect-master` is active.
- Required check `static-checks` is enforced.
- `clusters/prod/infra/kustomization.yaml` references `litellm.yaml`, `hermes.yaml`, their SOPS secrets, `hermes-agent`, `singbox-egress-ha`, and backup manifests.
- A4/A5 are documented as done in newer `STATUS.md` content / remote commit.

Why this matters:

- In this project files are the source of truth for Codex and Claude Code. Stale handoff text can cause the next agent to redo B0, bypass the PR flow, or treat the gate as optional.

Acceptance for fix:

- Update `STATUS.md`, `CLAUDE.md`, `docs/next-steps.md`, and `docs/infrastructure.md` so they agree with ADR-026 and current live GitOps.
- Keep unresolved risks explicit: HA still not ready; human review still absent; live-smoke/destructive drills still owner-gated.

### P1 - `configure-github-flux.sh` conflicts with ADR-026

File:

- `infra/ops/configure-github-flux.sh`

Problems:

- Defaults `UAP_GITHUB_VISIBILITY` to `private`, but ADR-026 depends on the repo being public so free rulesets can enforce `static-checks`.
- Pushes directly to `${branch}` with `git push -u origin "${branch}"`, which conflicts with the current PR-only master ruleset.
- Later optional `UAP_COMMIT_AND_PUSH=1` also commits/pushes directly.

Why this matters:

- If reused after ADR-026, the script either fails against protected `master` or recreates the old unsafe path in a fresh repo.

Acceptance for fix:

- Default to public or require an explicit owner choice with a warning that private free repos cannot enforce the master ruleset.
- Do not direct-push protected `master`; either create/push a setup branch and tell the operator to open a PR, or make direct push an explicit break-glass path with owner confirmation.
- Document that Flux deploy is PR-gated by `protect-master`.

### P2 - hermes-agent startup is not reproducible enough

Files:

- `clusters/prod/infra/hermes-agent.yaml`
- `clusters/prod/infra/hermes-agent-backup.yaml`

Problems:

- `nousresearch/hermes-agent:latest` is used for gateway/init/backup dump.
- `rclone/rclone:latest` is used for backup shipping.
- The initContainer installs coding CLIs with unpinned `npm i -g @openai/codex` and `npm i -g @anthropic-ai/claude-code`.

Why this matters:

- A fresh PVC, restore, node reschedule, or upstream package/image change can silently change the runtime or fail boot.
- This undermines the "self-test is the gate" model because the deployed worker may no longer match the tested worker.

Acceptance for fix:

- Pin hermes-agent image by version or digest.
- Pin rclone image by version or digest.
- Pin codex and claude CLI package versions, or build a small controlled image containing the tested versions.
- Add a verification command that prints `hermes`, `codex`, `claude`, and image digests in the runbook or CI/live-smoke.

### P2 - Coding worker pod boundary is weak

Files:

- `clusters/prod/infra/hermes-agent.yaml`
- `clusters/prod/infra/hermes-agent-config.yaml`

Observed:

- Codex runs with `sandbox_mode = "danger-full-access"` and `approval_policy = "never"`.
- Claude OAuth token is injected into the same pod.
- The live pod mounts the default Kubernetes service account token.
- Live `kubectl auth can-i` for the default service account returned `no` for pods/secrets/nodes, so immediate cluster-admin blast was not observed.
- The container status shows uid 0 for the running image.

Why this matters:

- A coding worker with shell access shares a pod with long-lived auth material and local state. The `.claude/settings.json` deny list is useful but the file itself correctly notes that Bash is unconstrained.

Acceptance for fix:

- Set `automountServiceAccountToken: false` for hermes-agent, singbox-egress-ha, and backup jobs unless a token is strictly required.
- Add a dedicated ServiceAccount with no permissions where a ServiceAccount is needed.
- Add pod/container securityContext where compatible: `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`, `seccompProfile: RuntimeDefault`, and non-root if the image can support it.
- Consider separating the coding worker execution boundary from the gateway/auth PVC, or document why the current pod boundary is accepted for the pilot.

### P2 - Missing probes for new critical pods

Files:

- `clusters/prod/infra/hermes-agent.yaml`
- `clusters/prod/infra/singbox-egress-ha.yaml`

Problems:

- No readiness/liveness/startup probes for `hermes-agent`.
- No readiness/liveness/startup probes for `singbox-egress-ha`.

Why this matters:

- Kubernetes reports the pod Ready if the process is running, not if Telegram, Codex brain, dashboard, or proxy routing works.

Acceptance for fix:

- Add minimal probes that are safe and local.
- For `singbox-egress-ha`, at least verify the proxy port is listening; ideally include a synthetic proxied request in a separate smoke check.
- For `hermes-agent`, use dashboard/health endpoint if available, or add a documented live-smoke command for brain + Telegram path.

### P3 - `validate_iac.py` orphan check has a path false-negative/false-positive class

File:

- `tests/static/validate_iac.py`

Problem:

- `_find_kustomization_orphans` compares kustomization resources by `Path(r).name`, not normalized same-directory paths.
- Reproduced in a temp tree: a resource `../shared/foo.yaml` can incorrectly hide local `foo.yaml`, while the actual referenced target can be flagged as orphan from its own directory.

Acceptance for fix:

- Normalize each `resources:` entry relative to the kustomization directory.
- Compare repo-root-relative resolved paths, not basenames.
- Add tests for:
  - sibling file referenced by name;
  - `../shared/foo.yaml`;
  - duplicate basenames in different directories;
  - intentionally allowlisted review-only manifests.

### P3 - PV `Retain` is live state, not declarative state

Files:

- `clusters/prod/infra/hermes-agent.yaml`
- `runbooks/hermes-agent-dr.md`

Observed:

- Live PV for `hermes-agent-data` is currently `Retain`.
- The runbook says this is a one-time manual patch on a dynamically provisioned PV.

Why this matters:

- A future re-created PVC will not automatically inherit `Retain`. The next restore/migration can regress to `Delete` unless the operator remembers the runbook step.

Acceptance for fix:

- Either add a tiny validation check that fails if the live `hermes-agent-data` PV is not `Retain`, or move to a storage class / static PV pattern that declares the reclaim policy.
- Keep this out of regular CI if it needs cluster access; put it in ops/live-smoke.

## Suggested Goal

Goal:

Post-A4 hardening bugfix pass: make the repository, bootstrap, and hermes-agent/egress runtime manifests consistent, reproducible, and safer without changing closed ADR decisions.

Acceptance criteria:

- Docs agree on A4/A5, GitOps coverage, and ADR-026 enforcement.
- Bootstrap scripts no longer imply private/no-ruleset/direct-master deploy as the default path.
- hermes-agent, backup, and egress images/tools are pinned or explicitly accepted with a documented risk.
- Coding worker pod has minimal ServiceAccount exposure and basic pod hardening where compatible.
- New critical pods have probes or explicit live-smoke checks.
- `validate_iac.py` path-based orphan bug is fixed with tests.
- `tests/verify-local.ps1 -SkipSmoke`, hermes unit tests, orphan tests, `kustomize build clusters/prod`, and GitHub `static-checks` are green.
- Any live smoke or destructive/restore drill is owner-approved before execution.

## Delegation Plan

Split into small PRs:

1. `docs(source-of-truth)`: update `STATUS.md`, `CLAUDE.md`, `docs/next-steps.md`, `docs/infrastructure.md`.
2. `fix(ops-bootstrap)`: make GitHub/Flux bootstrap ADR-026-aware.
3. `fix(iac)`: repair `validate_iac.py` orphan path logic and tests.
4. `chore(agent-runtime)`: pin images/CLI versions and add version verification.
5. `fix(agent-security)`: ServiceAccount and pod security hardening.
6. `fix(agent-health)`: probes and live-smoke additions.

Recommended order:

1. Docs and `validate_iac.py` first.
2. Bootstrap script second.
3. Runtime pinning and security after confirming exact image/CLI versions from the live pod.

## Readonly Wave Breakdown for Claude Code

Context:

- This section was added after a read-only follow-up pass.
- No Kubernetes apply/delete/rollout, restore drill, failover drill, or code-manifest edit was performed during the follow-up.
- Read-only checks included git status/log, local file inspection, GitHub ruleset/check status via `gh api`, `kubectl get/describe/logs`, safe `kubectl exec` inspections, and manifest parsing.
- Do not repeat secret values from logs or exec output. Treat any secret-like value observed in tool output as sensitive.

### Wave 1 - Source of truth drift

Status: red.

Observed:

- `STATUS.md`, `CLAUDE.md`, `docs/next-steps.md`, and `docs/infrastructure.md` still contain stale statements about GitOps coverage and quality-gate enforcement.
- GitHub reality is different: `protect-master` is active, PR is required, `static-checks` is required and green, and Hermes/LiteLLM are already represented in GitOps manifests.
- `runbooks/validation-matrix.md` is closer to current truth and already says the gate is CI-enforced.

Acceptance criteria:

- Docs agree on the current state of A4/A5, ADR-026, ruleset enforcement, and GitOps coverage.
- `CLAUDE.md` remains a short handoff and points to the deeper bug-hunt file instead of duplicating stale details.
- Any claim about HA remains qualified until the 3-node failure milestone is actually green.

### Wave 2 - CI and GitHub gate hardening

Status: yellow-green.

Observed:

- GitHub ruleset `protect-master` is active on `refs/heads/master`.
- Required rules include PR, non-fast-forward protection, deletion protection, and required `static-checks`.
- Latest observed `static-checks` run on `master` completed successfully.
- `.github/workflows/ci.yml` still uses version tags for third-party actions instead of SHA pins.
- `infra/ops/configure-github-flux.sh` still defaults `UAP_GITHUB_VISIBILITY` to `private` and includes an optional direct commit/push path to `master`.

Acceptance criteria:

- Workflow actions are SHA-pinned or an explicit ADR/risk note accepts tag pins.
- Bootstrap script matches ADR-026 defaults: public repo, PR/ruleset flow, no default direct push to protected `master`.
- Secret scanning covers project-specific provider token patterns in addition to generic gitleaks coverage.

### Wave 3 - Runtime reproducibility

Status: red-yellow.

Observed:

- `clusters/prod/infra/hermes-agent.yaml` uses `nousresearch/hermes-agent:latest`.
- `clusters/prod/infra/hermes-agent-backup.yaml` uses `nousresearch/hermes-agent:latest` and `rclone/rclone:latest`.
- Hermes-agent bootstrap installs `@openai/codex` and `@anthropic-ai/claude-code` at runtime via unpinned `npm i -g`.
- The live pod has a concrete image digest, but that digest is not encoded in GitOps.

Acceptance criteria:

- Pin hermes-agent and backup images by immutable digest or explicitly document why `latest` is accepted temporarily.
- Pin Codex and Claude Code CLI versions or bake them into a controlled image.
- Add a version smoke that records hermes-agent, codex, claude, node/npm, and image digest.

### Wave 4 - Worker boundary and secrets

Status: red.

Observed:

- A read-only exec inspection exposed secret environment variables inside the worker container output. Values must not be copied into issues, commits, prompts, markdown, or logs.
- The default ServiceAccount currently has no useful RBAC for pods/secrets/nodes in the checked namespace, which is good.
- Manifests do not make the intended ServiceAccount/token-mount boundary explicit enough for future maintainers.
- The coding worker combines powerful tools, persistent state, and sensitive auth in one pod boundary.

Acceptance criteria:

- Rotate any exposed token/password if the tool transcript or logs are considered shared or persistent.
- Set `automountServiceAccountToken: false` explicitly where Kubernetes API access is not required.
- Split or document auth/state/runtime boundaries for Claude OAuth, Codex auth, dashboard auth, and mounted work data.
- Add a log-redaction and "never print env" rule to runbooks and agent handoff docs.

### Wave 5 - Probes and live health

Status: yellow.

Observed:

- Live `uap-system` pods were Ready with no observed restarts.
- `hermes` and `litellm` have readiness/liveness probes.
- `hermes-agent`, `singbox-egress-ha`, and `subfleet-egress` lack readiness/liveness/startup probes.
- `sing-box check -c /etc/sing-box/config.json` passed on the live `singbox-egress-ha` pod.

Acceptance criteria:

- Add safe local probes for sing-box based on process/config/port health.
- Add hermes-agent health checks if the image exposes an endpoint, otherwise add a documented live-smoke command.
- Add a non-destructive smoke matrix for proxy path, brain path, and Telegram/dashboard path.

### Wave 6 - Backup and DR

Status: yellow.

Observed:

- `hermes-agent-backup` CronJob has recent successful runs.
- R2 listing showed recent backup archives for 2026-06-24 through 2026-06-27.
- Backup log reported skipped permission-denied files under `.claude*` and `.codex/config.toml`.
- No canary restore proof was performed during the read-only pass.

Acceptance criteria:

- Verify archive contents without leaking secrets.
- Decide whether skipped Claude/Codex files are expected, or fix permissions/exclude rules deliberately.
- Run an owner-approved canary restore into an isolated path or namespace.
- Document exactly what is recoverable, what must be recreated, and which secrets must be reissued.

### Wave 7 - Egress and network behavior

Status: yellow.

Observed:

- `singbox-egress-ha` is running and its config validates.
- No destructive failover test was performed.
- No claim should be made that egress HA is proven until an owner-approved failure drill passes.

Acceptance criteria:

- Add readonly route/DNS/proxy inspection commands to the runbook.
- Add a planned egress failover drill with owner approval, rollback steps, and expected packet/request behavior.
- Keep HA claims conditional until the milestone is green.

### Wave 8 - Hermes/Codex/Claude harness contract

Status: yellow.

Observed:

- The 2026-06 pivot is documented at a high level, but the operational contract for Hermes launching Codex/Claude tasks is still not tight enough.
- Open questions remain around allowed task classes, owner approval gates, PR boundaries, timeouts, budgets, logs, and rollback behavior.

Acceptance criteria:

- Create an ADR or research doc for the harness contract before broad automation.
- Define task classes: readonly audit, docs-only edit, code PR, infra PR, live-smoke, destructive drill.
- For each class, define required approval, allowed tools, logs, budget, and completion artifact.

### Wave 9 - Observability and ops hygiene

Status: orange.

Observed:

- No recent Kubernetes events were observed in `uap-system`.
- There is no obvious daily readonly health report covering ruleset status, image drift, backup age, pod probes, and static-check status.

Acceptance criteria:

- Add a readonly `ops/health-report` command or script.
- Report at least: git/CI gate, live image digests, latest backup age, failed jobs, pod readiness/restarts, probe coverage, and PV reclaim policy.
- Keep it safe to run from Codex/Claude without exposing secret values.

### Recommended Delegation

Use separate small PRs or worktrees:

1. `docs(source-of-truth)`: Wave 1 docs cleanup.
2. `fix(ci-gate)`: Wave 2 workflow SHA pins, scanner patterns, bootstrap alignment.
3. `chore(runtime-pin)`: Wave 3 image and CLI version pinning.
4. `fix(worker-boundary)`: Wave 4 ServiceAccount/token mount, secret handling, runbook redaction rules.
5. `fix(health)`: Wave 5 probes and live-smoke commands.
6. `test(dr)`: Wave 6 backup content verification and canary restore procedure.
7. `docs(harness-contract)`: Wave 8 ADR/research doc for autonomous task boundaries.

Suggested order:

1. Wave 1 and Wave 4 first, because they reduce coordination and secret-handling risk.
2. Wave 2 and Wave 3 second, because they stabilize PR gates and runtime reproducibility.
3. Wave 5 and Wave 6 third, because they prove operability.
4. Wave 7 and Wave 8 after owner-approved scope decisions.
