# A7.2 Live Blocked Handoff Evidence

Date: 2026-07-15
Status: **COMPLETE AT THE NON-ACTIVATING BLOCKED-HANDOFF BOUNDARY**

## Accepted boundary

A central mission carrying the exact build-1 routing selector reached one native Hermes Kanban root and one Central
`task.upsert`. The root was atomically created with a sticky `needs_input` block, no assignee and no run. A repeated
poll returned `null`. No worker, coding model, local model, GPU workload, swarm or Spark Runner was selected or
started. The owner performed no operator command.

This is not the autonomous delivery loop in the Product Operating Contract. There is still no periodic poller,
automatic activation, author/reviewer coordinator, PR/CI/merge/deploy state machine or automatic Central completion
caller. Those remain A7.3 work and require a new owner-approved route and target.

## Landed revisions

| Change | Exact result |
|---|---|
| Original A7 stack integration | PR [#189](https://github.com/PavelLizunov/unified-agent-platform/pull/189), merge `9909f79477a4d92f812928613747bf68e9f4119c` |
| Atomic sticky-block correction | PR [#190](https://github.com/PavelLizunov/unified-agent-platform/pull/190), reviewed head `ac4c63e090a54cb0e8ea34bf0f0a9a84c247d602`, merge `97739fe0e92985c639fc8650eb1043a35b3b4014` |
| Deployment staging correction | PR [#191](https://github.com/PavelLizunov/unified-agent-platform/pull/191), reviewed head `ab9b27cf4feda1bd5fae156c5da7942fdf5d171b`, merge `7214ad78cc9093f6529fc7e2dedb95eaa0682ec7` |

PR #189 preserved every reviewed stack head with merge ancestry and had tree
`814b5fd943ebab8c5f1d73efbd5c54107b61021c`, exactly matching the final folded candidate tree. PRs #185-#188 were
closed as superseded only after their exact heads were proven ancestors of the integration merge; GitHub could not
mark the stacked PRs merged automatically after their bases changed.

The pre-merge audit finding that a fixed latest-100 scan could starve an old accepted mission was corrected before
#189: Central filters the oldest eligible exact-profile candidate before the response limit. The same correction also
rejects producer idempotency-key collisions and tests response loss after a committed producer event.

## Independent review

The final PR #190 head was reviewed from a clean detached worktree by a separate `codex exec` session:

- model/provider/sandbox from persisted Codex rollout: `gpt-5.6-sol` / `openai` / `read-only`;
- session: `019f6322-15a7-7550-a881-b7772397e702`;
- verdict: `ACCEPT`, no required changes;
- final review SHA-256: `10a7c7ebc47ac3eba4c73c8767e144eb600460833a2c20b97e1cee732820cb44`;
- event JSONL SHA-256: `1c7234924e9606b99cfe290a79de91d398d6c6a7442d00a623ac4380ce18b9c8`;
- attested telemetry SHA-256: `c20a094a7ecfb4d97d56ffea230b82d766fa89635e3f585be71c3fad25daeb73`.

Sol rejected two earlier revisions before accepting the final head. The first required exact task ID, an explicitly
present null assignee, blocked status and an actual empty runs list. The second found the dispatcher-visible ready
interval between create and a later block command. The final implementation instead records the sticky block inside
the same pinned-Hermes SQLite transaction as task creation. Its exact-source concurrency regression opens the
dispatcher connection first, observes entry into `_dispatch_once_locked` while creation is paused inside its write
transaction, then proves zero assignment, runs and stub spawns after commit.

The deployment correction received a separate exact-SHA review:

- model/provider/sandbox: `gpt-5.6-sol` / `openai` / `read-only`;
- session: `019f632c-3db5-7960-99d1-30c277733769`;
- verdict: `ACCEPT`, no required changes;
- final review SHA-256: `ae70590f16bc0b12908c3b53623ea8a2cff91d98ce8ce014c2850809179fb9a2`;
- event JSONL SHA-256: `2cb0f072dba28a4a3189aad304ae63ba2a6b3aa78979b561e1fa48abe2b200c5`;
- attested telemetry SHA-256: `b3e6c518b70fbedd24fca559a0bbba1c73c2fb5746baa2c86d4b13b0c6b4d6e0`.

That review first rejected string-only deployment assertions. The accepted regression parses the multi-document YAML
and matches the exact pod-template revision, both staging copies, the full `mission-runtime` Kanban mount tuple and
the exact `emptyDir` volume.

## Verification gates

- Every final PR head passed GitHub `static-checks`.
- `tests/verify-local.ps1 -SkipSmoke` returned `secret-scan-ok`, `iac-static-ok` and `verify-local-ok` after each final
  correction.
- The exact pinned Hermes commit `7c1a029553d87c43ecff8a3821336bc95872213b` passed overlay apply, second-apply
  idempotency, patched fingerprints, image-root staging, bytecode compilation, tamper rejection and the instrumented
  dispatcher/create concurrency regression.
- The adapter tests cover malformed/missing native task identity, assignee, sticky state and runs; all fail closed.
- No review used Claude and no false `Co-Authored-By` trailer was added.

## GitOps rollout and recovered deployment incident

Flux first applied PR #190 at exact revision `97739fe0e92985c639fc8650eb1043a35b3b4014`. The controlled restart failed
closed in the bootstrap init container: the expanded overlay expected `hermes_cli/kanban_db.py`, but the Deployment
still staged only commands, gateway and API files. The error was an exact `FileNotFoundError`; the gateway never
started. No model or worker ran.

PR #191 added the missing upstream copy, patched-result copy and exact `subPath` mount, then bumped the pod template.
Flux applied `master@sha1:7214ad78cc9093f6529fc7e2dedb95eaa0682ec7`. The resulting pod was:

- pod: `hermes-agent-549d46bcc4-d4lqf`;
- UID: `99c56e6f-85d6-4f77-8ad3-b5cd280ffd93`;
- Ready: `true`; restarts: `0`;
- gateway `/health`: HTTP 200;
- dashboard `/api/status`: HTTP 200;
- bootstrap: `overlay applied`;
- mounted `kanban_db.py`: `35375a46c0b2d4a07d7d17fb770c4ac41ad8d72b61b094eb3bc0ad8d0daf9c9b`;
- mounted `uap_missions.py`: `91431815cd1e1583c506e45fe85f846a56df1b7da73ba023e87b7b5ef891539d`;
- mounted `api_server.py`: `0504003cea0d3f5663b17e16a602738ad25ab8dbdd4f7e4b72836286866b4775`.

## Build-1 installation

Build-1 used a detached exact-master worktree at `7214ad78cc9093f6529fc7e2dedb95eaa0682ec7`.

- installed adapter SHA-256: `53af22432f55b4f60475036b00595f1c44050096dff3478814b0305786a5e34e`;
- adapter mode: `0755`;
- pinned upstream Kanban source before overlay: `7ea3133148f82006840fa4883c8ce5e588945e26c1fde3889cb55a48ceec7c64`;
- installed exact patched Kanban source: `35375a46c0b2d4a07d7d17fb770c4ac41ad8d72b61b094eb3bc0ad8d0daf9c9b`.

Only `hermes_cli/kanban_db.py` was installed from the fail-closed transformed detached upstream tree; the unrelated
Central overlay files were not installed into the build-1 Hermes checkout. The intentional tracked modification is
therefore visible in `git status` and must be reproduced by future build-1 installation automation before A7.3.

## Canary chronology

Failed attempts are retained rather than rewritten as success:

1. `a7-blocked-20260715-9909f79-01` exposed that pinned Hermes auto-promoted a parentless non-sticky initial block.
   Adapter execution stopped; no worker/model ran. A manual block with a reason created one synthetic ended run, so
   this attempt was cancelled and task `t_429d8add` archived.
2. `a7-blocked-20260715-7214ad7-02` proved Central had the corrected overlay while build-1 still had upstream
   `kanban_db.py`. The updated adapter failed closed before publication. Diagnostic listing promoted the task; it was
   immediately blocked without a reason, had zero runs, then the mission was cancelled and `t_5ead1cc3` archived.
3. After exact build-1 overlay installation, `a7-blocked-20260715-7214ad7-03` passed from a clean mission and state
   directory without manual intervention inside the handoff.

Accepted canary facts before cleanup:

- routing selector: `build1-uap-a7-blocked-v1`;
- native root: `t_018bdb52`;
- native status/assignee/runs: `blocked` / null / `[]`;
- native events: exactly `created`, `blocked`; no `promoted`, `assigned`, `claimed` or `spawned`;
- Central sequence: `2`;
- Central events: exactly `mission.accepted`, `task.upsert`;
- Central task count: `1`, pointing to `t_018bdb52` with blocked/null projection;
- Central projection ID: `9df63d7fb534855b`;
- repeated exact-profile poll: `null`;
- exact process-name scans for Codex, Ollama and vLLM: empty.

After the evidence was captured, authenticated Central loopback authority completed the mission at sequence `3` with
the bounded result `A7.2 exact-profile blocked handoff verified with one task, zero runs, and no worker or model
launch.` The disposable native task was archived; its history still contains only `created`, `blocked`, `archived` and
zero runs.

Credentials were read from existing Kubernetes Secrets and piped to build-1 through stdin. Values were not printed,
stored in evidence, passed in argv or written into the repository. The build-1 proxy mismatch found during the first
attempt was handled only with a process-local `NO_PROXY` for the tailnet Central address; no global proxy or Tailscale
configuration was changed.

## Proven and not proven

Proven:

- oldest eligible exact-profile intake is not hidden by the latest-100 window;
- one manually invoked bounded poll creates exactly one atomically sticky-blocked, unassigned root;
- one deterministic Central task event is published and a repeated poll does no work;
- no worker/model route is needed for A7.2;
- the reconciled Central runtime starts cleanly with the overlay, while deterministic poll/event retries remain
  idempotent at the single blocked-event boundary.

Not proven and still required before autonomous A7.3 delivery:

- a periodic service/timer and crash-reconciled coordinator;
- recovery from deleted adapter state and partial publication of a future multi-event worker stream;
- concurrent real pollers and atomic native idempotency under concurrent task creation;
- automatic activation, runtime-derived author/reviewer attestation in the live worker, PR/CI/merge/deploy and
  post-verify reconciliation;
- automatic Central terminal completion;
- mission/task/worktree retention and garbage collection;
- full Workspace/Telegram chat, session and owner-answer synchronization;
- hard removal of forbidden local-model/GPU capabilities rather than the current approval policy.

No Qwen, local inference, GPU, Claude, swarm, Spark Runner, destructive test or actual coding-model turn was used by
the A7.2 live canary.
