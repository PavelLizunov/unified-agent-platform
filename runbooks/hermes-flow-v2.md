# Hermes Flow v2

ADR-028 contract for real multi-checkpoint repository work. This reuses Hermes Kanban; it does not add
another workflow engine.

## When to use

- Read-only or docs-only change up to three files: ordinary Hermes session is sufficient.
- Any code/infra PR: author → independent read-only reviewer → required CI.
- More than one checkpoint/PR or expected runtime over 30 minutes: Hermes Kanban swarm is mandatory.

## 1. Quota and route preflight

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

Author and reviewer profiles must resolve to different engine families. Reviewer is read-only: it may inspect the
diff and run checks, but must not patch files. A reviewer finding creates a `revise` task for the author. Maximum two
review cycles; the third request becomes `blocked` with evidence.

With `codex exec --sandbox workspace-write`, the linked worktree git-admin directory may be outside the writable
root. The author therefore edits and tests only. The orchestrator re-runs the checks, stages an explicit file
allowlist and creates the real commit. Never copy or replace `.git`, and never accept a SHA unless
`git rev-parse HEAD` in the guarded worktree returns it.

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
  --repo <owner/repo> --head "$(git rev-parse HEAD)" --ci-green
```

Any author commit invalidates the previous verification.

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

Capture Codex JSONL with `codex exec --json` and summarize it without sending the log to another model:

```bash
python tools/swarm/flow_contract.py summarize-codex \
  --events /home/uap/swarm-out/<mission>/author-events.jsonl \
  --component author --model gpt-5.3-codex-spark \
  --output /home/uap/swarm-out/<mission>/author-telemetry.json
```

## Pilot gate before production integration

Use a separate disposable repository. Required behavioral evidence:

- quota-blocked Claude is not invoked;
- wrong remote is rejected before write;
- author commit after `accept` makes review stale;
- same-family reviewer is rejected;
- review cycle 3 is blocked;
- merge is not called before review+CI;
- terminal completion is withheld until branch/worktree cleanup.

Only after the pilot PR is green may a separate PR wire this flow into production Hermes/Flux configuration.
