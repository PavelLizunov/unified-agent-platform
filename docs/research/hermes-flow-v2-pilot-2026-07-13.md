# Hermes Flow v2 pilot evidence — 2026-07-13

Status: **R1 failed honestly; clean R2 is green and unlocks production integration**.

## Scope

- Host: `uap-build-1`.
- Disposable origin: `/home/uap/hermes-flow-v2-pilot.git` (local bare repository).
- Primary checkout: `/home/uap/hermes-flow-v2-pilot`.
- Author worktree: `/home/uap/worktrees/hermes-flow-v2-pilot-author`.
- Branch: `agent/flow-v2-pilot`.
- Baseline: `83076aba6d2a67cfed4769dc5227094dfa958094`.
- Observed author commit: `9c1147f69b86fadd57f409e1db364a980f0e826a`.
- UAP production, Proxmox, VPN, R2, secrets and local models were out of scope and unchanged.

A GitHub test repository could not be created: the build-1 token returned HTTP 403, the GitHub connector has no
repository-creation operation, and the in-app browser was not signed in. No existing product repository was used as
a substitute. This describes R1; R2 later created the private repository through the owner OAuth on ops-1.

## Routing evidence

Quota state recorded Codex as `available` and Claude as `quota_blocked` from the owner's report that Claude usage was
at 100%. `standard_code` resolved to Codex `gpt-5.6-luna` as author, no reviewer, and `review_blocked`. The skipped
review candidates were Claude (`quota_blocked`) and Codex (`same_family`). Local Ornith/Qwen routing was not enabled.

The wrong expected remote `/home/uap/wrong-repo.git` failed before write. The exact local origin, non-default branch
and disposable worktree passed the repository guard.

## Author telemetry

- Engine/family/model: `codex` / `openai` / `gpt-5.3-codex-spark`.
- Session: `019f5afc-2a58-7630-b5cb-34409bb00aef`.
- Completed items: 29 command executions, 3 file changes and 9 agent messages.
- Failed command executions: 3. Timeouts: 0. Retry count was not exposed and remains `null`.
- Usage reported by Codex JSONL: 713,618 input tokens, 667,392 cached input tokens, 15,157 output tokens and
  12,155 reasoning-output tokens.
- Independent orchestrator check: `python3 -m unittest discover -s <worktree> -v` passed 3/3 tests.

The workspace-write sandbox could edit files but not the linked worktree git-admin directory. Spark copied `.git`
metadata, created a commit on a detached local copy of `main`, deleted that copy, and reported lost SHA `6a47a12` as
the result while the real worktree HEAD remained at the baseline. The orchestrator rejected that claim, staged only
`README.md`, `counter.py` and `test_counter.py`, and created the real commit shown above. Flow v2 now explicitly keeps
commit creation in the orchestrator role and rejects any claimed SHA not returned by `git rev-parse HEAD` in the
guarded worktree.

## Failed or pending gates

- **Claude-not-invoked evidence failed for this run.** Before pilot initialization, a malformed process-monitoring
  command lost its quotes and attempted `claude -p` without a prompt/stdin. The CLI rejected it immediately with
  `Input must be provided`; no Claude session or model response was created. It is still counted as an invocation
  attempt and is not hidden.
- Independent cross-family review was not run because Claude was quota-blocked. No local-model substitute was used.
- `verification.json`, external GitHub required CI, PR merge and terminal cleanup are intentionally absent.
- The worktree branch was not merged or deleted because a failed pilot must preserve inspectable evidence.
- Exact orchestrator runtime model and token usage were not exposed to this harness, so they remain unknown rather
  than being inferred from policy.

## Clean R2 result

R2 is active in private PR `PavelLizunov/hermes-flow-v2-pilot#1`:

- Fresh GitHub baseline and disposable build-1 worktree passed the exact remote/branch/worktree guard; a wrong
  GitHub remote was rejected before write.
- The first author attempt failed closed because Codex CLI 0.142.0 could not run `gpt-5.6-luna`. The CLI was updated
  to stable 0.144.3 and the same exact model was retried; no model substitution occurred.
- Author session `019f5b10-0cef-7e20-960c-c900525471f6` used `gpt-5.6-luna`: 7 command executions, 2 file-change
  batches, 0 failed commands and 0 timeouts; 148,644 input, 124,416 cached input, 2,859 output and 792 reasoning
  tokens. One runtime retry was required for the CLI update.
- The orchestrator created exact commit `de3c6b0d65363ea666d637a54c81b41b67ec3b5a` from the four-file allowlist.
  Both push and pull-request GitHub Actions `test` checks passed. The SHA-bound artifact is
  `hermes-flow-v2-pilot-r2-summary.json`.
- Claude remained `quota_blocked`; no Claude process/session and no local-model substitute was used in R2.
- Owner-approved `standard_code` fallback selected a separate read-only Codex reviewer using exact model
  `gpt-5.6-sol`, session `019f5b1d-9e69-76a3-8fe3-be5b06871510`, and `same_provider_degraded` review mode.
- Reviewer telemetry: 5 command executions, 4 agent messages, 0 failed commands, 0 timeouts; 107,997 input,
  96,512 cached input, 2,604 output and 1,115 reasoning-output tokens. The worktree stayed clean.
- SHA-bound `hermes-flow-v2-pilot-r2-verification.json` recorded `accept` for
  `de3c6b0d65363ea666d637a54c81b41b67ec3b5a`. The validator returned `hermes-flow-review-ok` only with the
  explicit degraded-mode flag and green CI.
- [Pilot PR #1](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/1) was squash-merged as
  `2c6a455822c07245007d713075316af57c19df6d`. Build-1 `main` was fast-forwarded to that SHA; remote/local task
  branches and the disposable worktree were deleted. `terminal-check` returned `hermes-flow-terminal-ok`.

R2 therefore satisfies the pilot gate. It does not claim cross-family independence: the accepted residual risk is
explicitly recorded as same-provider degraded review, limited by policy to `standard_code`.
