# Ordinary Workspace owner-answer rollout — 2026-07-18

## Scope and verdict

The exact Central Workspace session that accepted an ordinary goal can now route a later ordinary message to its one
open mission question through `MissionStore.ingest_owner_turn()`. This closes the deployed implementation asymmetry
with Telegram without adding a service or client-selected routing field.

This is a component/deployment pass, not a live owner question/answer canary. No production question was created or
answered during this rollout.

## Immutable implementation identity

```text
PR:                    #270
head:                  211fc08626bf73330ec88eab6bc460158c1e71c3
merge:                 5d95eada6b455740dd1fa1c49f61652f8e394942
required CI run:       29659152612 / static-checks passed
```

The ingress uses the same stable Workspace source-message ID that accepted the mission. If the exact accepting Central
session has one bound `waiting_owner` mission and one open question, the turn becomes `mission.answer` rather than a
second mission. The source message ID is persisted with the answer; same-text replay converges, changed-text replay
collides fail-closed, and multiple eligible questions are rejected rather than guessed. The existing structured answer
endpoint remains compatible.

## Exact rollout

Flux source and the production Kustomization converged to merge
`5d95eada6b455740dd1fa1c49f61652f8e394942`. The replacement Central pod
`hermes-agent-78fc4879f9-c6gmw` became Ready and returned HTTP 200. The merged runtime source and mounted pod file matched
at SHA-256 `123663992c31ce939eb618a59eee7b8ce5fd732cf9e7055924a25fb8cb157788`; the mounted pinned API-server overlay hash was
`f87b41aafab3d93d4c6c7d7d98607357540b28f74f2f19ca3f7449172551e460`.

An in-pod temporary-store component scenario returned `live-workspace-answer-component-ok`, proving the installed
ordinary-message path, answer persistence and no-second-mission invariant without mutating production mission data.
Later Flux rollouts retained the same merged behavior.

## Honest boundary

Accepted:

> The deployed Central ordinary Workspace ingress can deterministically answer the one open question of the mission
> accepted by that exact session, with restart-safe source-message idempotency and no second mission.

Still required:

- a live Workspace-origin question answered through Telegram;
- a live Telegram-origin question answered through Workspace;
- reconnect/replay proof around that owner answer;
- complete cross-channel chat/session transcript synchronization.
