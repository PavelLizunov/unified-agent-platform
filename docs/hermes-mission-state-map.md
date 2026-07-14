# Hermes Mission State Map

Status: **A6.0 evidence, complete 2026-07-14**. This document describes the current implementation; the target
behaviour remains the [Product Operating Contract](product-operating-contract.md) and ADR-030.

## Scope and evidence

This map was produced without starting a model, swarm, GPU workload or service and without reading live user data.
It is based on:

- UAP `master` at `dc9aae7701b8a74d70e962b6e5dfa26e8c797eed`;
- the exact Workspace upstream checkout `c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c` on `uap-build-1`;
- the ten Workspace files changed by the fail-closed overlay in `tools/hermes-workspace/apply_overlay.py`;
- manifests, runbooks and Flow contract code in this repository.

The Workspace source is external and is not vendored in UAP. Facts from that checkout are called out explicitly.
The UAP repository does not vendor the upstream Telegram adapter or central Conductor implementation, so their
internal storage and channel-to-session mapping are declared unknown rather than inferred.

## Current topology

```text
Telegram ---------------------------> central hermes-agent (k3s, home-2)
                                             |
Browser -> Workspace (build-1 :3000) --------+-- sessions/messages -> /opt/data/state.db
       |                                     +-- Kanban           -> /opt/data/kanban.db
       |                                     +-- scheduled jobs   -> /opt/data/cron/jobs.json
       |                                     +-- Conductor API     -> backing store not vendored
       |
       +-- local browser mission/task state
       +-- local Workspace run/session/task state
       +-- automatic central/local backend selection
       +-- local native-swarm fallback -> build-1 workers/tmux/profile state

central Hermes -- build1 MCP tool --> one-shot claude/codex subprocess result

local Flow v2 -> build-1 Kanban/tmux/worktrees -> /home/uap/swarm-out/<mission>/
```

Central Hermes is the durable chat service today. Workspace is both a central-Hermes client and a separate local
orchestrator/state owner. Flow v2 is another local execution path. Those paths do not yet share one durable mission
record or one correlation identifier.

## State ownership

| State | Current owner and store | Identifiers | Surfaces | Classification |
|---|---|---|---|---|
| Chat sessions and messages | central Hermes PVC: `/opt/data/state.db` | central `session_id`/session key | Workspace chat/history, dashboard, Telegram | Current durable chat authority |
| Codex brain memory | central Hermes PVC: `/opt/data/.codex/{memories_1,goals_1,state_5}.sqlite` | Codex-internal IDs | central brain | Internal authority, not a mission ledger |
| Central Kanban | central Hermes PVC: `/opt/data/kanban.db` | task/card ID | dashboard; Workspace only when the proxy is selected | Central board, not joined to every chat |
| Central scheduled jobs | central Hermes PVC: `/opt/data/cron/jobs.json` | cron job ID | central dashboard/API | Central automation, not ordinary chat runs |
| Central Conductor missions | pinned upstream dashboard `/api/conductor/missions` | mission ID and optional `session_id` | Workspace Conductor when the capability is available | API proven; backing store is not in UAP source |
| Workspace upstream routing | `<Workspace state dir>/workspace-overrides.json` | configured API/dashboard URLs | all Workspace server routes | Local configuration with higher precedence than environment |
| Workspace stream run cache | `<Workspace HERMES_HOME>/webui-mvp/runs/<session>/<run>.json` | `sessionKey`, `runId` | Workspace live/background-run UI | Local projection/cache |
| Workspace portable sessions | `<Workspace checkout>/.runtime/local-sessions.json` | local session ID | merged into `/api/sessions` | Alternate local authority |
| Workspace Task Lite | `<Workspace HERMES_HOME>/tasks.json` | local task ID, optional `session_id` | `/api/hermes-tasks` | Local build-1 authority |
| Workspace local Kanban | `<Workspace HERMES_HOME>/kanban.db` or `swarm2-kanban.json` | local card ID | `/api/claude-tasks`, depending on backend selection | Local build-1 fallback authority |
| Workspace native-swarm missions | `<Workspace checkout>/.runtime/swarm-missions.json` | `conductor-<time>` mission ID, assignment IDs | Conductor when central capability is unavailable | Local build-1 control plane |
| Workspace Conductor state | browser `localStorage`: `conductor:active-mission`, `conductor:history`, `conductor-settings` | browser mission ID, job alias, worker/session keys | one browser profile | Browser-local projection/authority |
| Older Workspace mission state | browser `localStorage`: `clawsuite:mission-checkpoint`, `clawsuite:mission-history` | browser checkpoint ID | one browser profile | Browser-local authority |
| Workspace Hub tasks | browser `localStorage`: `clawsuite:hub-tasks` | browser task ID, optional `missionId` | one browser profile | Browser-local authority |
| Workspace Jobs screen | build-1 profile `cron/jobs.json` files by default | profile cron job ID | `/api/claude-jobs?profiles=all` | Local profile jobs, not central jobs |
| Flow v2 mission | build-1 Kanban plus `/home/uap/swarm-out/<mission>/` | directory mission name; author/reviewer engine `session_id` | local Hermes/CLI/tmux and artifacts | Independent execution authority |
| Delivery evidence | Git commit, PR, CI, deploy/release IDs | repository-specific IDs | GitHub and project runtime | Not joined to a central mission today |

The central PVC inventory is documented in `runbooks/hermes-agent-dr.md`. Workspace paths and selection behaviour
come from the pinned external source. Flow paths and artifact fields are defined by `runbooks/hermes-flow-v2.md` and
`tools/swarm/flow_contract.py`.

## Actual request flows

### Workspace chat

```text
browser
  -> Workspace /api/send-stream
  -> central /api/sessions/{session_id}/chat/stream
  -> central SSE containing session_id/run_id/output
  -> Workspace-local run cache
  -> browser stream and later central session history
```

This path is correlated by the central `session_id` and per-send `run_id`. Workspace also polls persisted central
messages roughly every 800 ms to reconstruct tool events that are missing from the upstream live callback path. The
reconstruction is best-effort and the local run cache is not the central source of truth.

`/api/sessions` also merges portable local sessions into the central list. If the dashboard is available but the
enhanced session API is not, Workspace may return a friendly session ID with `persisted: false`. Therefore every row
visible in Workspace is not necessarily a durable central session.

### Telegram

Telegram terminates in the same central Hermes deployment and uses the same PVC-backed service. UAP proves that the
central service persists sessions/messages and maintains `channel_directory.json`; it does **not** prove how the
upstream Telegram adapter chooses or resumes a `session_id`.

Consequently:

- shared process/storage is proven;
- shared Workspace/Telegram history for the same user goal is **not** proven;
- no repository-backed mapping from a Telegram update ID/chat ID to a Workspace `session_id` or mission ID exists.

### Central Hermes to build-1

The managed central configuration exposes two build-1 MCP tools:

- `claude_code(repo, task, extra_args)` starts a fresh SSH subprocess and returns combined final output;
- `build1_shell(command, workdir)` starts a remote command and returns its output.

This is a direct delegation bridge, not Flow ingestion. It creates no durable central mission/task event for the
child process, streams no correlated terminal events back to the mission plane, and does not join Git/CI/deploy IDs.

### Workspace Conductor

The pinned Workspace source uses two mutually exclusive paths:

1. if the central dashboard advertises Conductor, POST `/api/conductor/missions` and poll that mission;
2. otherwise, automatically create a **local native-swarm** mission and dispatch build-1 worker profiles.

The browser persists the active mission separately. Worker discovery for dashboard missions is partly heuristic:
known session keys, label prefixes, creation time and text matching are used. A durable `mission_id -> all worker
session_id` relation is not guaranteed.

### Flow v2

Flow v2 is installed as a skill for the local build-1 Hermes. It uses local Kanban, tmux workers, worktrees and
artifacts under `/home/uap/swarm-out/<mission>/`. `summary.json` and `verification.json` require the coding engine's
author/reviewer session IDs, but do not require a central Hermes session or mission ID.

There is no current adapter that consumes a central mission, idempotently creates the Flow DAG and publishes ordered
worker/test/review/PR/deploy events back to that same central mission.

## Fallbacks and ambiguity

| Behaviour | Current result | Product risk |
|---|---|---|
| `<Workspace state dir>/workspace-overrides.json` has precedence over service environment | Workspace can point at a different API/dashboard even in central-only mode | UI can silently leave the intended authority |
| Central profile fetch fails or profile is missing | profile browser falls through to build-1 files | stale local agents can appear as if central |
| Models in `HERMES_CENTRAL_ONLY=1` | models endpoint returns central models only | This path is already fail-closed |
| Task screen loads | probes Hermes Task Lite and Kanban, then chooses using availability/data count | an empty or changed screen can mean a source switch |
| Kanban backend auto-detection | central dashboard when available, else local SQLite/JSON | cards can come from different databases |
| Forced central Kanban is unavailable | implementation can still return the local backend | `central-only` is not an authority invariant |
| Central Kanban card conversion | `missionId`, reviewer and report path become `null` | mission correlation is discarded at the proxy boundary |
| Jobs screen loads | asks for all profiles and reads build-1 profile cron stores | empty Jobs does not mean central Hermes has no jobs/sessions |
| Central Conductor unavailable | automatically launches local native-swarm | hidden switch to a second execution/control plane |
| Session list loads | central rows are merged with portable local rows | one UI list contains multiple authorities |

These facts explain why an empty Jobs/Tasks panel is not evidence that the active central chat disappeared. They do
not by themselves establish the root cause of intermittent page loading, token counters or network latency.

## Identifier gaps

The following identifiers exist, but no enforced join spans them:

```text
central session_id
  ? central Conductor mission_id
  ? central/local Kanban task ID
  ? Workspace browser mission/task ID
  ? native-swarm assignment ID
  ? Flow <mission> directory
  ? coding author/reviewer session_id
  ? commit / PR / CI / deploy / release IDs
```

`run_id` correlates one Workspace stream with one central session. It is not the durable product `mission_id` from
ADR-030. Workspace sometimes returns `jobId = missionId` for Conductor; that value is not a scheduled cron job ID.

## A6.0 gate result

**PASS for the mapping gate; FAIL for the target product contract.**

- Workspace chat -> central session/output: **traced** through `session_id` and `run_id`.
- Telegram -> same central deployment/PVC: **traced**; Telegram -> same Workspace session: **missing upstream link**.
- Central session -> build-1 direct command: **traced**, but only as a one-shot MCP result.
- Central mission -> Flow DAG -> ordered progress/result: **missing link**.
- One authoritative Tasks/Jobs/Kanban view: **not present**; current source selection and fallbacks are listed above.
- Flow result -> central mission -> synchronized Workspace/Telegram result: **missing link**.

The smallest next phase is A6.1: define one central mission/event contract and hermetic channel/reconnect tests, then
make `HERMES_CENTRAL_ONLY=1` fail closed for authority selection. It must not add a replacement dashboard or start a
live model/swarm canary.

## Repository evidence index

- Central deployment, ports, probes and PVC: `clusters/prod/infra/hermes-agent.yaml`.
- Central persistence/DR inventory: `runbooks/hermes-agent-dr.md`.
- Central build-1 bridge and history statement: `clusters/prod/infra/hermes-agent-config.yaml`.
- Owner access surfaces: `runbooks/hermes-access.md`.
- Workspace pin and operation: `runbooks/hermes-workspace-webcenter.md`.
- Workspace fail-closed overlay and tests: `tools/hermes-workspace/apply_overlay.py`,
  `tools/hermes-workspace/test_overlay.py`.
- Local Flow lifecycle and artifacts: `runbooks/hermes-flow-v2.md`, `tools/swarm/hermes-flow-v2/SKILL.md`,
  `tools/swarm/flow_contract.py`.
- Local Flow/Workspace boundary: `docs/codex-brain-onboarding.md`.
- Target behaviour and sequence: `docs/product-operating-contract.md`, ADR-030, `docs/next-steps.md`.

Pinned external Workspace files inspected read-only:

- `src/routes/api/send-stream.ts`, `src/routes/api/sessions.ts`, `src/server/claude-api.ts`;
- `src/server/run-store.ts`, `src/server/local-session-store.ts`, `src/server/workspace-state-dir.ts`;
- `src/lib/tasks-api.ts`, `src/server/tasks-store.ts`, `src/server/kanban-backend.ts`;
- `src/lib/jobs-api.ts`, `src/routes/api/claude-jobs.ts`, `src/server/hermes-cron-profiles.ts`;
- `src/routes/api/conductor-spawn.ts`, `src/server/swarm-missions.ts`;
- `src/screens/gateway/hooks/use-conductor-gateway.ts`,
  `src/screens/gateway/lib/mission-checkpoint.ts`, `src/screens/gateway/components/task-board.tsx`;
- `src/server/gateway-capabilities.ts`, `src/server/profiles-browser.ts`, `src/routes/api/models.ts`.
