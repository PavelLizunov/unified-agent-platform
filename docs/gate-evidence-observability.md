# Gate Evidence Observability

Status: **implemented 2026-07-24**. Incremental gate checkpoints published by the delivery
coordinator as each gate durably passes, giving the owner real-time progress without waiting
for the terminal batch.

## Event shape

Each gate checkpoint is a `gate.upsert` producer event published to the central MissionStore:

```json
{
  "schema_version": 1,
  "mission_id": "<mission-id>",
  "type": "gate.upsert",
  "source": "build1-flow",
  "correlation": {
    "task_id": "<root-task-id>",
    "producer_event_id": "build1-flow:<sha256-24>"
  },
  "payload": {
    "gate_id": "<gate>",
    "status": "passed"
  }
}
```

### Fields

| Field | Source | Notes |
|---|---|---|
| `gate_id` | coordinator phase | One of: `tests`, `review`, `ci`, `post-verify`, `deployment`, `cleanup` |
| `status` | coordinator phase | `passed` when the gate durably succeeds |
| `task_id` | `state["root_task_id"]` | Identity-bearing correlation field |
| `producer_event_id` | `_producer_event` hash | `sha256({type, payload, task_id})[:24]` — deterministic, idempotent |

## Idempotency and reconciliation

The `producer_event_id` hashes only `{type, payload, task_id}` (the identity-bearing fields).
Routing-only correlation fields (`worker_id`, `run_id`, `session_id`) are excluded from the
hash. This means:

- The incremental checkpoint (correlation `{task_id}`) and the terminal batch replay
  (correlation `{task_id, worker_id}`) share the **same** `producer_event_id`.
- `_append_events_locked` reconciles the re-publish instead of raising a collision.
- A genuine forgery (same `producer_event_id`, different `type`/`source`/`payload` or
  different `task_id`) still fails closed with `"producer event id collision"`.

## Publish points

| Phase | Gate | Trigger |
|---|---|---|
| `pre_review_ci_green` | `tests` | After candidate branch + draft PR verified, before review |
| `pr_open` | `review` | After independent review accepted, before final CI |
| `ci_green` | `ci` | After final CI green, before merge |
| `verified` | `post-verify` | After fresh-main post-verify, before cleanup/deploy |
| `deployed` | `deployment` | After deployment verified, before cleanup |
| `cleaned` | `cleanup` | After cleanup, before Kanban task completion |

## Projection

Gate events project into `projection["gates"]` as `{"gate_id": ..., "status": ...}` entries,
keyed by `gate_id`. The terminal batch is authoritative; incremental checkpoints are
owner-facing evidence only. Completion requires all five `_COMPLETION_GATES`
(`tests`, `review`, `ci`, `post-verify`, `cleanup`) to be `passed`.
