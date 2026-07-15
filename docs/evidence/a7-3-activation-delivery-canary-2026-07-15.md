# A7.3 Activation and Delivery Canary Evidence

Date: 2026-07-15

Status: **FAILED AT INDEPENDENT REVIEW; A7.3 IS NOT COMPLETE**

## Accepted boundary

The owner approved one real-project A7.3 route, then explicitly approved one second clean attempt after the first
candidate failed review. Both used:

- target `PavelLizunov/VPNRouter`, issue #39, base
  `c51f619fa98792c1726c1eadc2796f4e067048ba`;
- exactly one native Kanban root and one run, with no swarm;
- author `gpt-5.6-luna` and separate exact-SHA read-only reviewer `gpt-5.6-sol`;
- at most two author/review cycles per mission;
- exactly three allowlisted target files;
- the Windows test VM through `windows-brat`, never the owner's Windows computer;
- one approved crash after a durable author commit and before Central acknowledgement;
- PR/CI/merge/post-verify authority only after an accepted review;
- no Claude, Qwen, Ollama, vLLM, local inference, GPU, Spark Runner, tag, release or destructive test.

The owner did not run commands or repair either attempt. The quality gate stopped both candidates before a target PR
was opened.

## Landed UAP foundation and corrections

| Change | Reviewed head | Merge | Result |
|---|---|---|---|
| [#199](https://github.com/PavelLizunov/unified-agent-platform/pull/199) recoverable delivery coordinator | `ebad7cc53730f98350f6b321abb5e0fb3949147d` | `62021fcc3bd2186025fae2f470323ce216bda837` | One profile-bound timer route, durable phases, author/reviewer, PR/CI/merge/post-verify and cleanup transitions |
| [#200](https://github.com/PavelLizunov/unified-agent-platform/pull/200) direct Central client | `b7a4abf1d16f98c43f8d0ba72f0a67bcb22256a5` | `2f86498aba41b271b97afcaa8e4c4640c4cf1d8b` | Central credentials bypass ambient proxies |
| [#201](https://github.com/PavelLizunov/unified-agent-platform/pull/201) pinned active status | `2205f96e1c37f2fecd80f99b67c3a1ad7068ba63` | `c9348465da96b89b02fd16bd96ce9b7f3f94e3f9` | Adapter uses pinned Hermes `running` create status |
| [#202](https://github.com/PavelLizunov/unified-agent-platform/pull/202) public lease proof | `96d390091d005cae001191f298fcbb1216424d60` | `73bb2f3782690e7007d7adfe5f8bdf3998e69973` | Claim proof is bound to exact task/run, lock and unexpired public event payload |
| [#203](https://github.com/PavelLizunov/unified-agent-platform/pull/203) exhausted-review checkpoint | `68138dadb6be7118feb95d779042854bd423681d` | `4b1f39ccea857c0a5f8d8912c2c9094e3778a411` | Final rejection is durable and later ticks cannot invoke another model |

Every PR passed required `static-checks`. The final #203 head also passed the full local gate with
`secret-scan-ok`, `iac-static-ok` and `verify-local-ok`. Its separate runtime-attested Sol review used session
`019f65a6-2305-7310-936d-0c8083388dbd`, exact model `gpt-5.6-sol`, read-only sandbox and returned `accept` with no
findings. The installed build-1 coordinator matched the accepted source SHA-256
`d8abf8488689eadf576772a2ccaae0316e9d05817b5aa70b69cad79b91faab8f`.

## Attempt 1 — rejected

| Identity | Value |
|---|---|
| Mission | `a7-vpnrouter-issue39-20260715-01` |
| Root / run | `t_cc8f0c4c` / `21` |
| First candidate | `f63e2a3d58651dbb134b55baea885301a1aa74d5` |
| Final candidate | `460c16a1f609d550dc418519e49e9e44966fb74e` |
| Luna sessions | `019f6572-6405-7830-96a3-9d1173093ba7`, `019f6577-276e-7ba2-945b-06ef56818313` |
| Sol sessions | `019f6575-79a5-7de1-80ae-1cbae2fc5c5b`, `019f657f-e6c0-7c73-bf25-a29cb45c6c4d` |

The approved crash occurred after the first durable author commit. The next timer tick reused the same mission,
task, run, worktree and commit and did not launch a duplicate first author turn. Windows author and reviewer gates
passed before each review.

Sol rejected cycle 1 because a fresh process did not rehydrate a configured custom executable path and the test did
not behaviorally pin the null-state decision. Cycle 2 fixed those points but introduced two P1 defects: status polling
called side-effectful `SettingsLoader.Load()`, and the rehydration path was Windows-only. The coordinator stopped before
push. No target PR exists.

## Attempt 2 — clean retry, also rejected

| Identity | Value |
|---|---|
| Mission | `a7-vpnrouter-issue39-20260715-02` |
| Root / run | `t_47f5689a` / `22` |
| First candidate | `a15e596b0c42ff060e4fb78ee7f2a72d647082c4` |
| Final candidate | `9714da63b0c7d3d9a68b74838093ad407be52c80` |
| Luna sessions | `019f658b-721f-7e10-b08e-d7ad16bde9d3`, `019f6590-1751-7fa0-82fe-2cf3cf9f3ce3` |
| Sol sessions | `019f658d-f243-77f2-b59a-21b47cd18719`, `019f6593-5130-7dd0-9151-61782e837ba9` |

The refined contract required a cross-platform, direct read-only configuration path, no `SettingsLoader.Load/Save`,
no configuration creation/migration/backup/replacement, fail-closed malformed input and only the existing YamlDotNet
dependency. Both author candidates changed exactly the three allowlisted files. All authoritative Windows commands in
the author and review checkpoints exited zero.

At `2026-07-15T11:33:45Z` the approved crash fired after candidate `a15e596...` was committed but before Central ACK.
The next systemd tick recovered the same task `t_47f5689a`, run `22` and commit without another cycle-1 Luna session.

Sol cycle 1 found stale/dead CLI state precedence and cache invalidation after a same-path configuration rewrite.
Cycle 2 found that file length plus `LastWriteTimeUtc` can miss an equal-length rewrite with a preserved timestamp.
That candidate therefore remained incorrect despite green focused tests. Review rejected it, so the coordinator did
not push, open a PR, wait for CI, merge or post-verify the target.

The rejected candidate is retained as a 5,814-byte prerequisite bundle at build-1 under the mission evidence
directory. Its SHA-256 is `b3d0a3be08a617e760635d8ac8c27763430ddaed7c995ab5a23e75a1d6819721`; it requires base `c51f619...`.

## Failure recovery and cleanup

The original coordinator saved the final review files but raised before updating `delivery-state.json`. Because the
timer remained enabled, another tick could invoke Sol again and violate the two-cycle ceiling. The timer was disabled
before a third review began. PR #203 now checkpoints `phase=review_rejected`, final verification, telemetry and findings
before returning. Its regression proves that a later tick does not call the reviewer or mutate a worktree, including
when Central already reports `failed`.

Post-install verification repaired attempt 2's historical state from the exact saved review artifacts, then invoked
the installed systemd coordinator once with the timer disabled. It returned success from `review_rejected`, launched
no model and recreated no worktree.

Both Central missions were terminated as `failed` by authenticated loopback authority. Both native tasks were
archived and their active runs reclaimed. Both timers are disabled/inactive, disposable worktrees and local branches
are absent, and target PR lookup is empty. The current Central projections are sequence `7`, status `failed`, stage
`testing`, progress `50%`; projection IDs are `825d56543d2fb5d0` and `9232b99540b6e45f`.

One failure-path gap remains visible: Central's embedded task projections still say `running` although the native
tasks are archived. The rejection path does not yet publish a final rejected gate/task snapshot, close the Central
mission locally, or perform evidence-driven cleanup by itself. Manual cleanup was performed by Codex, not the owner,
but this is not the Product Operating Contract's autonomous terminal path.

## Proven and not proven

Proven:

- exact-profile periodic intake can create and claim one real Kanban task/run;
- Luna author turns, Windows VM checks and separate Sol exact-SHA reviews are machine-bound to runtime model and
  sandbox identity;
- the approved post-commit crash recovers the same author checkpoint without a duplicate turn;
- the review gate prevents PR creation for a green-tested but incorrect candidate;
- final review exhaustion no longer causes unbounded model retries after PR #203;
- the owner did not become a command, test or cleanup operator.

Not proven:

- one successful real-project mission reaching PR, required CI, merge and fresh-main post-verify;
- autonomous rejected-run closure, Central failure, projection reconciliation and cleanup;
- Workspace/Telegram terminal consistency for a rejected delivery;
- CI-failure repair, merge conflict recovery, deploy/rollback, retention, soak or HA;
- authority for another live author/reviewer mission. The two approved attempts are exhausted.

## Gate

| Gate | Result |
|---|---|
| A7.3 coordinator foundation | **PASS, installed** |
| Crash/restart checkpoint | **PASS** |
| Runtime model/sandbox attestation | **PASS** |
| Independent quality rejection | **PASS (fail-closed)** |
| Successful target delivery | **FAIL / NOT DEMONSTRATED** |
| A7.3 Product Operating Contract milestone | **NOT COMPLETE** |

Before another live canary, add a bounded failure terminal path that durably records review rejection, reconciles the
native and Central task states, notifies the owner and cleans up without another model call. A new canary then needs a
fresh owner approval for its model turns. The target contract must also pin content-sensitive cache invalidation,
including an equal-length rewrite with preserved metadata.
