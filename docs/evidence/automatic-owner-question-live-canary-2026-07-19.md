# Automatic owner-question live canary — 2026-07-19

## Verdict

PASS for the narrow deployed `architecture_change` owner gate and the complete registered no-deploy delivery path.

An ordinary Telegram goal created one Central mission on the already armed profile. The first natural build-1 timer
tick created one inert sticky-blocked root and one deterministic owner question before any model turn. Telegram's
unrelated `/approve` command did not authorize the mission. A later ordinary message containing exact `APPROVE`
became the durable source-linked answer, resumed the same root, and the standing timer completed authoring, tests,
independent review, PR, CI, exact merge, fresh-main post-verify, terminal commit and cleanup without manual
`accept`, `bind`, `poll`, `tick`, coordinator, completion or publication calls.

This run proves the ordinary Telegram answer path. It does not prove a Telegram-origin question answered through
Workspace, complete cross-channel chat history, deploy/release, a quality repair, or a capacity fallback.

## Installed revisions

| Change | Pull request | Merge |
|---|---|---|
| automatic owner-question producer | [#281](https://github.com/PavelLizunov/unified-agent-platform/pull/281) | `27744b065a8abb79f43bd8dcdb5b428300d0b14c` |
| Central runtime rollout | [#282](https://github.com/PavelLizunov/unified-agent-platform/pull/282) | `2970397549355db79455e9ba1e60bcd00a3ccd65` |
| pre-armed owner-gate profile and Telegram route | [#283](https://github.com/PavelLizunov/unified-agent-platform/pull/283) | `80e1a07bf4d9671df6ef1ffa9d56cf8df589f6e0` |

Flux GitRepository and Kustomization both reported `master@sha1:80e1a07bf4d9671df6ef1ffa9d56cf8df589f6e0`.
The Ready Central pod used revision `v52-owner-gate-canary-route`, and its process environment mapped Telegram to
`build1-flow-pilot-owner-gate-v4` while Workspace remained on `build1-flow-pilot-registered-v4`.

| Installed artifact | SHA-256 |
|---|---|
| Central `uap_missions.py` | `4ad2f9713349d376a1c783eb73e9b6c90a2811572e640f589b5df983ef783776` |
| build-1 `delivery_coordinator.py` | `bd7f2fbb9fecf134963c0590e66d75bc070e161288cd76995695647936a085eb` |
| owner-gate profile | `0023a0fde1a1c730e885246fd4cf4f87b6bf6d99585da48ca809d864ba48e491` |
| `openai-autonomy-v2` policy | `9f5a110961635a501c31d7323b2656be54c15092eca47d3f551a31ce0156cfca` |

The sixth `hermes-delivery-coordinator@flow-pilot-owner-gate-v4.timer` was `active` and `enabled` before the owner
message. Its pre-canary natural tick returned `null`.

## Owner interaction and Central lineage

The owner sent one ordinary Telegram goal at `2026-07-19T04:45:26Z`:

> Расширь существующий dependency-free Rust mission ledger: добавь read-only команду history &lt;mission-id&gt;,
> которая выводит все committed статусы этой mission в порядке записи. Добавь библиотечный API, CLI, tests и README;
> сохрани текущую семантику torn tail и malformed committed data; зависимости не добавляй.

| Identity | Value |
|---|---|
| mission | `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` |
| profile | `build1-flow-pilot-owner-gate-v4` |
| root task | `t_bbb75a0c` |
| run | `43` |
| question | `owner-gate:2424d13134d3107b9ebb2cf0` |
| terminal projection | `41f596fa6a59e3d7` |

The ordered Central log contains exactly 27 events:

```text
1   mission.accepted     input_platform=telegram
2   task.upsert          t_bbb75a0c blocked, assignee=null
3   mission.question     exact APPROVE required
4   mission.answer       APPROVE
5   task.upsert          same t_bbb75a0c ready, assigned
6-12                    implementing -> testing -> reviewing -> delivering -> verifying
13-26                   task/worker complete, four changes, five gates, three deliveries
27  mission.completed    one concrete terminal result
```

The wrong `/approve` command produced no mission authorization event. Exact `APPROVE` was stored once, and the
completed evidence binds its SHA-256 without persisting raw channel identity. The final Workspace payload had cursor
`27`, projection SHA-256 `16dc44fc507f36d9d83c8d0c4d5c5b626be9ded6d40c12497b85c66b15d58ae5`, and the Telegram subscription reached
`last_notified_sequence=27` with zero pending notifications.

## Delivery proof

| Fact | Value |
|---|---|
| base | `53eca7e419781679d730575f60848b902a8b7de6` |
| candidate/reviewed head | `be127e9a17decac7015b805fa531a4ed005d58a6` |
| candidate tree | `fabbee2c4e53d3866d74e4f55c7b702aad6b9289` |
| target PR | [#9](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/9) |
| merge/default | `c24aed910e36a7bcded4da270b50c11503a38613` |
| CI run | `29674119223` |
| changed files | `README.md`, `src/lib.rs`, `src/main.rs`, `tests/journal.rs` |

`test-linux`, `test-windows`, `test-macos` and `test-python` all completed successfully for the exact candidate.
Git independently confirmed that the candidate is an ancestor of the merge, the merge is an ancestor of current
`origin/main`, and the cumulative diff contains only the four recorded paths.

The runtime-derived actors were:

| Role | Model | Effort | Sandbox | Session |
|---|---|---|---|---|
| author | `gpt-5.6-sol` | `xhigh` | `workspace-write` | `019f78b9-cde7-76f0-b333-3a8e57171468` |
| reviewer | `gpt-5.6-terra` | `xhigh` | `read-only` | `019f78be-34dc-7ee3-8f02-226c99affc53` |

Both actors bind route decision `8192442f2a83f214ce9c25e61d8041e2737ecd25f5f989a77dd21a8310990e33`; the reviewer accepted the exact candidate
with no findings. The registered target declares `delivery_mode: none`, so Central recorded explicit
`delivery: not_applicable` rather than implying a deployment.

Cleanup removed both disposable worktrees, the local and remote branch, archived the task and ran Kanban GC. No Codex
actor remained after completion.

## Completion evidence v2

Build-1 wrote owner-only mode-`0600` files:

```text
/home/uap/swarm-out/mission-43da330a1a4698d3fb72f138/completion-evidence.json
/home/uap/swarm-out/mission-43da330a1a4698d3fb72f138/delivery-state.json
```

| Evidence identity | Value |
|---|---|
| schema | `2` |
| byte SHA-256 | `c4fd409e7f17d40f9d7fee326780581e11d0d0f47c2252f81d5e984995891026` |
| semantic SHA-256 | `4dbb3b926e1b987ef7a168e176dde9ef172ea7cfde9e1fa03284935663adaad4` |
| systemd invocation count | `5` |
| invocation chain SHA-256 | `c1eb28446d88f51e33a1c26ba53eddc4e51c0f14a4f30650789f95d5486153df` |

Every recorded invocation names `hermes-delivery-coordinator@flow-pilot-owner-gate-v4.service`. The installed verifier
returned:

```text
hermes-flow-completion-evidence-ok 4dbb3b926e1b987ef7a168e176dde9ef172ea7cfde9e1fa03284935663adaad4
```

This is the first live schema-v2 artifact. It binds the server-owned Telegram origin and hashed source key/message,
the owner-answer hash, systemd invocation chain, exact route/runtime actors, Git/PR/CI lineage, post-verify, cleanup
and concrete Central terminal projection.

## Accepted and unaccepted claims

Accepted:

> On the exact registered no-deploy pilot, one ordinary Telegram architecture mission automatically stopped before
> model execution, accepted only exact owner approval, resumed the same root, and completed OpenAI-only delivery,
> independent exact-SHA review, PR/CI/merge, fresh-main verification, terminal publication and cleanup without a
> human operator.

Not accepted by this run:

- a Telegram-origin question answered through Workspace;
- complete Workspace/Telegram chat transcript synchronization;
- automatic inference of `architecture_change` from arbitrary goal text (the approved profile supplies the flag);
- deploy/release or deployed-revision verification;
- a review/CI repair, capacity exhaustion or whole-route fallback;
- arbitrary repository/profile creation, HA or signed external attestation.
