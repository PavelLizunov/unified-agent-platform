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

Required fields are fixed for v1. `correlation` and `payload` are objects and may be empty. Unknown payload fields must
be preserved. Unknown event types may be retained for forward compatibility but do not change a v1 projection.

### Producer submission

Build-1 submits the same envelope without the central-only fields `sequence`, `event_id` and `occurred_at`. It must
include a deterministic `correlation.producer_event_id`. Central Hermes deduplicates that value, then assigns the
canonical sequence, event ID and timestamp. A producer retry is therefore safe after a crash between execution and
checkpoint persistence.

## Event types

| Type | Required payload | Projection effect |
|---|---|---|
| `mission.accepted` | `goal` | status becomes `active`, stage `accepted` |
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
the adapter is not installed into the live build-1 runtime by this phase. It reuses Flow v2's existing Python runtime
and standard library, so it adds no interpreter or third-party package.

## Central runtime and channel projections

A6.3 adds a stdlib-only module at `tools/hermes-mission/runtime.py`, installed only into the exact pinned external
Hermes source by `tools/hermes-mission/apply_overlay.py`. It is part of the existing Hermes modular monolith, not a new
service:

- SQLite at `$HERMES_HOME/missions-v1.sqlite3` owns the canonical log and Telegram subscriptions;
- the existing authenticated gateway API exposes mission list/create/read and producer-event endpoints;
- producer writes require a separate `HERMES_MISSION_PRODUCER_KEY`, are idempotent, and cannot publish a terminal
  mission event;
- the Workspace API proxies the structured central projection and the existing Dashboard polls it every two seconds;
- Telegram `/mission [mission-id]` binds a chat to that mission, and owner-relevant stage/question/terminal events
  render from the exact same projection and `projection_id`;
- terminal/question text is force-redacted at the Hermes API boundary and all stored/event frames are bounded.

The Workspace card uses native expand/collapse and shows stage/progress first; tasks, workers, terminal, changes,
gates and delivery links are secondary detail. It deliberately uses bounded polling instead of adding another SSE
stream: refresh/reconnect simply re-fetches the authoritative projection.

`tests/static/test_hermes_mission_runtime.py` reopens the SQLite file, replays the canonical fixture from a cursor and
proves that Workspace and Telegram reach the same projection hash. It also proves producer retry and Telegram
notification idempotency, central-only completion, monotonic progress and terminal authority. Both pinned overlays
pass idempotency/tamper checks; the patched Workspace production build and an aiohttp mission API smoke pass on
build-1 without touching live services.

This remains an offline rollout artifact. No live Hermes/Workspace checkout, service, model, GPU, swarm or Kubernetes
manifest was changed by A6.3. Wiring secrets, installing the overlays and executing a disposable mission belong to
owner-approved A6.4.
