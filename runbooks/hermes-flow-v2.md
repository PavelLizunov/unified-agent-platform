# Hermes Flow v2

ADR-028 contract for real multi-checkpoint repository work. This reuses Hermes Kanban; it does not add
another workflow engine.

Runtime status (2026-07-13): installed on `uap-build-1` from UAP merge
`fe8b1aa0760b5f9cdc84306a03f2237bd40de835`. Installer/check, skill discovery, the then-current route guard, and a
no-model Kanban lifecycle smoke all passed. Smoke card `t_9ba72c8e` completed with zero worker processes; no gateway
restart was required.

Repository status (2026-07-14): the A6.2 central mission adapter is implemented, tested, installed on live build-1 and
was exercised once by the owner-approved A6.4 canary. Automatic central intake-to-dispatch is not installed; the
canary orchestrator invoked the adapter explicitly.

## When to use

- Read-only or docs-only change up to three files: ordinary Hermes session is sufficient.
- Any code/infra PR: author → independent read-only reviewer → required CI.
- More than one checkpoint/PR or expected runtime over 30 minutes: Hermes Kanban swarm is mandatory.

## 1. Route preflight

On build-1, install or verify the runtime bridge from a trusted UAP checkout:

```bash
python3 tools/swarm/install_flow_v2.py
python3 tools/swarm/install_flow_v2.py --check
```

This installs the contract/policy under `~/swarm-bin` and the `hermes-flow-v2` skill under
`~/.hermes/skills`. Long missions load that skill and use native Kanban for their durable checkpoint DAG while
Codex CLI provides the separately sandboxed author/reviewer executions.

`openai-autonomy-v1` is a deterministic repo-contract decision, not an LLM classifier. The planner supplies a closed JSON
record with the allowed-file count, prior independent-review rejections for the same task and explicit risk flags:

```json
{
  "schema_version": 1,
  "changed_files": 6,
  "prior_review_rejections": 2,
  "flags": ["cross_process", "durable_state", "multi_platform"]
}
```

Evaluate it without starting a model:

```bash
python tools/swarm/flow_contract.py delivery-route \
  --policy tools/swarm/flow-policy.json \
  --signals /home/uap/swarm-out/<mission>/route-signals.json
```

The installed policy has three standing-approved outcomes:

- `standard`: Luna author (`medium`) / Sol reviewer (`low`);
- `complex`: Sol author / Terra reviewer at `xhigh`;
- `escalated`: two prior review rejections select Terra author / Sol reviewer at `xhigh`.

Unknown flags fail closed. Local/GPU, destructive, architecture, credential/external-authority and new-provider flags
can never become runnable through this command. Canonical signals, the full policy SHA-256 and exact model/effort
route are bound into `decision_id`. Exit 0 means the OpenAI route is ready; exit 3 means owner-gated capability was
requested. Luna/Sol/Terra selection and ordinary spend require no confirmation; Claude/local/GPU are not fallback.

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

Every route uses a separate read-only OpenAI reviewer session with a different exact model. Runtime telemetry must
prove both model identities, distinct sessions, the reviewed SHA and the reviewer read-only sandbox. This is
`same_provider_independent`: provider diversity is not claimed, but the review is not a degraded fallback. Reviewer
may inspect the diff and run checks, but must not patch files. A finding creates a `revise` task; the platform
automatically escalates the route after repeated rejection.

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

This creates or reuses one blocked, unassigned root card. Activation is allowed only through a configured repository
profile. The platform must supply both `--assignee` and a non-scratch `--workspace`; omission fails closed.

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
  --dispatch-profile <configured-profile-label> \
  --workspace <fixed-non-scratch-workspace>
```

`HERMES_API_TOKEN` and `HERMES_MISSION_PRODUCER_KEY` must come from a protected environment file; never pass either
secret on argv. One invocation claims at most one exact-profile mission and stops after projecting its idempotent,
blocked and unassigned root task. An absent/unknown profile, a non-accepted mission or an existing task is skipped.
This default cannot launch a worker. `--activate --assignee <configured-kanban-profile>` creates a ready card only
for the repository/profile fixed in platform configuration. The coordinator chooses the OpenAI route and continues
without per-run confirmation. Owner input remains required only for capabilities outside that contract.

## 4. Durable artifacts

Author writes `/home/uap/swarm-out/<mission>/summary.json`:

```json
{
  "schema_version": 1,
  "repo": "owner/repo",
  "branch": "agent/mission",
  "head_sha": "full-sha",
  "engine_family": "openai",
  "model": "gpt-5.6-luna",
  "reasoning_effort": "medium",
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
  "engine_family": "openai",
  "model": "gpt-5.6-sol",
  "reasoning_effort": "low",
  "session_id": "exact-reviewer-session-id",
  "review_mode": "same_provider_independent",
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

For every OpenAI route, use the distinct reviewer model/session returned by `delivery-route`, set
`"review_mode": "same_provider_independent"`, and add `--allow-same-provider-review` to `validate-review`. The flag
does not waive SHA, tests, CI, cycle, exact-model, sandbox, or session checks.

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
either log to another model. The summarizer requires the rollout `session_meta.id` to equal the JSONL `thread_id`,
requires its `cwd` to equal the attested worktree, and derives model/provider/sandbox from its single runtime
`turn_context`; the CLI model argument is only the expected value and a mismatch or Codex `model rerouted` event fails
closed. Before a read-only reviewer starts, bind its exact source tree to that persisted rollout prompt:

```bash
MARKER="$(python tools/swarm/flow_contract.py attest-source \
  --worktree /home/uap/worktrees/<mission>-review --head <candidate-sha> \
  --output /home/uap/swarm-out/<mission>/reviewer-source.json)"
codex exec --json --sandbox read-only "Review <candidate-sha>. ${MARKER}"
```

```bash
python tools/swarm/flow_contract.py summarize-codex \
  --events /home/uap/swarm-out/<mission>/author-events.jsonl \
  --rollout /home/uap/.codex/sessions/<date>/rollout-<session-id>.jsonl \
  --worktree /home/uap/worktrees/<mission> --head <candidate-sha> \
  --component author --model gpt-5.6-luna --reasoning-effort medium \
  --sandbox workspace-write \
  --output /home/uap/swarm-out/<mission>/author-telemetry.json
```

Use the reviewer model/effort from the resolved route plus `--sandbox read-only --source-attestation
<reviewer-source.json>`. The source digest is present in
the persisted user input, was created no more than five minutes before the session, and must still match the clean
worktree HEAD/tree when summarized. This binds the review turn to the candidate under the single-owner coordinator
threat model; it still does not prove an OS-independent filesystem or credential boundary.

## Pilot gate before production integration

Use a separate disposable repository. Required behavioral evidence:

- only the exact OpenAI route is invoked;
- wrong remote is rejected before write;
- author commit after `accept` makes review stale;
- same-provider review requires the explicit independent mode, distinct exact models and distinct sessions;
- repeated review rejection automatically escalates the OpenAI route;
- merge is not called before review+CI;
- terminal completion is withheld until branch/worktree cleanup.

Only after the pilot PR is green may a separate PR wire this flow into production Hermes/Flux configuration.
