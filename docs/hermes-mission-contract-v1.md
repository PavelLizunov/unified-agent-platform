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
