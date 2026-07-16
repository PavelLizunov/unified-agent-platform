# A7.3 Telegram-Bound Autonomous Canary Evidence

Date: 2026-07-16

UAP runtime revision: `07c47ae8a4f0ff1dc0b70e9b364665e964900fdc`

Target: `PavelLizunov/VPNRouter`

## Verdict

The A7.3 successful-delivery gate passed on a non-toy existing project. The owner supplied the product goal and did
not run commands, select models, inspect the diff, execute tests, operate GitHub or recover either mission. The
profile-bound coordinator performed the repository work, planned recoverable crash, independent review, PR/CI,
merge, fresh-main Windows verification, terminal delivery and disposable cleanup.

The first mission also exposed a pre-existing false-positive Windows regression test. UAP did not ask the owner to
become an operator or silently weaken the gate. It created a second correlated repair mission, diagnosed and fixed the
test through bounded retries, obtained a separate exact-SHA review, merged the repair, passed fresh-main verification,
then resumed and completed the original mission without a second original author turn.

This proves the A7.3 autonomous delivery/recovery path. It does not claim that the remaining full-history
Workspace/Telegram answer loop, durable UI event replay or retention lifecycle are complete.

## Standing authority and exclusions

ADR-031 and the Product Operating Contract supplied standing authority for OpenAI Luna/Sol/Terra routing, reasoning
effort, retries, normal subscription spend, repository tests, PR/CI/merge and fresh-main verification. No per-step
owner approval was used.

The run did not use Claude, Qwen, Ollama, vLLM, local inference, GPU, Spark Runner, a swarm, a new provider, a new
credential or a destructive test. A post-run build-1 process scan was empty for those forbidden runtimes.

## Mission 1: production behaviour change

| Evidence | Value |
|---|---|
| Mission | `a7-vpnrouter-reconnect-20260716-10` |
| Dispatch profile | `build1-vpnrouter-a7-3i` |
| Native Kanban task / run | `t_89f0de48` / `30` |
| Base | `6f7bdc98b1b0f1fe27bd838a0d2e4985adb3aefe` |
| Candidate | `2cd6974416eedc5f1adf1b530bea37294d58e01f` |
| PR | [VPNRouter #44](https://github.com/PavelLizunov/VPNRouter/pull/44) |
| Merge | `58abb6446dabb5ddef37610e9f63994d070e409b` |
| Fresh-main verified SHA | `43649922d489b18665721105ad9aa29cd8768574` |
| Final Central sequence / projection | `22` / `dd7d24b14586cf51` |

The deterministic `durable_state` signal selected the `complex` route under `openai-autonomy-v2`:

- author: runtime-attested `gpt-5.6-sol`, `xhigh`, `workspace-write`, session
  `019f6995-f20d-7c33-89d1-18e0b5b6a846`;
- reviewer: runtime-attested `gpt-5.6-terra`, `xhigh`, `read-only`, separate session
  `019f699e-80f5-7b42-be1f-d167d64183a6`;
- reviewer disposition: `accept` against exact candidate SHA;
- route decision ID: `bda7d5fcf9b7c0255e5d96a4d8648817013e37f7840e1a1af9e80bb09e894ff0`;
- policy SHA-256: `9f5a110961635a501c31d7323b2656be54c15092eca47d3f551a31ce0156cfca`.

The coordinator injected the contracted stop after the author commit became durable. The next timer tick recovered
the same mission, task, run, worktree, candidate and author session. It did not launch another author or create a
second candidate commit.

GitHub recorded
[`test=SUCCESS`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29477202445/job/87552652952),
[`grep=SUCCESS`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29477202547/job/87552653136) and the
repository-defined
[`characterization-windows=SKIPPED`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29477202445/job/87552653887).
The reviewed candidate is an ancestor of PR #44's merge, and that merge is an ancestor of the final default-branch
SHA. Fresh-main Windows post-verify passed at `43649922...`.

## Autonomous repair mission

The first fresh-main post-verify attempts failed in the pre-existing
`VPNRouter.Tests.SingBoxManagerProcessExitLeakTests.DisposedManagers_AreNotRetainedByProcessExitHook`. The same test
also failed on the exact pre-PR baseline, so the production change in PR #44 was not treated as the regression.

UAP created a separate bounded repair mission rather than editing the target manually:

| Evidence | Value |
|---|---|
| Mission | `a7-vpnrouter-test-gc-20260716-11` |
| Dispatch profile | `build1-vpnrouter-a7-3j` |
| Native Kanban task / run | `t_f350fef3` / `31` |
| Base | `58abb6446dabb5ddef37610e9f63994d070e409b` |
| Candidate | `a02b64cc86ba17a0de1902a2abeb0d122bc54655` |
| PR | [VPNRouter #45](https://github.com/PavelLizunov/VPNRouter/pull/45) |
| Merge / fresh-main verified SHA | `43649922d489b18665721105ad9aa29cd8768574` |
| Final Central sequence / projection | `20` / `111a2125cb87c17b` |

The deterministic `concurrency` signal selected Sol/Terra `xhigh`. The final author session was
`019f69d0-dedb-7632-9786-36293465a734`; the independent exact-SHA read-only Terra reviewer session was
`019f69dc-4575-76e3-b16a-d7339af3cf1b` and returned `accept` with no findings. The final change touched only
`VPNRouter.Tests/SingBoxManagerProcessExitLeakTests.cs`; production code was unchanged.

Two author cycles failed their Windows gate. The coordinator durably recorded `needs_fix` and retried without owner
input. The third cycle identified a bounded asynchronous cleanup root unrelated to the ProcessExit subscription and
made the test isolate the intended leak condition. Five independent targeted Windows invocations and the complete
non-visual Windows suite passed before delivery. GitHub then recorded
[`test=SUCCESS`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29481032552/job/87564579906),
[`grep=SUCCESS`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29481034608/job/87564586082) and
[`characterization-windows=SKIPPED`](https://github.com/PavelLizunov/VPNRouter/actions/runs/29481032552/job/87564580569).
The PR merged and fresh-main Windows post-verify passed.

This run exposed one remaining observability defect: author-check feedback persisted only the first bounded failure
line, not the useful diagnostic body. That is follow-up work; it did not prevent autonomous recovery in this canary.

## Mission-plane convergence

Read-only post-run queries compared canonical JSON rather than selected fields:

| Mission | Central SHA-256 | Workspace SHA-256 | Equal | Status |
|---|---|---|---|---|
| original | `16bb16fa55f008c51811f78b46517b28d68180686d8f8f1019d979da88cb8a31` | same | yes | `completed`, sequence `22` |
| repair | `a8457bda3b12b2d313823b64e5e5c02e625a32e7c26eac7e5188cbdd45dfc975` | same | yes | `completed`, sequence `20` |

Each event log contains exactly one terminal `mission.completed`. Both projections report `stage=complete`,
`progress_percent=100`, one task, one worker and result `Delivery completed, merged, and verified`.

The original mission's currently bound Telegram subscription has `last_notified_sequence=22`, exactly equal to the
terminal Central sequence, with no active notification lease. The channel identity is recorded only as SHA-256
`6817cea343fb9df127e4195162230ab25302fdd657f302bba2c2a54c7628458c`; no chat ID or credential is stored here.

During the repair, the single-owner channel was temporarily rebound and its cursor reached repair sequence `20`
before it was deliberately rebound to the original mission. The current subscription row therefore proves the
original terminal delivery, not historical repair binding. No stronger after-the-fact repair-Telegram claim is made.

## Native and delivery evidence

- Native task `t_89f0de48` is `done`, run `30` is `done`, and its event kinds are exactly
  `created, claimed, completed`.
- Native task `t_f350fef3` is `done`, run `31` is `done`, with the same event-kind sequence.
- PR #44 contains candidate `2cd6974...`, is merged as `58abb64...`, and its required checks are green.
- PR #45 contains candidate `a02b64c...`, is merged as `4364992...`, and its required checks are green.
- `origin/main` is exactly `43649922...`; the candidate/merge/default ancestry checks all returned success.
- Both durable delivery states are `phase=complete`; both planned crash flags are persisted.

### Ordered Central event identities

The sanitized read-only Central responses contained these complete ordered logs. Every `build1-flow:*` value is the
stored deterministic `producer_event_id`; `accepted` has no producer ID and `central:auto-complete:v1` is Central's
terminal identity.

```text
original
 1 mission.accepted  central
 2 task.upsert       build1-flow:9dfd3a009da7edf2fe9ca620
 3 mission.stage     build1-flow:d47eea14f17aecf77fec74ea
 4 task.upsert       build1-flow:a3f319401c93fc50b03ba1e3
 5 worker.upsert     build1-flow:58cb3c813a97f26d4973bfa0
 6 mission.stage     build1-flow:91df881b83cfcce3afec8e72
 7 mission.stage     build1-flow:25f30fb9d30ee1c697421254
 8 mission.stage     build1-flow:b7efdd2042c18cc8c24a6eaa
 9 mission.stage     build1-flow:108c7dfb371f9498e64ba3a6
10 task.upsert       build1-flow:847f362278dc7f890262430b
11 worker.upsert     build1-flow:205644dc5ec3302a9753593b
12 change.upsert     build1-flow:d49f5e2e83e3bbe33d1cbc16
13 change.upsert     build1-flow:110db322a3e581761917b441
14 change.upsert     build1-flow:590ea6110f87a13a2434ffc0
15 gate.upsert       build1-flow:c8fea6fef0bce275146dc1dc
16 gate.upsert       build1-flow:c47ed1c3cddee9bb96b0ccaf
17 gate.upsert       build1-flow:2bedef5d0a89a5a6cf80421b
18 gate.upsert       build1-flow:214b85eae6d0ac37066e4e95
19 delivery.upsert   build1-flow:7ef0e0bf88e65fe66419b4a6
20 delivery.upsert   build1-flow:e04f528ed31f4e85f9faf968
21 gate.upsert       build1-flow:8a8f6d6a8b3d70dd60814c8a
22 mission.completed central:auto-complete:v1

repair
 1 mission.accepted  central
 2 task.upsert       build1-flow:9667c99c1292341505d1c301
 3 mission.stage     build1-flow:b526a3939c5cd2bd24da24ee
 4 task.upsert       build1-flow:537f05184d26454ec14a2eb2
 5 worker.upsert     build1-flow:6e871ec13616d00dd0f339f1
 6 mission.stage     build1-flow:cc64eaae5c12829f8f0cdaa0
 7 mission.stage     build1-flow:82a8d01c17cdca3c11f4e6bd
 8 mission.stage     build1-flow:0f0f486b456fe5ac924aa37f
 9 mission.stage     build1-flow:4d94fa998d285e77026ceed2
10 task.upsert       build1-flow:efa5a41ffbcfa2e62142377f
11 worker.upsert     build1-flow:6fa31404108f3bbc05d3dcdd
12 change.upsert     build1-flow:0bde054046c5df7a8f1392b9
13 gate.upsert       build1-flow:5f661220c3b5ed60e128fd1f
14 gate.upsert       build1-flow:aceed99ec84cb448bf458328
15 gate.upsert       build1-flow:703a31731391a239b2d552ba
16 gate.upsert       build1-flow:66a12ec764d57f6a20cb49f2
17 delivery.upsert   build1-flow:2fac950fe2648d29e9973d3b
18 delivery.upsert   build1-flow:ef63f25ed6797ff0e86e4ae6
19 gate.upsert       build1-flow:176ca48bef81c14eb9bc9c40
20 mission.completed central:auto-complete:v1
```

### Persisted test commands

The original author and reviewer independently ran the same Windows gate after an exact preparation plus three
allowlisted file uploads:

```text
/home/uap/bin/windows-brat powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\uap\windows-brat-a7i-test.ps1 a7-vpnrouter-reconnect-20260716-10
```

The repair author and reviewer independently ran the same repair gate after exact preparation plus the one allowlisted
test-file upload:

```text
/home/uap/bin/windows-brat powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\uap\windows-brat-a7j-test.ps1 a7-vpnrouter-test-gc-20260716-11
```

Both missions persisted this successful fresh-main post-verify command at exact default SHA:

```text
/home/uap/bin/windows-brat powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\uap\windows-brat-post-verify.ps1 43649922d489b18665721105ad9aa29cd8768574
```

## Runtime and cleanup evidence

- Flux source and applied Kustomization are Ready at
  `master@sha1:07c47ae8a4f0ff1dc0b70e9b364665e964900fdc`.
- The central Hermes pod is Ready with zero restarts; Central API, dashboard and Workspace returned HTTP 200.
- Mission SQLite uses `journal_mode=delete`; its directory is `0700` and database file is `0600`, so no WAL/SHM
  sidecars existed in the captured state.
- Both disposable coordinator timers are disabled and inactive after terminal completion.
- Author/reviewer worktrees, the diagnostic worktree and disposable local/remote branches are absent. The persistent
  source checkout and bounded durable mission evidence remain intentionally retained.

## Acceptance boundary

| Gate | Result |
|---|---|
| Profile-bound autonomous intake/activation | PASS |
| Deterministic OpenAI-only routing and runtime attestation | PASS |
| Planned crash recovery without duplicate author/candidate | PASS |
| Independent exact-SHA read-only review | PASS |
| PR, required CI, exact-head merge and fresh-main verification | PASS |
| Autonomous diagnosis/repair of a pre-existing gate defect | PASS |
| Native task/run and Central terminal closure | PASS |
| Central/Workspace exact projection equality | PASS |
| Telegram-bound original terminal cursor | PASS |
| Disposable branch/worktree/timer cleanup | PASS |
| Full chat/session/question answer-and-resume synchronization | OPEN |
| Durable UI event replay and complete retention lifecycle | OPEN |

The A7.3 successful-delivery milestone is complete. The full Product Operating Contract remains open only for the
explicit observation and lifecycle/security follow-ups; this evidence must not be used to claim those later gates.
