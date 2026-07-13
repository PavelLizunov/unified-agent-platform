# Hermes Flow v2 pilot evidence — 2026-07-13

Status: **not green; production integration remains blocked**.

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
a substitute.

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

## Required rerun

1. Create a private `PavelLizunov/hermes-flow-v2-pilot` repository with Actions enabled.
2. Start a fresh mission after Claude quota becomes available and record the exact Claude model before the real
   reviewer task; do not spend quota on a dummy probe.
3. Run author → orchestrator commit → read-only cross-family reviewer → required CI → merge → branch/worktree cleanup.
4. Require matching `summary.json`, `verification.json`, actual PR HEAD and green CI, then run `terminal-check`.

Only that clean rerun may turn the pilot gate green.
