# A7.3 Activation and Delivery Canary Evidence

Date: 2026-07-15

Status: **AUTONOMOUS FAILURE PATH PASS; SUCCESSFUL DELIVERY NOT YET PROVEN**

## Accepted boundary

The owner approved one real-project A7.3 route, explicitly approved a second clean attempt, later approved a third
attempt after the first two candidates exposed platform and target defects, approved a fourth after the cross-process
product rule was made explicit, and explicitly approved a fifth after the runtime/config-path split was defined. All five used:

- target `PavelLizunov/VPNRouter`, issue #39, base
  `c51f619fa98792c1726c1eadc2796f4e067048ba`;
- exactly one native Kanban root and one run, with no swarm;
- author `gpt-5.6-luna` and separate exact-SHA read-only reviewer `gpt-5.6-sol`;
- at most two author/review cycles per mission;
- exactly three allowlisted target files for attempts 1-3, four for attempt 4 and five for attempt 5;
- the Windows test VM through `windows-brat`, never the owner's Windows computer;
- one approved crash after a durable author commit and before Central acknowledgement;
- PR/CI/merge/post-verify authority only after an accepted review;
- no Claude, Qwen, Ollama, vLLM, local inference, GPU, Spark Runner, tag, release or destructive test.

The owner did not run commands or repair any attempt. The quality gate stopped all five candidates before a target
PR was opened.

## Landed UAP foundation and corrections

| Change | Reviewed head | Merge | Result |
|---|---|---|---|
| [#199](https://github.com/PavelLizunov/unified-agent-platform/pull/199) recoverable delivery coordinator | `ebad7cc53730f98350f6b321abb5e0fb3949147d` | `62021fcc3bd2186025fae2f470323ce216bda837` | One profile-bound timer route, durable phases, author/reviewer, PR/CI/merge/post-verify and cleanup transitions |
| [#200](https://github.com/PavelLizunov/unified-agent-platform/pull/200) direct Central client | `b7a4abf1d16f98c43f8d0ba72f0a67bcb22256a5` | `2f86498aba41b271b97afcaa8e4c4640c4cf1d8b` | Central credentials bypass ambient proxies |
| [#201](https://github.com/PavelLizunov/unified-agent-platform/pull/201) pinned active status | `2205f96e1c37f2fecd80f99b67c3a1ad7068ba63` | `c9348465da96b89b02fd16bd96ce9b7f3f94e3f9` | Adapter uses pinned Hermes `running` create status |
| [#202](https://github.com/PavelLizunov/unified-agent-platform/pull/202) public lease proof | `96d390091d005cae001191f298fcbb1216424d60` | `73bb2f3782690e7007d7adfe5f8bdf3998e69973` | Claim proof is bound to exact task/run, lock and unexpired public event payload |
| [#203](https://github.com/PavelLizunov/unified-agent-platform/pull/203) exhausted-review checkpoint | `68138dadb6be7118feb95d779042854bd423681d` | `4b1f39ccea857c0a5f8d8912c2c9094e3778a411` | Final rejection is durable and later ticks cannot invoke another model |
| [#205](https://github.com/PavelLizunov/unified-agent-platform/pull/205) autonomous rejection closure | `d17d0a47ec4efb2fc1681b80d90c1999ee7ac110` | `461795c70e426f546489d38059e67d9c4472a81a` | Rejected runs clean up, durably complete the native task and let Central append `mission.failed` |
| [#206](https://github.com/PavelLizunov/unified-agent-platform/pull/206) rejection rollout | `54c1698845d1de394c24ce7e45fddefa3cc047a6` | `a012bfe27052d5462d0cc9bd021ed58836a92ff7` | Config revision `v26-a7-3-rejection` mounted the failure policy in the live pod |
| [#207](https://github.com/PavelLizunov/unified-agent-platform/pull/207) author-check retry | `46af67e0887746ebaa9cddb70ce490d0f24b8309` | `7964b9a76078655a01bbba0317454134ad674d2a` | A failed pre-commit gate becomes one bounded repair cycle; exact candidate content is fingerprinted and exhaustion terminates safely |
| [#208](https://github.com/PavelLizunov/unified-agent-platform/pull/208) author-check rollout | `bad5ef9c59bf97e741305c82cb020e3d8fa335c6` | `7ef3eff619617c71e8b3a3e332e653b8fc2c6b19` | Config revision `v27-a7-3-author-checks` rolled the live Central failure policy |
| [#209](https://github.com/PavelLizunov/unified-agent-platform/pull/209) first-tick timer arming | `6c7ccbc402c30aaebd716fb854454fc82850e7cb` | `da3ec15526c60b9c76a33b0234178f17f2b80e28` | `OnActiveSec` arms a newly enabled timer independently of the old user-manager boot time |

Every PR passed required `static-checks`. The #207 correction passed the full local gate with `secret-scan-ok`,
`iac-static-ok` and `verify-local-ok`, 20 Windows/Linux coordinator tests and the mission-runtime checks. After two
review rounds found and closed candidate-mutation gaps, exact head `46af67e...` received a runtime-attested read-only
Sol `accept` with no findings in session `019f65ec-f81d-7242-a81b-33d12128a1f4`. The installed build-1 coordinator
matched its merged-master source SHA-256 `0fe747daac5acbb3f69b9202e77a98fefe0324b450b0d07cbe1705debb31efb1`.
The two-line #209 timer correction also passed the full gate and an exact-SHA read-only Sol review.

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

## Attempt 3 — autonomous recovery and rejection closure

| Identity | Value |
|---|---|
| Mission | `a7-vpnrouter-issue39-20260715-03` |
| Root / run | `t_e9157d97` / `23` |
| Final candidate | `28ed7ad5663c8b774c03b5927f8c047d8234e45e` |
| Luna sessions | `019f65d3-48a3-72f2-a5cb-7b75d6da10ab`, `019f65f8-af93-7213-a0da-e6f095d344b5` |
| Sol session | `019f65fb-5a8e-7df3-86b6-4a3003b4e485` |
| Final state SHA-256 | `9d0173dc19d86327bb7bde80b74c5f4bb6a442f53c733ab28674756b0b97478c` |

The first Luna turn changed exactly the three approved files but the authoritative Windows gate found two C# compiler
errors before commit. The old coordinator left `phase=claimed` with a dirty worktree and refused a second model. The
timer was disabled; no target file was manually repaired. PRs #207/#208 added and rolled out a content-fingerprinted,
bounded author-check checkpoint. On resumption, one recovery tick reran the gate and persisted `needs_fix`, cycle 2,
without a model. The next timer tick invoked exactly one Luna repair turn, passed all Windows author checks and created
candidate `28ed7ad...`. The approved post-commit crash then fired; the following tick recovered the same SHA and did
not repeat Luna.

The separate read-only Sol review reran the Windows gate successfully but rejected the candidate with one P1: CLI
status runs in another process, while the deep-verification suppression signal is process-local, so a temporary probe
can be mistaken for a TUN-owning external runtime. No target PR was opened.

Unlike attempts 1 and 2, rejection closure was fully autonomous. The coordinator removed author/review worktrees and
the local branch, completed native task `t_e9157d97`, published the terminal task/worker/gates and Central appended
`mission.failed`. The final Central projection is sequence `12`, status `failed`, one `done` task, one `completed`
worker and exact gates `tests=passed`, `review=failed`, `cleanup=passed`. Target branch/PR lookup is empty and no model
process remains. The final timer was disabled/inactive.

One bootstrap defect was observed: the installed timer still used `OnBootSec`, so enabling it long after the user
manager boot produced `active (elapsed)` with no next trigger; Codex started the first recovery service tick once.
PR #209 replaced that condition with `OnActiveSec=1min`. Live post-install verification then showed a future first
trigger immediately after `enable --now`; the timer was disabled before that verification trigger fired.

## Attempt 4 — cross-process rule pinned; custom-path liveness still rejected

| Identity | Value |
|---|---|
| Mission | `a7-vpnrouter-issue39-20260715-04` |
| Root / run | `t_8ca3b0bf` / `24` |
| First candidate | `6effd671bfb5ba38651c26bd2f86e1fa86363de9` |
| Final candidate | `bed49e9f24813bb286aa26a2ed92f4a111371377` |
| Luna sessions | `019f6634-e21e-7eb3-a746-3fc3075774b4`, `019f663b-8fbd-7c40-8dd6-b1529910a945` |
| Sol sessions | `019f6638-ede3-7db1-9bb4-20a057ce674d`, `019f663e-3c7a-7672-aace-020e59e345a5` |
| Final state SHA-256 | `dec6b1aa23a7042a9dadd84bcfd2d92d8f14d4f71c64de6783c91e53c6315f59` |

The fourth contract made the missing product behavior explicit: a process-owned `sing-box` is an external running
tunnel only while the existing system-wide TUN ownership lock is also held. A deep-verification probe in another
process holds no TUN lock and must remain non-running. No new IPC, service, cache or dependency was permitted. The
candidate changed exactly the two production files plus the two existing regression suites in the four-file allowlist.

Both author cycles and both independent reviewer checkpoints passed the authoritative Windows VM gate. After the
first candidate committed, the approved crash fired before Central acknowledgement; the next tick reused exact SHA
`6effd67...` without a duplicate Luna turn. Sol cycle 1 found that a missing, unreadable or malformed YAML poll could
clear the custom executable path already registered by the running manager. Luna cycle 2 preserved that path on read
failure. Sol cycle 2 then found the remaining valid-rewrite case: config path A can be replaced by valid path B while
the live tunnel still runs A, and overwriting the registered path makes the healthy tunnel appear stopped. This needs
separate runtime-registered and config-derived ownership candidates, not another process-local probe signal.

The two-cycle limit terminated fail-closed. No target branch or PR was pushed. The coordinator removed both disposable
worktrees and the local branch, completed task `t_8ca3b0bf`/run `24` with result `review_rejected`, and Central reached
sequence `12`, projection `71ca91d0119aba2e`, status `failed`, one `done` task, one `completed` worker and exact gates
`tests=passed`, `review=failed`, `cleanup=passed`. The timer is disabled/inactive, no Codex, local-model, swarm or Spark
process remains, and no GPU route was configured or invoked.

Before mission creation, one shell `curl` reached the tailnet URL through the build-1 ambient HTTP proxy and returned
`502`. Direct health was `200`; an existence check showed no committed mission, then a single `--noproxy` POST created
and verified the mission. The installed coordinator's direct Central transport was unaffected.

## Attempt 5 — runtime/config split passed; fail-open lock semantics rejected

| Identity | Value |
|---|---|
| Mission | `a7-vpnrouter-issue39-20260715-05` |
| Root / run | `t_2bfdf8e2` / `25` |
| Final candidate | `97cd9df93b4cb7ef2eb30f9e48429f0c8a9b5a00` |
| Luna sessions | `019f6658-5f74-7621-9c4f-1bc051a8f8bc`, `019f665c-0dbe-7632-a88a-4903147bb8a9` |
| Sol session | `019f665e-c0a9-7b82-a37c-9a68f27912fd` |
| Final state SHA-256 | `304bacfc28e8a14726ac042519e873c44675fdc6206a0f971fcaaa6997b0b8eb` |

The fifth contract preserved `ProcessOwnership.ConfiguredExePath` as the actual executable registered by the running
manager and passed a freshly read config path as a separate ownership candidate. Missing or malformed YAML contributed
no candidate and could not erase the registered path; a valid A-to-B rewrite left the live path A intact. The allowlist
contained exactly the CLI status command, runtime detector, process ownership helper and two existing regression suites.
No cache, IPC, service, dependency, release or unrelated target file was allowed.

The first Luna turn produced the five-file change, but the Windows gate rejected it before commit because an overloaded
ownership method made an existing method-group caller fail compilation. The coordinator persisted `needs_fix` and
started exactly one bounded Luna repair. The second turn restored the one-argument compatibility seam, passed every
author Windows command and committed exact candidate `97cd9df...`. The approved crash then fired before Central ACK;
the next timer tick recovered that exact task, run and SHA without a third Luna turn. The exact-SHA read-only Sol
checkpoint reran the Windows gate successfully.

Sol rejected the candidate for one distinct P1. `TunOwnershipLock.TryAcquire()` intentionally returns success when
semaphore creation or `WaitOne` throws, allowing the tunnel to continue without owning the semaphore. The candidate
made `TunOwnershipLock.IsOwnedByAnyone()` a mandatory second signal and would therefore report that supported
fail-open tunnel as stopped. Its new assertions only pinned source shape and did not behaviorally cover the unavailable
lock state. A correct next contract needs an observable tri-state lock result or another minimal way to preserve the
existing fail-open behavior without reopening the normal cross-process probe false positive.

The two-cycle limit terminated fail-closed. No target branch or PR was pushed. The coordinator removed both worktrees
and the local branch, completed task `t_2bfdf8e2`/run `25` with result `review_rejected`, and Central reached
sequence `12`, status `failed`, one `done` task, one `completed` worker and exact gates `tests=passed`,
`review=failed`, `cleanup=passed`. VPNRouter issue #39 remains open and target `main` remains `c51f619...`.
The timer is disabled/inactive and no Codex, local-model, GPU, swarm or Spark process remains.

Before mission creation, the first helper used the wrong bearer variable name and failed before any POST. The timer
briefly ran one empty poll and returned `null`; it was disabled before the helper was corrected. A single verified
POST then created the mission. No task, worker or model existed before that successful creation.

## Failure recovery and cleanup

The original coordinator saved the final review files but raised before updating `delivery-state.json`. Because the
timer remained enabled, another tick could invoke Sol again and violate the two-cycle ceiling. The timer was disabled
before a third review began. PR #203 now checkpoints `phase=review_rejected`, final verification, telemetry and findings
before returning. Its regression proves that a later tick does not call the reviewer or mutate a worktree, including
when Central already reports `failed`.

Post-install verification repaired attempt 2's historical state from the exact saved review artifacts, then invoked
the installed systemd coordinator once with the timer disabled. It returned success from `review_rejected`, launched
no model and recreated no worktree.

Historical attempts 1 and 2 were terminated as `failed` by authenticated loopback authority, their native tasks were
archived and active runs reclaimed. Their timers are disabled/inactive, disposable worktrees and local branches are
absent, and target PR lookup is empty. Their Central projections are sequence `7`, status `failed`, stage `testing`,
progress `50%`; projection IDs are `825d56543d2fb5d0` and `9232b99540b6e45f`.

Those historical gaps are closed for attempts 3-5. Two observation limitations remain: Central exposes only the generic
error `Independent review rejected the candidate`, not the actionable Sol finding, and the failed projection retains
stage `testing` at `50%` with an empty terminal list. Telegram delivery of this terminal update was not independently
verified.

## Proven and not proven

Proven:

- exact-profile periodic intake can create and claim one real Kanban task/run;
- Luna author turns, Windows VM checks and separate Sol exact-SHA reviews are machine-bound to runtime model and
  sandbox identity;
- the approved post-commit crash recovers the same author checkpoint without a duplicate turn;
- the review gate prevents PR creation for a green-tested but incorrect candidate;
- final review exhaustion no longer causes unbounded model retries after PR #203;
- a pre-commit test failure resumes through exactly one bounded author repair without manual state or target edits;
- review rejection autonomously closes native and Central state and removes branch/worktrees without another model;
- a newly enabled timer is now scheduled from activation rather than a historical boot;
- the owner did not become a command, test or cleanup operator;
- the runtime-registered and config-derived executable paths can remain separate, while Sol stopped a distinct
  fail-open lock-liveness defect.

Not proven:

- one successful real-project mission reaching PR, required CI, merge and fresh-main post-verify;
- detailed review-finding projection and Workspace/Telegram terminal consistency for a rejected delivery;
- CI-failure repair, merge conflict recovery, deploy/rollback, retention, soak or HA;
- authority for another live author/reviewer mission. The approved fifth attempt is exhausted.

## Gate

| Gate | Result |
|---|---|
| A7.3 coordinator foundation | **PASS, installed** |
| Crash/restart checkpoint | **PASS** |
| Runtime model/sandbox attestation | **PASS** |
| Independent quality rejection | **PASS (fail-closed)** |
| Autonomous failure closure and cleanup | **PASS** |
| Newly enabled timer self-arms | **PASS after #209** |
| Successful target delivery | **FAIL / NOT DEMONSTRATED** |
| A7.3 Product Operating Contract milestone | **NOT COMPLETE** |

Before another live canary, obtain fresh owner approval for its model turns and revise the target contract around the
remaining lock-liveness rule: preserve the existing fail-open startup behavior when semaphore observation is
unavailable, while still requiring the lock in the normal observable path so a cross-process deep-verification probe
cannot masquerade as a tunnel. The smallest likely seam is a tri-state ownership probe in the existing lock class,
with a behavioral regression for the unavailable state. A successful PR/CI/merge/fresh-main post-verify route remains
the A7.3 completion gate. Separately, project the actionable review finding and a terminal stage/progress into Central
and verify Telegram delivery; neither requires claiming that the success path is complete.
