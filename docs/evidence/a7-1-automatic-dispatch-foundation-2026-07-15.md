# A7.1 Automatic Mission Dispatch Foundation — offline evidence

Date: 2026-07-15
Status: **PREPARED OFFLINE; NOT MERGED, DEPLOYED OR LIVE-ACCEPTED**

## Authority baseline

- GitHub `master`: `63f647e30e7aaea6d88b2f8f5383682844e2c3d9`.
- Hermes remains the agent layer; Central Hermes remains the only mission authority.
- Build-1 remains an execution plane and receives no arbitrary command, repository path, model ID or credential from a
  mission.
- The user's original Windows checkout was not modified; all work used disposable worktrees.

## Candidate stack

| PR | Exact head | Offline result |
|---|---|---|
| [#182](https://github.com/PavelLizunov/unified-agent-platform/pull/182) | `da3962490fe6f72052df7a772ad1175f36ed9b44` | bounded pull handoff, blocked-by-default task and crash recovery |
| [#184](https://github.com/PavelLizunov/unified-agent-platform/pull/184) | `327e9dc06cf983267f2874899eb614e3cebafba8` | terminal authority requires authenticated direct loopback |
| [#185](https://github.com/PavelLizunov/unified-agent-platform/pull/185) | `885ba8a0e6401d1589001284e28edad4ce817e92` | closed producer schema and pre-storage redaction |
| [#186](https://github.com/PavelLizunov/unified-agent-platform/pull/186) | `4b809a2dd785cab708ee78fdd9d6fa56a4c466cb` | owner-only mission DB and adapter state modes |

All four PRs are draft, mergeable and have successful `static-checks`. The three security commits contain no
`Co-Authored-By` trailer: Claude did not participate or run.

## Proven offline

1. `mission.accepted` may carry one immutable optional `dispatch_profile`.
2. One bounded adapter poll reads at most 100 current projections and handles at most one exact-profile mission.
3. The safe default creates or reuses one blocked, unassigned native Kanban root using
   `central-mission:<mission_id>`; only explicit `--activate` plus an assignee can make it ready.
4. A simulated failure after Kanban create but before producer publish converges after restart to one task, one
   `root_task_id` and one deterministic `task.upsert`; no terminal event or model runner is invoked.
5. Producer submissions accept only the closed v1 envelope, exact `build1-flow` source and allowlisted primitive
   fields. A producer cannot create `mission.accepted` or a terminal event. Structured strings are redacted before
   SQLite storage; a sensitive idempotency key is rejected instead of mutated.
6. Remote holders of the general API bearer cannot call the terminal endpoint; only an authenticated direct loopback
   caller can.
7. On POSIX, the mission SQLite file is repaired to `0600`, adapter JSON is `0600`, and adapter-created mission state
   directories are repaired to `0700`.

## Verification evidence

- Windows: `tests/verify-local.ps1 -SkipSmoke` returned `secret-scan-ok`, `iac-static-ok` and `verify-local-ok` for
  every candidate patch.
- Linux/ops-1: mission runtime, adapter, deployment and secret-scan tests passed.
- The exact pinned Hermes `7c1a029553d87c43ecff8a3821336bc95872213b` overlay passed apply, idempotency,
  fingerprint, image-root and tamper checks.
- Offline aiohttp API smoke accepted and deduplicated a valid producer event, rejected an unknown payload field and
  rejected producer-created `mission.accepted`.
- POSIX mode regressions began with deliberately over-permissive files/directories and proved repair to `0600`/`0700`.
- An offline bottom-up merge rehearsal preserved the exact PR heads with merge commits, completed without conflicts and
  produced tree `4c1170cc33108d57c1186cf989bfdc65b63750e4`, exactly matching #187. The folded tree again passed
  `tests/verify-local.ps1 -SkipSmoke`. A sequential squash rehearsal conflicted at #184, so A7.2 must preserve the
  reviewed stack ancestry with merge commits rather than improvise conflict resolution on `master`.
- GitHub Actions: [#182](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29367928747),
  [#184](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29370027332),
  [#185a](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29370025614),
  [#185b](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29370026016),
  [#186a](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29370025506) and
  [#186b](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29370026791) completed successfully.

No Qwen, local inference, GPU, Claude, swarm, Spark Runner, model turn or destructive fault injection was used.

## Explicitly not proven

- The stack is not in `master`; Flux has not reconciled it.
- Central Hermes was not restarted and the updated adapter was not installed on build-1.
- No live `mission.accepted → blocked task → task.upsert` canary has run.
- No periodic timer, claim, worker, author/reviewer, PR delivery, merge or post-verify path is enabled by A7.1.
- No automatic Central Hermes completion caller exists in A7.1. The loopback guard deliberately removes the former
  remote general-bearer completion path; a later coordinator must use the authenticated local authority path.
- Independent model review was not run because no reviewer/model was owner-approved for this stage.
- A7.3 is specified in `docs/a7-real-project-canary.md`, but its target, routes, activation, recoverable fault and full
  delivery/cleanup run remain unapproved and unexecuted.

## Next owner gate

A7.2 requires one explicit approval covering the draft stack merge **bottom-up with merge commits**, Flux verification,
controlled Central Hermes restart, build-1 adapter update and one disposable poll **without** `--activate`. Acceptance
is exactly one blocked, unassigned Kanban task and one central `task.upsert`, with no worker/model process. Work stops
before activation.
