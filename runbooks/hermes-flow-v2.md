# Hermes Flow v2

ADR-028 contract for real multi-checkpoint repository work. This reuses Hermes Kanban; it does not add
another workflow engine.

Runtime status (2026-07-13): installed on `uap-build-1` from UAP merge
`fe8b1aa0760b5f9cdc84306a03f2237bd40de835`. Installer/check, skill discovery, the then-current route guard, and a
no-model Kanban lifecycle smoke all passed. Smoke card `t_9ba72c8e` completed with zero worker processes; no gateway
restart was required.

Repository status (2026-07-16): the A6 adapter, profile-bound A7 coordinator and `openai-autonomy-v2` schema-v3 profile
are installed on build-1. Attempt 7 reached accepted review, required CI, exact-head merge, fresh-main post-verify and
cleanup, while #218-#221 repaired four harness defects between durable ticks. This proves recoverable delivery; the
next gate is one clean uninterrupted repeat on that corrected runtime, with a bound Telegram subscription. Generic
arbitrary-repository intake remains outside the current fixed-profile boundary.

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

The coordinator must not inherit Workspace's owner-answer capability. Before enabling any coordinator timer,
provision `~/.config/uap/delivery-coordinator.env` with mode `0600` and only the two Central client variables
`HERMES_API_URL` and `HERMES_API_TOKEN`. The producer capability remains in the existing owner-only
`~/.config/mission-producer-key`. Never copy `HERMES_MISSION_OWNER_KEY` into the coordinator environment. A safe
migration from the existing protected Workspace environment is:

```bash
install -d -m 0700 "$HOME/.config/uap"
temporary="$(mktemp "$HOME/.config/uap/.delivery-coordinator.env.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
sed -n '/^HERMES_API_URL=/p; /^HERMES_API_TOKEN=/p' \
  "$HOME/hermes-workspace/.env" > "$temporary"
test "$(grep -Ec '^(HERMES_API_URL|HERMES_API_TOKEN)=' "$temporary")" = 2
! grep -q '^HERMES_MISSION_OWNER_KEY=' "$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$HOME/.config/uap/delivery-coordinator.env"
trap - EXIT
```

The installed systemd unit reads only that file and explicitly unsets `HERMES_MISSION_OWNER_KEY`. This prevents
normal coordinator execution from receiving the Workspace owner capability; it does not claim isolation from a
separately compromised process running as the same trusted build-1 Unix account.

Before enabling an A7.3 timer, migrate its stopped legacy two-cycle profile atomically. This removes manual model/
effort fields, sets schema v3 and makes all three bounded routes reachable:

```bash
PROFILE=<profile>
systemctl --user stop \
  "hermes-delivery-coordinator@${PROFILE}.timer" \
  "hermes-delivery-coordinator@${PROFILE}.service"
systemctl --user reset-failed \
  "hermes-delivery-coordinator@${PROFILE}.timer" \
  "hermes-delivery-coordinator@${PROFILE}.service" || true
test "$(systemctl --user is-active "hermes-delivery-coordinator@${PROFILE}.timer" || true)" = inactive
test "$(systemctl --user is-active "hermes-delivery-coordinator@${PROFILE}.service" || true)" = inactive
python3 tools/swarm/install_flow_v2.py \
  --migrate-profile "$HOME/.config/uap/delivery-${PROFILE}.json"
```

The helper rechecks that both matching units are exactly `inactive`, validates the complete v3 profile before
`os.replace`, keeps mode `0600`, and is idempotent. A schema v1/2 profile or a correction budget outside three to
seven retries after the initial candidate fails closed in the coordinator; the canonical contract rejects review
cycles above eight.

This installs the contract/policy under `~/swarm-bin` and the `hermes-flow-v2` skill under
`~/.hermes/skills`. Long missions load that skill and use native Kanban for their durable checkpoint DAG while
Codex CLI provides the separately sandboxed author/reviewer executions.

`openai-autonomy-v2` is a deterministic repo-contract decision, not an LLM classifier. The planner supplies a closed JSON
record with the allowed-file count, prior author-gate/review/required-CI quality failures for the same task and explicit
risk flags:

```json
{
  "schema_version": 1,
  "changed_files": 6,
  "prior_quality_failures": 2,
  "flags": ["cross_process", "durable_state", "multi_platform"]
}
```

Evaluate it without starting a model:

```bash
python tools/swarm/flow_contract.py delivery-route \
  --policy tools/swarm/flow-policy.json \
  --signals /home/uap/swarm-out/<mission>/route-signals.json \
  > /home/uap/swarm-out/<mission>/route-decision.json
```

The installed policy has three standing-approved outcomes:

- `standard`: Luna author (`medium`) / Sol reviewer (`low`);
- `complex`: Sol author / Terra reviewer at `xhigh`;
- `escalated`: any two prior author-gate, review or required-CI failures select Terra author / Sol reviewer at `xhigh`.

Unknown flags fail closed. Local/GPU, destructive, architecture, credential/external-authority and new-provider flags
can never become runnable through this command. Canonical signals, the full policy SHA-256 and exact model/effort
route are bound into `decision_id`. Exit 0 means the OpenAI route is ready; exit 3 means owner-gated capability was
requested. Luna/Sol/Terra selection and ordinary spend require no confirmation; Claude/local/GPU are not fallback.

A failed required CI check is a normal autonomous repair signal. The coordinator persists only bounded check
name/outcome metadata, increments the durable quality-failure count, selects the next route, reruns the author and
independent exact-SHA review, verifies the previously bound PR number/branch/head/base before the repair push, pushes
with an exact prior-head lease to that same PR and verifies the new head. It never sends raw CI logs to a model. Exhausted
pre-commit author gates have no PR identity: they retain only redacted bounded diagnostics and terminate after local
cleanup. Once a PR exists, terminal failure requires a live claim and exact PR identity. GitHub does not support
conditional requests for unsafe PR-close mutations, so an open exact failed PR/branch is preserved as bounded evidence;
if the PR is already closed, only its unchanged branch/SHA is lease-deleted. Local disposable state is still cleaned and
the failed delivery is projected. Compatible exact v1 route and PR identity remain usable for their in-progress cycle. Restarts after a
successful initial push, PR create or repair push reconcile only the exact branch/candidate/base identity and converge
without repeating the successful mutation. New cycles use v2. The coordinator then removes local worktrees and publishes the
terminal failure contract.

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

The build-1 Hermes checkout must also receive the exact transformed `hermes_cli/kanban.py` and
`hermes_cli/kanban_db.py` from a detached checkout of pinned upstream commit
`7c1a029553d87c43ecff8a3821336bc95872213b`. Stage that detached tree with
`tools/hermes-mission/apply_overlay.py`, stop the coordinator timer, copy only those two verified files into the
build-1 Hermes checkout, and restart the timer after their SHA-256 values match `PATCHED_FILES`. Do not install the
Central gateway/API overlay files on build-1. This pair is indivisible: the CLI passes the owner-answer audit
reference into the same native SQLite transaction that persists `unblocked`, and adapter recovery rejects any
different/manual unblock.

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
  "route_decision_id": "sha256-of-the-canonical-policy-decision",
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
  "route_decision_id": "sha256-of-the-canonical-policy-decision",
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
  --route-decision /home/uap/swarm-out/<mission>/route-decision.json \
  --policy tools/swarm/flow-policy.json \
  --repo <owner/repo> --head "$(git rev-parse HEAD)" --ci-green
```

The gate recomputes the canonical decision from its persisted signals/policy, enforces the exact ADR-031 model/effort
tuples and approved runtime provider, requires both artifacts to bind the same
`decision_id`, cross-checks exact model/session/effort against runtime-derived Codex telemetry, and requires author
`workspace-write` plus reviewer `read-only` sandbox attestations. Any author commit invalidates the previous
verification. Every route uses the distinct reviewer model/session and `same_provider_independent` mode returned by
`delivery-route`; no manual review waiver exists.

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
- repeated author-gate failure, review rejection, required-CI failure or bounded CI timeout automatically escalates
  the OpenAI route; a PR is reused only after one exists;
- successful/failed CI state contains only bounded name/outcome metadata;
- lost responses after initial push, PR create or repair push reconcile the exact remote identity without duplication;
- exhausted pre-commit author gates retain redacted bounded diagnostics and no PR evidence; after PR creation, final
  failure under a live claim preserves an open exact PR/branch as bounded evidence, while an already closed PR permits
  exact-lease deletion of only its unchanged branch/SHA;
- an exact compatible v1 in-progress decision resumes under v2 while a tampered decision fails closed;
- merge is not called before review+CI;
- terminal completion is withheld until branch/worktree cleanup.

Only after the pilot PR is green may a separate PR wire this flow into production Hermes/Flux configuration.
