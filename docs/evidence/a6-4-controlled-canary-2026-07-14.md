# A6.4 controlled canary evidence — 2026-07-14

## Approved boundary

The owner approved one disposable end-to-end canary with this exact route:

- central provider/runtime: `openai-codex` / `codex_app_server`;
- author: `gpt-5.6-luna`;
- independent exact-SHA read-only reviewer: `gpt-5.6-sol`;
- target: private `PavelLizunov/hermes-flow-v2-pilot`;
- change: add `counter.py --help`, one focused test and README usage;
- delivery: tests, independent review, PR/CI, merge and fresh-main post-verify.

The model IDs and `read-only` mode below are the approved and recorded route labels. The current
`flow_contract.py summarize-codex` input does not derive model identity from a runtime event, and the evidence does not
attest an OS-enforced read-only filesystem or credential boundary for the reviewer.

Qwen, local inference, GPU, Claude, swarm, Spark Runner and destructive tests remained forbidden. The owner did not
perform an execution step after approving this boundary.

## Runtime rollout

1. [UAP PR #178](https://github.com/PavelLizunov/unified-agent-platform/pull/178), merge
   `61b9f53e83cdff5fbaf6dda31fe5595b0d2d79d9`, installed the exact pinned central mission overlay, SOPS-encrypted
   producer key and fail-closed Deployment mounts. `static-checks` passed. Flux reconciled that exact revision and the
   new central Hermes pod was `Running` with zero restarts.
2. The live managed config reported provider `openai-codex`, runtime `codex_app_server` and default model
   `gpt-5.6-luna`. Central `/health` and Dashboard `/api/status` returned HTTP 200.
3. [UAP PR #179](https://github.com/PavelLizunov/unified-agent-platform/pull/179), merge
   `9b532cfe071b2934093694201ba477d35bb01497`, added fail-closed migration from the two known legacy Workspace overlay
   hashes. `static-checks`, the exact-source overlay check and `pnpm install --frozen-lockfile && pnpm build` passed.
   The owner-approved Workspace restart returned HTTP 200 with zero subsequent restarts.
4. The build-1 adapter was installed from the exact merge. Its 64-byte producer key matched the central Secret by
   SHA-256; no key value was printed or stored in evidence.

## Disposable mission

- Mission: `a6-canary-help-20260714`.
- Kanban task: one root task, one claimed run and one worker; no swarm.
- Disposable author branch: `agent/a6-canary-help-20260714`.
- Author result: commit `388b197876d081ff75247e7baa843e0d141cc3ca`, exactly three changed files and 20
  inserted lines. The focused gate passed 4/4 tests.
- Author telemetry recorded a completed turn with label `gpt-5.6-luna`. The first ephemeral transport attempt did not emit
  `turn.completed`, was rejected, left no accepted change and was retried through the same approved model route.
- Separate review used a different session and recorded `gpt-5.6-sol` in `read-only` mode against exact commit
  `388b197876d081ff75247e7baa843e0d141cc3ca`. It reran the 4/4 test gate, returned `accept` and reported no findings.
  The worktree remained clean at the reviewed SHA.
- The machine contract accepted the same-provider degraded review only after proving different exact models,
  different sessions, exact author/reviewer/current HEAD equality and green CI.

## Delivery and post-verify

- Target [PR #2](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/2) merged as
  `3c20400b5c004d25ddceb767d7d8a09454115091` using a merge commit, so reviewed commit `388b197...` remains an
  ancestor of `main`.
- Both the [push CI](https://github.com/PavelLizunov/hermes-flow-v2-pilot/actions/runs/29356327455) and
  [PR CI](https://github.com/PavelLizunov/hermes-flow-v2-pilot/actions/runs/29356358979) completed successfully.
- A fresh `main` checkout passed 4/4 tests and `python3 counter.py --help` printed the documented usage.
- The remote branch, local disposable branch and disposable worktree were removed. `flow_contract.py terminal-check`
  passed all four terminal conditions.

## Shared observation proof

- The adapter projected one completed task, one completed worker, three changes, four passed gates and one merged PR.
- Its ten deterministic producer events were replayed once; all ten returned `created=false`.
- Central Hermes completed the mission at event cursor 26. Repeating the terminal request returned the same event with
  `created=false`.
- Central API and authenticated Workspace API returned equal completed projections with SHA-256
  `9c69b3f46a8201c03e7b03cabda082453fdd40a06079be09952cb455b25f46ec`, stage `complete` and progress 100%.
- The single Telegram subscription reached `last_notified_sequence=26`, equal to the central mission cursor.

## Honest boundary after the canary

This proves the A6 mission projection and one owner-approved, explicitly orchestrated route end to end. It does not
prove runtime-derived model identity or an OS-enforced read-only reviewer, and it does not yet make arbitrary missions
fully push-button: Codex orchestration explicitly created/claimed the Kanban task, invoked the approved author and
reviewer routes and published the adapter events. No human operator action was hidden, but automatic central-mission
dispatch and route selection remain a later product milestone. One canary is also not a soak or HA claim.
