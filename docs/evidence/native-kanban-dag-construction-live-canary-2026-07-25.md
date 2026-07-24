# Native Kanban DAG construction — live canary (2026-07-25)

## Verdict

**PASS for the native Hermes Kanban DAG primitive.**

**NOT PROVEN for automatic decomposition of ordinary UAP delivery missions.** The production
`delivery_coordinator.py` still creates one idempotent Kanban root and drives author, review, CI, delivery,
post-verification, and cleanup as durable phases of that root. This canary must not be cited as evidence that an
ordinary Workspace or Telegram goal is automatically split into parallel delivery workers.

## Boundaries

- UAP repository base observed before the canary:
  `d1af3808f7406282354b0aa964946b4952f5023a`.
- Host: build-1 (`100.85.56.31`), using the installed executable:
  `/home/uap/hermes-agent/.venv/bin/hermes`.
- Hermes surface: native `kanban swarm` from the intentionally pinned build-1 v0.18 runtime.
- Storage: a new `HERMES_HOME` and Kanban SQLite database under a process-specific `/tmp` directory.
- No production Kanban board, Central mission, repository, GitHub object, worker, model, or Telegram message was
  created or changed.
- A shell trap removed the temporary directory and SQLite database on exit.

## Scenario

The canary constructed one deterministic graph with:

- one completed planning/root card;
- two parallel worker cards;
- one verifier card;
- one synthesizer card;
- one tenant and one idempotency key.

The command did not invoke the dispatcher. The graph was inspected directly from the temporary SQLite
`tasks` and `task_links` tables.

## Observed result

The persisted graph contained exactly five tasks and five directed edges:

```text
root
  ├─> worker A ─┐
  └─> worker B ─┴─> verifier ─> synthesizer
```

The assertions passed:

```text
dag-canary-ok
{"parallel_workers": 2, "production_board_mutated": false,
 "synthesizer_status": "todo", "tasks": 5,
 "tenant": "canary-dag-20260725", "verifier_status": "todo"}

dag-edges-ok
{"edges": 5, "initial_ready": ["Worker A", "Worker B"],
 "shape": "root -> 2 parallel workers -> verifier -> synthesizer"}
```

Only Worker A and Worker B were `ready`. The verifier and synthesizer were `todo`, proving that dependency
promotion had not been bypassed. The root was already `done`, matching the native Swarm v1 blackboard protocol.

## What this proves

- The installed build-1 Hermes binary exposes the expected native `swarm`, `link`, and `decompose` Kanban surfaces.
- `kanban swarm` persists a real dependency graph rather than only a visual grouping.
- Sibling worker tasks become ready in parallel.
- The verifier depends on both workers.
- The synthesizer depends on the verifier.
- Graph construction is safe to test in an isolated board without model execution.

## Remaining integration gap

The UAP mission adapter currently calls `HermesKanbanBackend.ensure_root()` once. The delivery coordinator claims,
completes, and archives that same root; it does not call `kanban swarm`, `kanban decompose`, or create child tasks.
Therefore:

- the Workspace task count of one is accurate for ordinary delivery;
- author/reviewer/CI phases are not separate Kanban cards;
- task decomposition does not currently reduce token use or parallelize repository edits;
- native decomposition cannot be enabled blindly because UAP must preserve the OpenAI-only actor allowlist,
  one-writer worktree contract, exact candidate SHA, independent review, bounded retries, and restart idempotency.

A future integration requires an explicit coordinator/ADR change and its own regression plus ordinary-message live
canary. This evidence deliberately does not make that completion claim.
