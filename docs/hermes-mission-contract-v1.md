# Hermes Mission Contract v1

Status: **A6.1 contract**. This is the smallest shared state boundary needed by the
[Product Operating Contract](product-operating-contract.md). Central Hermes owns the log; Workspace, Telegram and
build-1 are clients or producers, never alternate authorities.

## Identity and ordering

- `mission_id` is an opaque, stable ID allocated once by central Hermes.
- Each accepted event has a central `sequence`, starting at 1 and increasing by exactly 1.
- `event_id` is stable and unique within the mission. Replayed events keep the same ID.
- Consumers persist only their last applied sequence, request events after that cursor, ignore a replayed event ID and
  reject a gap. Refresh is a replay from sequence 0.
- Producers may attach their own idempotency key in `correlation.producer_event_id`; central Hermes assigns the final
  sequence and event ID exactly once.

## Event envelope

```json
{
  "schema_version": 1,
  "mission_id": "mission-example",
  "sequence": 1,
  "event_id": "mission-example:1",
  "occurred_at": "2026-07-14T14:00:00Z",
  "type": "mission.accepted",
  "source": "central-hermes",
  "correlation": {
    "session_id": "optional",
    "run_id": "optional",
    "task_id": "optional",
    "worker_id": "optional",
    "producer_event_id": "optional"
  },
  "payload": {}
}
```

Fields and event types are closed for v1: unknown top-level, correlation or payload fields and unknown event types are
rejected before persistence. Schema expansion therefore requires an explicit contract revision rather than silent
forward-compatible storage.

### Producer submission

Build-1 submits the same envelope without the central-only fields `sequence`, `event_id` and `occurred_at`. It must
include a deterministic `correlation.producer_event_id`. Central Hermes deduplicates that value, then assigns the
canonical sequence, event ID and timestamp. A producer retry is therefore safe after a crash between execution and
checkpoint persistence. Producer submissions must use source `build1-flow`; they cannot create `mission.accepted` or
any terminal mission event. Every allowed string is inspected before SQLite storage: normal fields are force-redacted,
while a sensitive idempotency key is rejected instead of being mutated and breaking retry identity.

## Event types

| Type | Required payload | Projection effect |
|---|---|---|
| `mission.accepted` | `goal`; optional `dispatch_profile` | status becomes `active`, stage `accepted` |
| `mission.stage` | `stage`, `progress_percent` | updates the owner-visible stage/progress |
| `mission.question` | `question_id`, `text` | status becomes `waiting_owner` |
| `task.upsert` | `task_id`, `title`, `status` | creates or replaces one task projection |
| `worker.upsert` | `worker_id`, `status` | creates or replaces one worker projection |
| `terminal.append` | `stream`, `text` | appends bounded terminal/tool output |
| `change.upsert` | `path`, `status` | records a changed artifact |
| `gate.upsert` | `gate_id`, `status` | records test, review, CI or verification state |
| `delivery.upsert` | `kind`, `status`, `url` | records PR, deploy or release evidence |
| `mission.completed` | `result` | terminal success; stage `complete`, progress 100 |
| `mission.failed` | `error` | terminal failure |
| `mission.cancelled` | `reason` | terminal cancellation |

Stages are `accepted`, `planning`, `implementing`, `testing`, `reviewing`, `delivering`, `verifying` and `complete`.
Progress is an integer from 0 through 100 and may not decrease. Terminal events are final; later events are invalid.
`dispatch_profile` is an immutable, opaque label. Central Hermes stores and projects it; only an exact build-1
configuration match authorizes handoff. An absent or unknown label does not dispatch.

## Authority rules

- Central Hermes stores the canonical event log and cursor.
- Workspace and Telegram derive the same projection by applying the same ordered events.
- Browser/local files may cache a projection but never create a competing mission history.
- Build-1/Flow publishes correlated events and uses `producer_event_id` for retry safety; it does not allocate a second
  user-facing mission ID.
- A missing central authority is an explicit unavailable state. `HERMES_CENTRAL_ONLY=1` must not switch to local
  sessions, profiles, tasks, Kanban, jobs or native-swarm execution.

## Hermetic gate

`tests/fixtures/hermes-mission-events-v1.json` is the canonical A6.1 timeline.
`tests/static/test_hermes_mission_contract.py` validates the envelope and proves that:

1. a Workspace projection survives disconnect/reconnect by cursor;
2. a Telegram projection consuming different page sizes reaches the same state;
3. a full Workspace refresh reaches that same state;
4. duplicate replay is idempotent and sequence gaps fail closed.

The fake backend is test-only and stdlib-only. It does not add a Python production runtime.

## Build-1 adapter boundary

`tools/swarm/mission_adapter.py` reuses native Hermes Kanban. It creates the root card with
`--idempotency-key central-mission:<mission_id>` and uses the mission ID as the Kanban tenant. The default card is
blocked and unassigned. Dispatch is possible only when the caller explicitly supplies `--allow-dispatch`, an
assignee and a non-scratch workspace; model/runtime approval remains outside this contract.

The adapter projects `kanban list/show/log` into `task.upsert`, `worker.upsert` and bounded `terminal.append` producer
events. Worker completion metadata may contribute only `change.upsert`, `gate.upsert` and `delivery.upsert`; a worker
cannot forge a terminal mission event. Expected metadata shape:

```json
{
  "mission_events": [
    {"type": "change.upsert", "payload": {"path": "src/lib.rs", "status": "modified"}},
    {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "passed"}},
    {"type": "gate.upsert", "payload": {"gate_id": "review", "status": "passed"}},
    {"type": "delivery.upsert", "payload": {
      "kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/1"
    }}
  ]
}
```

`tests/static/test_hermes_mission_adapter.py` injects a crash after Kanban create, restarts the adapter/backend against
the same store and proves that one task completes without duplicate work or producer events. This is an offline gate;
At the A6.2 checkpoint the adapter was not yet installed into the live build-1 runtime; A6.4 later installed it for the
controlled canary. It reuses Flow v2's existing Python runtime and standard library, so it adds no interpreter or
third-party package.

The post-A6 `poll` command is a bounded pull handoff. It asks Central Hermes for the oldest eligible projection with
the exact locally configured immutable `dispatch_profile` and accepts at most one mission per invocation. Eligibility
also requires status/stage `active`/`accepted` and no projected task. Filtering happens before the response limit, so
an older accepted mission cannot be hidden by more than 100 newer records. API credentials come from environment
variables rather than argv. The caller supplies the fixed assignee and non-scratch workspace; mission data never
becomes a shell command.

`dispatch_profile` is a routing selector, not a Central capability or server-side registry. Central validates and
freezes the label; the owner-approved build-1 invocation supplies the matching profile, workspace and optional
assignee. A7.1 considers the blocked root handed off once its deterministic `task.upsert` is projected. Reconciliation
uses a separate bounded `reconcile` command and `reconcile=1` Central selector: it finds one already handed-off active
mission, reconstructs a missing local cache only from one exact native root, and republishes the current deterministic
Kanban projection. A committed prefix is therefore deduplicated and a partially published multi-event suffix is
retried. This primitive does not install a timer, activate a task, run a worker or complete a mission.

The `tick` command is the smallest coordinator: reconcile one existing active mission first, otherwise poll and hand
off one new mission. It preserves a single execution lane per configured invocation and remains non-spawning unless
the separately owner-approved caller passes both `--activate` and an exact assignee.

The safe default creates an unassigned root with `--initial-status blocked`. The exact pinned Hermes overlay records
the sticky native `needs_input` block in the same SQLite transaction as the task, so a concurrent dispatcher sees
either no task or the complete blocked task and never a dispatchable intermediate state. The adapter verifies exact
task identity, blocked status, null assignee, the sticky event and no runs before returning; legacy/non-sticky state
fails closed. The patched native board enforces one non-archived task per idempotency key with a partial SQLite
`UNIQUE` index; two concurrent creators return the same root. Its directory is `0700`, and the database plus
WAL/SHM/journal files are owner-only `0600`. `--activate` additionally requires an assignee and is the only mode that
leaves a ready card. A crash after
Kanban commit but before the central POST repeats the same Kanban idempotency key and producer event ID, so it converges
to one root task and one central task event without a dispatch lease table. The hermetic test uses a fake Kanban and
fake central API and invokes no model. A periodic service/timer and its exact assignee/profile remain a separate
owner-approved live rollout; enabling `--activate` can cause the existing Kanban dispatcher to launch a worker.

## Central runtime and channel projections

A6.3 adds a stdlib-only module at `tools/hermes-mission/runtime.py`, installed only into the exact pinned external
Hermes source by `tools/hermes-mission/apply_overlay.py`. It is part of the existing Hermes modular monolith, not a new
service:

- SQLite at `$HERMES_HOME/missions-v1.sqlite3` owns the canonical log and Telegram subscriptions;
- the existing authenticated gateway API exposes mission list/create/read, central-terminal and producer-event
  endpoints;
- producer writes require a separate `HERMES_MISSION_PRODUCER_KEY`, are idempotent, and cannot publish a terminal
  mission event;
- the central mission SQLite file and build-1 adapter JSON are owner-only (`0600`); adapter-created mission state
  directories are `0700` on POSIX;
- only an authenticated direct loopback caller inside the Central Hermes process boundary may publish `completed`,
  `failed` or `cancelled`; forwarded client headers are ignored, and terminal retries with the same status and
  redacted message are idempotent;
- the Workspace API proxies the structured central projection and the existing Dashboard polls it every two seconds;
- Telegram `/mission [mission-id]` binds a chat to that mission, and owner-relevant stage/question/terminal events
  render from the exact same projection and `projection_id`;
- terminal/question text is force-redacted at the Hermes API boundary and all stored/event frames are bounded.

The Workspace card uses native expand/collapse and shows stage/progress first; tasks, workers, terminal, changes,
gates and delivery links are secondary detail. It deliberately uses bounded polling instead of adding another SSE
stream: refresh/reconnect simply re-fetches the authoritative projection.

`tests/static/test_hermes_mission_runtime.py` reopens the SQLite file, replays the canonical fixture from a cursor and
proves that Workspace and Telegram reach the same projection hash. It also proves producer-event idempotency,
notification deduplication after the cursor checkpoint, central-only completion, monotonic progress and terminal
authority. Telegram delivery is at-least-once: a crash after the remote send but before `last_notified_sequence` is
stored can repeat that notification. Both pinned overlays pass idempotency/tamper checks; the patched Workspace
production build and an aiohttp mission API smoke pass on build-1 without touching live services.

A6.3 remained offline until owner-approved A6.4. UAP PR #178 added the generated ConfigMap, SOPS-encrypted producer
key and fail-closed Deployment mounts; Flux reconciled its exact merge revision. UAP PR #179 then migrated the two
known legacy Workspace overlay hashes, rebuilt the pinned Workspace and restarted its owner-approved service.

Mission `a6-canary-help-20260714` subsequently exercised the contract through implementation, tests, exact-SHA
read-only review, PR/CI/merge and post-verify. Central and Workspace returned the same terminal projection, the
Telegram cursor matched the central cursor, and replaying all adapter events created no duplicates. The full sanitized
record is [A6.4 controlled canary evidence](evidence/a6-4-controlled-canary-2026-07-14.md).
