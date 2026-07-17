# A7.3 clean Telegram-bound canary evidence — 2026-07-17

## Verdict and boundary

The fixed-profile A7.3 acceptance canary passed. One Telegram-bound Central mission was taken by the installed
systemd timer and completed a non-toy Rust change through authoring, repository tests, independent exact-SHA
read-only review, pull request, Linux/macOS/Windows CI, exact-head merge, fresh-default-branch post-verification,
Central terminal completion and cleanup.

This was one corrected-runtime run with no mid-run code, profile or command repair. It deliberately included the
contract's one-time crash after the author commit became durable and before its Central acknowledgement; the next
timer invocation resumed the same task, run, worktree and candidate without a second author turn. Therefore "clean"
means no operator repair or runtime mutation, not absence of the planned recovery checkpoint.

The canary proves the configured `flow-pilot-a7-3l` route. It does not claim generic arbitrary-repository routing,
complete cross-channel chat/session history, soak, HA or multi-user isolation. Mission acceptance and one-time timer
arming were platform setup actions; after the timer was armed there was no direct coordinator service invocation or
manual tick. The owner ran no command and reviewed no diff.

## Reviewed runtime prerequisite

[UAP PR #238](https://github.com/PavelLizunov/unified-agent-platform/pull/238) closed the final exact-PR preservation
and recovery gaps before the canary:

```text
reviewed head: bc3510998d75fa3fc0b4bb6711a703d9f5bb00b8
static-checks run: 29578257295, success
separate Sol xhigh review: PASS, no actionable findings
merge commit: 87e0e2e1550530455cc74cfb9aca30fa95529f4f
```

The reviewed head is the PR head and is an ancestor of the merge. Build-1 installed that merge through the existing
`install_flow_v2.py` path; installation and the independent `--check` both returned
`hermes-flow-v2-install-ok`. Installed and source `delivery_coordinator.py` hashes matched:

```text
47380bb047dfb1a2ffaa5cfccdd399034f5a3e24786b7be82a1506827724f96d
```

The exact `flow-pilot-a7-3l` profile was mode `0600`; its SHA-256 was
`f016ebd5f180ffd0af5934711f55f3fe13a002508f9041cc037bcd244c5c2c2d`. Other delivery timers were stopped for
isolation. The existing Telegram subscription was bound to the canary mission before the canary timer started.

## Mission, task and route

```text
mission: a7-clean-ledger-list-20260717-a0fc5a
dispatch profile: build1-flow-pilot-a7-3l
native task: t_1d60193c
native run: 38
target: PavelLizunov/hermes-flow-v2-pilot
base SHA: 83076aba6d2a67cfed4769dc5227094dfa958094
```

The deterministic `openai-autonomy-v2` decision was `complex` / `high` because the fixed profile declared
`durable_state`, `multi_platform` and `protocol_or_schema`. Runtime-derived attestations recorded:

| Role | Exact model / effort | Sandbox | Session | Result |
|---|---|---|---|---|
| author | `gpt-5.6-sol` / `xhigh` | `workspace-write` | `019f6ff9-1261-77b2-8996-69ff79446f15` | completed |
| reviewer | `gpt-5.6-terra` / `xhigh` | `read-only` | `019f6ffe-0319-7530-9ba2-34c948b2d247` | accepted, zero findings |

The sessions were distinct. The reviewer saw the exact candidate SHA and could not write to its review worktree.
Claude, local inference, GPU, swarm and Spark were not routes in this profile. The retained coordinator state records
only the two OpenAI/Codex sessions above; the final process scan contained no model or test worker.

## Recovery checkpoint

The author produced one clean candidate commit:

```text
0389b7b42adbc2f772d56255e9ef7b07116d12d6  feat(ledger): list latest mission states
src/lib.rs
src/main.rs
tests/journal.rs
```

At `2026-07-17T12:11:07Z` the coordinator emitted the approved
`hermes-delivery-coordinator-injected-crash` checkpoint after that commit was durable and before Central ACK. systemd
immediately ran the next due invocation. Durable state retained `crash_injected=true`, the same task/run and the same
candidate SHA; author-failure, review-rejection and CI-failure counters all remained zero. No second candidate or
duplicate author session was created.

## Private target GitHub evidence, merge and post-verify

[Target PR #5](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/5) was created as a draft at the exact
candidate, passed pre-review CI, received the accepted Terra review, was marked ready and was merged by the
coordinator. The target repository is private; these PR, commit and Actions URLs require repository access and are not
independently readable by an anonymous auditor. The exact live/private GitHub objects were queried through the
authenticated read-only `gh` client on build-1:

```text
head branch: codex/a7-3l-rust-ledger-list-bb3537feb0bf
candidate/head: 0389b7b42adbc2f772d56255e9ef7b07116d12d6
pull_request run: https://github.com/PavelLizunov/hermes-flow-v2-pilot/actions/runs/29579364955, success
  test-python: job 87881115492, success
  test-linux:   job 87881115499, success
  test-macos:   job 87881115515, success
  test-windows: job 87881115516, success
push run: https://github.com/PavelLizunov/hermes-flow-v2-pilot/actions/runs/29579356190, success
  test-python: job 87881086869, success
  test-linux:   job 87881086740, success
  test-macos:   job 87881086745, success
  test-windows: job 87881086754, success
merged at: 2026-07-17T12:14:16Z
merge/default SHA: 811c24a6383a28eaf9fa6b520bf22598f0788e45
```

The candidate is an ancestor of the merge, and `origin/main` resolved to the merge SHA. Fresh-default-branch
post-verification ran:

```text
/usr/local/bin/cargo test --all-targets --locked
exit code: 0
```

## Central, Workspace and Telegram convergence

Central stored 22 ordered events: one `mission.accepted`, task/stage/worker/change/gate/delivery projections and one
Central-authored `mission.completed`. The terminal projection was:

```text
status=completed stage=complete progress=100 sequence=22
tasks=1 workers=1 gates=5
pull request=merged
default branch=verified
all five gates=passed
```

The following is an explicitly labeled live read-only evidence block from the authenticated Central private API. It
records every canonical envelope field except payload and unused optional session/worker correlation, without chat
identity. `run_id` was not present in these canonical event correlations; the native run `38` is evidenced separately
by the task snapshot above.

```text
seq | event_id                                      | occurred_at              | type              | source         | task_id    | run_id | producer_event_id
1   | a7-clean-ledger-list-20260717-a0fc5a:1       | 2026-07-17T12:05:11.263Z | mission.accepted  | central-hermes | -          | -      | -
2   | a7-clean-ledger-list-20260717-a0fc5a:2       | 2026-07-17T12:06:57.369Z | task.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:4ef836e1e1a9f9b2224b233f
3   | a7-clean-ledger-list-20260717-a0fc5a:3       | 2026-07-17T12:06:58.391Z | mission.stage     | build1-flow    | t_1d60193c | -      | build1-flow:77008c2131334f2184dcea22
4   | a7-clean-ledger-list-20260717-a0fc5a:4       | 2026-07-17T12:07:00.119Z | task.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:efa55190f66127aedabfb5ee
5   | a7-clean-ledger-list-20260717-a0fc5a:5       | 2026-07-17T12:07:00.336Z | worker.upsert     | build1-flow    | t_1d60193c | -      | build1-flow:61801ca2c00f901dc09f4084
6   | a7-clean-ledger-list-20260717-a0fc5a:6       | 2026-07-17T12:11:09.125Z | mission.stage     | build1-flow    | t_1d60193c | -      | build1-flow:d461dd1529ce52e0d44e8188
7   | a7-clean-ledger-list-20260717-a0fc5a:7       | 2026-07-17T12:13:58.673Z | mission.stage     | build1-flow    | t_1d60193c | -      | build1-flow:0e021058dcc0133b09960f6c
8   | a7-clean-ledger-list-20260717-a0fc5a:8       | 2026-07-17T12:14:03.417Z | mission.stage     | build1-flow    | t_1d60193c | -      | build1-flow:8b6dacb4a2242ccb54424375
9   | a7-clean-ledger-list-20260717-a0fc5a:9       | 2026-07-17T12:14:22.321Z | mission.stage     | build1-flow    | t_1d60193c | -      | build1-flow:a2c0b5b2d9f280ba5d5f9c2f
10  | a7-clean-ledger-list-20260717-a0fc5a:10      | 2026-07-17T12:14:28.359Z | task.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:87ce7ce683d811091c7016ea
11  | a7-clean-ledger-list-20260717-a0fc5a:11      | 2026-07-17T12:14:28.572Z | worker.upsert     | build1-flow    | t_1d60193c | -      | build1-flow:710f5807ac70c8f000413d83
12  | a7-clean-ledger-list-20260717-a0fc5a:12      | 2026-07-17T12:14:28.799Z | change.upsert     | build1-flow    | t_1d60193c | -      | build1-flow:fee8202234b519d61feb54b8
13  | a7-clean-ledger-list-20260717-a0fc5a:13      | 2026-07-17T12:14:29.016Z | change.upsert     | build1-flow    | t_1d60193c | -      | build1-flow:19c3719625af5933333fffb4
14  | a7-clean-ledger-list-20260717-a0fc5a:14      | 2026-07-17T12:14:29.252Z | change.upsert     | build1-flow    | t_1d60193c | -      | build1-flow:cfaa57f5a5eb7bd7eadbc9e0
15  | a7-clean-ledger-list-20260717-a0fc5a:15      | 2026-07-17T12:14:29.465Z | gate.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:91ddced74960d211fc155582
16  | a7-clean-ledger-list-20260717-a0fc5a:16      | 2026-07-17T12:14:29.686Z | gate.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:108a5f8c750d3a74f9bfb682
17  | a7-clean-ledger-list-20260717-a0fc5a:17      | 2026-07-17T12:14:29.898Z | gate.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:a5145177aab51d343909880b
18  | a7-clean-ledger-list-20260717-a0fc5a:18      | 2026-07-17T12:14:30.114Z | gate.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:4192d30b4abd042e1073c4d0
19  | a7-clean-ledger-list-20260717-a0fc5a:19      | 2026-07-17T12:14:30.335Z | delivery.upsert   | build1-flow    | t_1d60193c | -      | build1-flow:978a95dc068d6b8469261f94
20  | a7-clean-ledger-list-20260717-a0fc5a:20      | 2026-07-17T12:14:30.546Z | delivery.upsert   | build1-flow    | t_1d60193c | -      | build1-flow:445e520b6625c7855bed4f11
21  | a7-clean-ledger-list-20260717-a0fc5a:21      | 2026-07-17T12:14:30.767Z | gate.upsert       | build1-flow    | t_1d60193c | -      | build1-flow:37df5ead53a477234af3da96
22  | a7-clean-ledger-list-20260717-a0fc5a:22      | 2026-07-17T12:14:31.320Z | mission.completed | central-hermes | -          | -      | central:auto-complete:v1
```

The same query returned `events=22`, `unique_event_ids=22`, `producer_rows=20`, `unique_producer_ids=20` and
`terminal_rows=1`. Thus the recovered run stored no duplicate producer row and exactly one terminal event. This is a
live-state assertion backed by the retained Central database, not a public GitHub object.

An authenticated request through the live Workspace API returned HTTP 200 and the exact same mission object as the
Central API:

```text
Workspace SHA-256: e5b3517f97dbe0df60e9e7ac1547f820ee9e0371a898370e477ffe44b34ede19
Central SHA-256:   e5b3517f97dbe0df60e9e7ac1547f820ee9e0371a898370e477ffe44b34ede19
equal: true
```

The single bound Telegram subscription reached `last_notified_sequence=22`, equal to the terminal Central cursor.
This cursor is a delivery checkpoint, not a Telegram read receipt; delivery retains the documented at-least-once
duplicate window.

## Cleanup and final state

The native task was `archived`, its only run was `done`, and its durable event sequence was
`created, claimed, completed, archived`. The coordinator removed the author and reviewer worktrees, removed the exact
remote head branch after merge, ran the existing Kanban GC checkpoint and retained only the bounded owner-only
delivery state required by the 30-day evidence policy. The one-shot `flow-pilot-a7-3l` timer and service were inactive
after the final no-op tick; the previously active fixed-profile timers were restored after confirming that Central had
no pending or reconcile candidates for them.

## Acceptance result

| Gate | Result |
|---|---|
| exact fixed-profile timer intake | PASS |
| one native task/run | PASS |
| deterministic OpenAI route and runtime attestations | PASS |
| crash recovery without duplicate author/candidate | PASS |
| repository tests and independent exact-SHA review | PASS |
| Linux/macOS/Windows required CI | PASS |
| exact-head PR merge and fresh-main post-verify | PASS |
| Central/Workspace/Telegram terminal convergence | PASS |
| branch/worktree/task cleanup | PASS |

A7.3 is accepted at the configured fixed-profile boundary. This evidence does not widen that boundary or authorize a
new provider, local model/GPU execution, swarm, destructive testing or arbitrary shell/repository input.
