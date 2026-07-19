# Interrupted-author recovery and Russian progress rollout — 2026-07-19

## Verdict

PASS for the deployed correction. If an author turn has a durable ambiguous checkpoint, its exact transient unit is
gone and its disposable worktree was deleted externally, the coordinator no longer remains in `reconciling`
forever. It records one execution-state failure, cleans and archives through the existing rejection path, and does
not start another author or count an availability failure as a quality failure.

Telegram and Workspace now render the existing mission stages, capacity/recovery notices, owner question, progress
and terminal result in clear Russian. Durable event types, notice codes, routing and owner-gate authority are
unchanged.

## Immutable source and tests

| Fact | Value |
|---|---|
| primary PR | [#299](https://github.com/PavelLizunov/unified-agent-platform/pull/299) |
| primary head | `03528cc9949101a3606476b570b0b07e6f3bbac4` |
| primary merge | `5e9b8d93b732682ec0fdd2c294aed0b0484c501c` |
| primary CI | [29696978269](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29696978269) |
| overlay follow-up PR | [#300](https://github.com/PavelLizunov/unified-agent-platform/pull/300) |
| final merge | `97e6fb4f8b81aecbf0c046fc757833b90d8aa72a` |
| follow-up CI | [29697952120](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29697952120) |
| coordinator suite | `130` passed |
| local repository gate | `verify-local-ok` |

The recovery regression covers a lost completion response and restart after the worktree disappeared. It asserts no
author/worktree recreation, no quality-counter increment, one terminal execution failure and persisted rejection.
A separate regression requires stale worktree registration to be pruned before local branch deletion. Central tests
require exactly `execution=failed` plus `cleanup=passed` for this terminal contract.

The first Workspace rollout attempt stopped fail-closed because the newly merged overlay did not list the exact
previously deployed card hash. No Workspace file was changed. PR #300 added only that pinned predecessor hash and a
history-based upgrade regression; the Linux overlay integration check then passed.

## Exact rollout

Flux reported both source and Kustomization `Ready=True` at final revision `97e6fb4f...`. Central pod
`hermes-agent-78896674d6-gxb45` is Ready with zero restarts and revision `v55-russian-mission-progress`; `/health` and
Dashboard `/api/status` returned HTTP 200.

| Artifact | Exact SHA-256 |
|---|---|
| mission runtime source and mounted file | `fa62f1f6eaab4b7f2ac5d9065be5ffac357f5b247a27e9e0f179901d9e4f4fad` |
| mounted Central API overlay | `438666691b5d858ddfc3fbe0a61ace314767f2d00dabc01afaeecf11812cb897` |
| coordinator source and installed file | `bce3b92fc43d87d5b755d2e44971098595bd2ed5f4dce8568f77195fa2917046` |
| Workspace card source and installed file | `5b03769fc1be0c253168ffe9e4ac5a1de062489d99efdb65a9e3a3b3fa9ec69c` |

The pinned Workspace overlay reached `exact-patched`; `pnpm install --frozen-lockfile && pnpm build` passed, the
Workspace service restarted active, its root returned HTTP 200, and the protected runtime environment remained
`0700`/`0600` with the owner capability present. Both Russian progress strings were found in the production client
bundle. All six coordinator timers are active; every service completed a later natural tick with `Result=success` and
`ExecMainStatus=0`.

## Claim boundary

Accepted:

> The registered build-1 delivery loop converges safely when an already-ambiguous author worktree has disappeared,
> and both owner windows render the same durable mission state with clearer Russian progress and results.

Not claimed:

- reconstruction or continuation of work whose ambiguous worktree was lost;
- a destructive live deletion of a production mission worktree (the failure matrix is hermetic);
- translation of internal event IDs, technical diagnostics or arbitrary producer-defined text;
- arbitrary repository/profile delivery, actual deploy/release modes, full chat transcript synchronization or HA.
