# Hermes Flow v2

ADR-028 contract for real multi-checkpoint repository work. This reuses Hermes Kanban; it does not add
another workflow engine.

Runtime status (2026-07-13): installed on `uap-build-1` from UAP merge
`fe8b1aa0760b5f9cdc84306a03f2237bd40de835`. Installer/check, skill discovery, Claude-blocked routing, and a
no-model Kanban lifecycle smoke all passed. Smoke card `t_9ba72c8e` completed with zero worker processes; no gateway
restart was required.

Repository status (2026-07-14): the A6.2 central mission adapter is implemented, tested, installed on live build-1 and
was exercised once by the owner-approved A6.4 canary. Automatic central intake-to-dispatch is not installed; the
canary orchestrator invoked the adapter explicitly.

## When to use

- Read-only or docs-only change up to three files: ordinary Hermes session is sufficient.
- Any code/infra PR: author → independent read-only reviewer → required CI.
- More than one checkpoint/PR or expected runtime over 30 minutes: Hermes Kanban swarm is mandatory.

## 1. Quota and route preflight

On build-1, install or verify the runtime bridge from a trusted UAP checkout:

```bash
python3 tools/swarm/install_flow_v2.py
python3 tools/swarm/install_flow_v2.py --check
```

This installs the contract/policy under `~/swarm-bin` and the `hermes-flow-v2` skill under
`~/.hermes/skills`. Long missions load that skill and use native Kanban for their durable checkpoint DAG while
Codex CLI provides the separately sandboxed author/reviewer executions.

Claude Code exposes plan status interactively through `/usage`, but the installed CLI has no documented
machine-readable `claude usage --json`. Never spend quota on an empty `claude -p` probe.

Record known state in a mission-local file outside the repository:

```bash
python tools/swarm/flow_contract.py quota-set \
  --file /home/uap/swarm-out/<mission>/quota.json \
  --engine claude --state quota_blocked \
  --reason owner_reported_100_percent
```

Route without local models by default:

```bash
python tools/swarm/flow_contract.py route \
  --policy tools/swarm/flow-policy.json \
  --quota /home/uap/swarm-out/<mission>/quota.json \
  --task-class standard_code \
  --model claude=<exact-model-id>
```

Exit 0 means author+reviewer are runnable. Exit 3 means `author_blocked` or `review_blocked`; do not call the
blocked engine. `--allow-local` is forbidden unless the owner explicitly authorizes local models for this mission.
After a known reset, state becomes `unknown`, not silently `available`; either update it from `/usage` or explicitly
allow the first real task as the availability check.

## 2. Repository guard

Create a disposable worktree/branch, then fail closed before any write:

```bash
python tools/swarm/flow_contract.py guard-repo \
  --path /home/uap/worktrees/<mission> \
  --remote https://github.com/<owner>/<repo>.git \
  --branch agent/<mission>
```

The guard verifies exact root, canonical origin, non-default branch and registered git worktree. A mismatch is a
terminal routing failure, not permission to create a crate in the current directory.

## 3. Kanban DAG

Minimum DAG:

```text
preflight → author → reviewer → CI/PR → merge → cleanup
                 ↖ revise ─────┘
```

Cross-family review is preferred. When Claude is `quota_blocked`, `standard_code` may use the policy's explicit
`same_provider_degraded` fallback: a separate read-only Codex session using a different exact model. This fallback
is forbidden for infra, security and secrets. Reviewer may inspect the diff and run checks, but must not patch files.
A finding creates a `revise` task for the author. Maximum two review cycles; the third becomes `blocked`.

With `codex exec --sandbox workspace-write`, the linked worktree git-admin directory may be outside the writable
root. The author therefore edits and tests only. The orchestrator re-runs the checks, stages an explicit file
allowlist and creates the real commit. Never copy or replace `.git`, and never accept a SHA unless
`git rev-parse HEAD` in the guarded worktree returns it.

## 3a. Central mission adapter

`mission_adapter.py` is installed beside `flow_contract.py`. It does not replace Kanban or run a second dispatcher.
It gives central Hermes one idempotent ingress and converts native Kanban state back into mission producer events.

Acceptance is fail-safe by default:

```bash
python tools/swarm/mission_adapter.py \
  --state-root /home/uap/swarm-out \
  --board default \
  accept --event /path/to/mission-accepted.json
```

This creates or reuses one blocked, unassigned root card. `--allow-dispatch` is forbidden until the owner has approved
the exact runtime/profile and test target. Once approved, the platform must also supply both `--assignee` and a
non-scratch `--workspace`; omission fails closed.

Read the current deterministic producer-event batch without starting work:

```bash
python tools/swarm/mission_adapter.py \
  --state-root /home/uap/swarm-out \
  --board default \
  sync --mission-id <central-mission-id> --output /path/to/events.json
```

Every retry emits stable `producer_event_id` values for central deduplication. The adapter accepts worker metadata only
for file, gate/review and delivery evidence; mission completion remains a central Hermes decision. See
`docs/hermes-mission-contract-v1.md` for the envelope and metadata schema.

Post-A6 automatic handoff uses one bounded pull iteration:

```bash
HERMES_API_URL=http://100.94.228.67:30642 \
python tools/swarm/mission_adapter.py \
  --state-root /home/uap/swarm-out \
  --board default \
  poll \
  --dispatch-profile <owner-approved-profile-label> \
  --workspace <fixed-non-scratch-workspace>
```

`HERMES_API_TOKEN` and `HERMES_MISSION_PRODUCER_KEY` must come from a protected environment file; never pass either
secret on argv. One invocation claims at most one exact-profile mission and stops after projecting its idempotent,
blocked and unassigned root task. An absent/unknown profile, a non-accepted mission or an existing task is skipped.
This default cannot launch a worker. `--activate --assignee <owner-approved-kanban-profile>` is a separate explicit
gate: it creates a ready card and may make the existing Kanban dispatcher launch the configured worker, so the exact
profile, workspace, model route and target require owner approval.

## 4. Durable artifacts

Author writes `/home/uap/swarm-out/<mission>/summary.json`:

```json
{
  "schema_version": 1,
  "repo": "owner/repo",
  "branch": "agent/mission",
  "head_sha": "full-sha",
  "engine_family": "openai",
  "model": "gpt-5.3-codex-spark",
  "session_id": "exact-author-session-id",
  "task_class": "standard_code",
  "changed_files": ["src/lib.rs"],
  "checks": [{"command": "cargo test --locked", "exit_code": 0}],
  "remaining_risks": []
}
```

Reviewer reads the actual worktree/diff and writes `verification.json`:

```json
{
  "schema_version": 1,
  "reviewed_sha": "full-sha",
  "engine_family": "anthropic",
  "model": "exact-claude-model-id",
  "session_id": "exact-reviewer-session-id",
  "review_mode": "cross_family",
  "verdict": "accept",
  "review_cycle": 1,
  "findings": [],
  "checks": [{"command": "cargo test --locked", "exit_code": 0}]
}
```

Validate immediately before merge using the current PR HEAD:

```bash
python tools/swarm/flow_contract.py validate-review \
  --summary /home/uap/swarm-out/<mission>/summary.json \
  --verification /home/uap/swarm-out/<mission>/verification.json \
  --author-telemetry /home/uap/swarm-out/<mission>/author-telemetry.json \
  --reviewer-telemetry /home/uap/swarm-out/<mission>/reviewer-telemetry.json \
  --repo <owner/repo> --head "$(git rev-parse HEAD)" --ci-green
```

The gate cross-checks each artifact's exact model/session against runtime-derived Codex telemetry and requires the
author `workspace-write` and reviewer `read-only` sandbox attestations. Any author commit invalidates the previous
verification.

For the owner-approved standard-code fallback, use a distinct reviewer model/session, set
`"review_mode": "same_provider_degraded"`, and add `--allow-same-provider-review` to `validate-review`. The flag
does not waive SHA, tests, CI, cycle, exact-model, or session checks and is rejected for other task classes.

## 5. Terminal state

`commit`, `PR open`, `CI green` and `merged` are intermediate states. Complete only after all four facts are
independently observed:

1. PR is merged.
2. Default branch contains the merge SHA.
3. Remote/local task branch is deleted.
4. Disposable worktree is removed.

Machine-check the observed facts:

```bash
python tools/swarm/flow_contract.py terminal-check \
  --merged --main-contains-head --branch-deleted --worktree-removed
```

Telemetry must attribute exact sessions/models/tools/retries/timeouts separately for orchestrator, author,
reviewer, CI and external monitor. Unknown token usage remains `null`.

Capture Codex JSONL with `codex exec --json`, retain the matching local rollout, and summarize both without sending
either log to another model. The summarizer requires the rollout `session_meta.id` to equal the JSONL `thread_id` and
derives model/provider/sandbox from its single runtime `turn_context`; the CLI model argument is only the expected
value and a mismatch or Codex `model rerouted` event fails closed:

```bash
python tools/swarm/flow_contract.py summarize-codex \
  --events /home/uap/swarm-out/<mission>/author-events.jsonl \
  --rollout /home/uap/.codex/sessions/<date>/rollout-<session-id>.jsonl \
  --worktree /home/uap/worktrees/<mission> --head <candidate-sha> \
  --component author --model gpt-5.3-codex-spark --sandbox workspace-write \
  --output /home/uap/swarm-out/<mission>/author-telemetry.json
```

Use `--sandbox read-only` for the reviewer. This proves the policy recorded by the exact Codex turn, not an
OS-independent filesystem or credential boundary; preserve before/after worktree evidence for that stronger claim.

## Pilot gate before production integration

Use a separate disposable repository. Required behavioral evidence:

- quota-blocked Claude is not invoked;
- wrong remote is rejected before write;
- author commit after `accept` makes review stale;
- same-family reviewer is rejected by default; degraded standard-code review requires distinct models and sessions;
- review cycle 3 is blocked;
- merge is not called before review+CI;
- terminal completion is withheld until branch/worktree cleanup.

Only after the pilot PR is green may a separate PR wire this flow into production Hermes/Flux configuration.
