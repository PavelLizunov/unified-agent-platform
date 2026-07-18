# Workspace mission cursor replay — live evidence (2026-07-18)

## Scope

This record covers one narrow Product Operating Contract boundary: the live Workspace Dashboard must recover the
ordered Central mission event history after a browser reload without using a snapshot as an event-history substitute.
It does not claim complete Workspace/Telegram chat transcript synchronization or live cross-channel question/answer.

## Landed implementation

- PR [#256](https://github.com/PavelLizunov/unified-agent-platform/pull/256), merge
  `037af9a7a090d6ae41ee5d0d59e89315f0ef87bb`, added the authenticated Workspace proxy for
  `GET /api/missions/{mission_id}?after=<cursor>`, sequence/cursor validation and the compact ordered timeline.
- PR [#257](https://github.com/PavelLizunov/unified-agent-platform/pull/257), merge
  `b1ca68a9e394e46e56717de0dfe906f80b0a0ad0`, fixed the null first-render race found by the first live rollout and
  added an exact vulnerable-asset upgrade regression.
- GitHub Actions `static-checks` passed on both exact PR heads:
  - PR #256: run `29651866277`;
  - PR #257: run `29652212538`.

Before each merge, the repository `tests/verify-local.ps1` gate ended in `verify-local-ok`. The pinned upstream
Workspace overlay test passed on Linux. Both client and SSR production builds passed against the exact pinned
Workspace source.

## Preserved failed rollout

The first live PR #256 rollout was not rewritten as success. Its production build and service restart passed, but the
first Dashboard render failed with:

```text
Cannot read properties of null (reading 'events')
```

The cause was a client-only null race: before either mission query had returned, `undefined === undefined` selected a
branch that dereferenced `replayRef.current.events` while the ref was still null. No Central mission data was changed
or lost. PR #257 removed that unnecessary fallback; events are rendered only from the already validated query result.
Its overlay accepts the exact vulnerable PR #256 asset and upgrades it deterministically.

## Exact live rollout

The live build-1 Workspace was installed from detached UAP merge worktree commit:

```text
b1ca68a9e394e46e56717de0dfe906f80b0a0ad0
```

The installer and `--check` both reported the mission route and card as `exact-patched`. Source/installed hashes were
equal:

```text
mission-overview-card.tsx
486df3f1451ce7cbc4e80dbce70dd3105d39b78b64b5c61d2a2a6e91fd0b532d

missions.ts
45d6f3fb04da76e955147faa59b5295637da239c2727cee059b3ba81b3dd39a9
```

The exact live source built successfully, `hermes-workspace.service` restarted at
`2026-07-18 16:35:31 UTC`, and `GET http://127.0.0.1:3000/dashboard` returned HTTP 200.

## Browser reconnect canary

The authenticated live Workspace selected completed ordinary-intake mission:

```text
mission-intake-f53871c022ce187501a0e9d9021b8823
```

Before reload, its expanded mission card showed:

```text
Tasks 1 · Workers 1 · Gates 5 · Changes 1 · Events 20
event 20 · cursor 20
```

The timeline was strictly ordered from sequence 1 `mission.accepted` through sequence 20 `mission.completed`, with one
rendered `mission.completed`. The browser then performed a full page reload. After the live queries recovered, the
same card again showed 20 events and cursor 20. The complete rendered details text before and after reconnect was
identical, including the mission ID, event order, five passed gates and terminal deliveries.

## Accepted claim and remaining boundary

Accepted:

> For the selected Central mission, live Workspace now consumes durable ordered event-cursor replay, rejects sequence
> gaps/cursor mismatches, and reconstructs the same complete mission timeline after browser reconnect.

Not accepted by this canary:

- complete Workspace/Telegram chat transcript unification;
- a live question created in one window and answered in the other;
- ordinary Telegram goal intake;
- exactly-once Telegram notification presentation;
- unbounded terminal/tool-log replay beyond the bounded Central event contract.
