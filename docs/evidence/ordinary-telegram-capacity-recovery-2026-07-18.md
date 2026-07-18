# Ordinary Telegram capacity-recovery campaign — 2026-07-18

## Scope and verdict

This record covers one ordinary Telegram message routed through the registered
`build1-flow-pilot-registered-v4` profile. The owner sent only the message below; no `/mission`, mission ID, profile,
model, repository path, poll, coordinator command or completion command was supplied:

> Расширь существующий dependency-free Rust mission ledger: добавь read-only команду summary, которая выводит
> количество missions по каждому latest status в лексикографическом порядке. Обнови библиотечный API, CLI, tests и
> README; зависимости не добавляй.

The campaign passed ordinary Telegram intake, a controlled exact pre-turn capacity failure, automatic same-model
recovery, runtime-attested OpenAI author/reviewer execution, independent exact-SHA review, PR/CI/merge, fresh-main
post-verify, explicit no-deploy applicability, cleanup, Central terminal convergence, Telegram delivery and canonical
completion-bundle verification.

This was an adversarial correction campaign, not a clean uninterrupted run on a frozen preinstalled build. The first
review attempt exposed two production gaps and the final Central transition exposed a third. PRs #271–#273 were
merged and installed while the same durable mission was preserved. The final result therefore proves recovery and the
corrected runtime boundaries, but a later clean run remains the strongest possible regression proof.

## Controlled capacity injection

The registered profile used one pre-announced wrapper. Its first invocation atomically created a private marker,
emitted the exact trusted CLI compatibility message and exited before starting Codex; every later invocation delegated
to the installed Codex binary:

```bash
if mkdir /home/uap/.local/state/uap/codex-capacity-canary-20260718.fired 2>/dev/null; then
  printf '%s\n' 'ERROR: Selected model is at capacity. Please try a different model.' >&2
  exit 1
fi
exec /home/uap/.local/bin/codex "$@"
```

The private marker was created at `20:12 UTC`. Central recorded the original run, a later scheduled historical run and
the replacement running/completed run. Sequence 6 at `20:14:23.128Z` was:

```json
{
  "type": "mission.notice",
  "payload": {
    "code": "capacity_recovered",
    "message": "OpenAI capacity recovered; automatic author execution resumed on gpt-5.6-sol.",
    "owner_action_required": false
  }
}
```

The failure did not increment author, review or CI quality counters and did not create an owner question. One
same-model Sol retry recovered, so this campaign did **not** exercise burst exhaustion, `capacity_wait` or whole-route
fallback. The injected compatibility envelope also is not evidence of a naturally occurring provider-capacity error.

## Runtime corrections preserved in history

The campaign found and retained three real defects instead of rewriting them as success:

1. The original reviewer transient unit used both `BindsTo=` and `After=` against the still-activating oneshot parent.
   Parent and child waited on each other. PR #271 removed only the ordering edge while retaining the lifetime binding.
2. Restart then safely quarantined the interrupted reviewer but had no convergence transition. PR #272 added the
   reviewer-only retry after proving the old transient unit was unloaded, the read-only checkout was clean at the exact
   candidate and the draft PR was unchanged. Author ambiguity remains fail-closed.
3. Capacity recovery left one historical `scheduled` worker and one terminal worker. Central incorrectly required
   exactly one worker total, so every delivery gate was green but terminal completion remained blocked. PR #273 now
   accepts zero or more ordered historical `scheduled` workers followed by exactly one successful terminal worker,
   while still rejecting running, failed, malformed or multiple-terminal histories.

Repository identities for those corrections:

| PR | Purpose | Head | Required CI | Merge |
|---|---|---|---|---|
| #271 | remove reviewer parent ordering deadlock | `d033623eb025d7429e5c4aeb04cd89447b51e11a` | `29659665632` | `a360e61a6eb6f1b2567caaae1cb54279f7308e1f` |
| #272 | converge an interrupted read-only review | `8c91de7cfa7185bd645b9f658951fb1649df8725` | `29660284068` | `ea597a9542ed85cf6397cdf2d83f04555baa5b10` |
| #273 | complete after capacity-created historical runs | `39494d962235852f003fae3cf0793e082f9ff535` | `29660825424` | `9cb7546fad6222ba7599ca99913fdd349bc3b271` |

The exact PR #272 coordinator installed on build-1 has SHA-256
`511337191dbe9fd8007ec08e6ea2216b04208c391b9582eb8818b40611250841`. Flux source and the production Kustomization
converged to PR #273 merge `9cb7546fad6222ba7599ca99913fdd349bc3b271`; the replacement Central pod was Ready
with zero restarts and mounted mission runtime SHA-256
`7198fe7c94b0cb973164dee51f7f886325a7ebf21c860acd3150a7d2ac0153fd`.

## Mission and execution identity

```text
mission:             mission-intake-0c72cde02b5ef62972a30bc998f316b9
dispatch profile:    build1-flow-pilot-registered-v4
goal SHA-256:        f61d7f9f119b9bb5a81fb2bde4ac90f95b267a1053153cd53a2b5f1bf3168b3f
root task:           t_dfe1893e
historical run:      41 / scheduled
terminal run:        42 / completed
route:               complex / openai-autonomy-v2
route decision:      8192442f2a83f214ce9c25e61d8041e2737ecd25f5f989a77dd21a8310990e33
quality failures:    author=0, review=0, CI=0
```

The final author was runtime-attested as `gpt-5.6-sol`, `xhigh`, `workspace-write`, session
`019f76dd-ae41-7f33-a30c-b756327ef7e3`. It produced candidate
`255d4e464864f316fc739bf72aa49a750e3e1c5c`, tree `7feb4103e6e3cc7bf822ce3b003347ffa4aacf61`, changing exactly:

```text
README.md
src/lib.rs
src/main.rs
tests/journal.rs
```

The recovered reviewer ran in transient unit `uap-review-4e34190fad46d832ab1d2c03.service`, retained `BindsTo=`
without the parent ordering edge, and exposed only the mission-local model and Codex homes as writable. The unit showed
the intended strict filesystem/home, private-user, private-tmp and hidden-proc properties while active. Runtime
attestation recorded `gpt-5.6-terra`, `xhigh`, `read-only`, distinct session
`019f76fd-40b7-73a2-a46a-32625a2e41ac`. It accepted the exact candidate SHA/tree with source-attestation SHA-256
`105772c6f31cb399e487a70591e7c93f925744868f39692d6cced99018acde50`.

## GitHub delivery and post-verify

Target PR [#8](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/8) was merged from exact head
`255d4e464864f316fc739bf72aa49a750e3e1c5c` into `main`. Required run
[29659412330](https://github.com/PavelLizunov/hermes-flow-v2-pilot/actions/runs/29659412330) was a `pull_request`
run on that exact SHA; Python, Linux, macOS and Windows jobs all passed. The merge/default revision is
`53eca7e419781679d730575f60848b902a8b7de6`.

Fresh-main post-verify passed:

```text
/usr/local/bin/cargo test --all-targets --locked   exit 0
/usr/bin/python3 -m unittest -v                    exit 0
```

The registered target declares `delivery_mode: none`; Central recorded `delivery: not_applicable`. The coordinator
removed both disposable worktrees and the local/remote branch, archived the task and ran Kanban GC.

## Terminal and channel convergence

After PR #273 deployed, the next natural profile-timer tick appended exactly one terminal event:

```text
sequence:             27
event:                mission.completed
occurred_at:          2026-07-18T21:05:03.106Z
result:               Delivery completed, merged, and verified
projection:           completed / complete / 100%
projection_id:        af9b9a328d1a2567
```

The final Workspace projection contains all 27 ordered events and has canonical projection SHA-256
`1966509a1630999aa0692869dd5373431896ce42d744b8055c8b2a45310ce13b`. The Telegram subscription created by ordinary
intake reached `last_notified_sequence=27`; there were zero pending subscriptions and no open owner question. All five
standing delivery timers were active after verification, and no Codex author/reviewer process remained.

## Canonical completion bundle

Build-1 wrote private files with mode `0600`:

```text
/home/uap/swarm-out/mission-80b04dbceab42832e340c52b/completion-evidence.json
/home/uap/swarm-out/mission-80b04dbceab42832e340c52b/delivery-state.json
```

The evidence file's byte SHA-256 is
`bef78e627ba69b32ab191874dcb31185ff037f82a2f037a071a3011f78a226f2`; its canonical semantic digest is
`d05c16b75ade9800d9976b3416e5771b13650529dbe42c3306a22029f67601b6`. The installed independent command returned:

```text
hermes-flow-completion-evidence-ok d05c16b75ade9800d9976b3416e5771b13650529dbe42c3306a22029f67601b6
```

The bundle binds 21 recorded coordinator invocation IDs in chain SHA-256
`b7138627e0ee82fb65c159dcc27990eef941c6766ae8f831b6dbc7a9a8c71780`, the exact profile/policy/coordinator hashes,
mission/task/run, route, candidate/reviewer sessions, PR/CI/merge/default, post-verify, cleanup and terminal projection.

## Accepted and unaccepted claims

Accepted:

> For the exact registered no-deploy pilot, one ordinary Telegram goal survived a controlled exact pre-turn capacity
> failure without owner action, resumed on an approved OpenAI route, completed distinct runtime-attested author and
> OS-isolated exact-SHA reviewer sessions, merged green multi-platform CI, passed fresh-main verification, cleaned up,
> reached one Central terminal event and produced a valid canonical completion bundle.

Not accepted by this campaign:

- a naturally occurring OpenAI/Codex provider-capacity envelope;
- `capacity_wait`, burst exhaustion or whole-route capacity fallback;
- a clean start-to-finish run with PRs #271–#273 already installed before intake;
- a live cross-channel question/answer leg or complete cross-channel transcript synchronization;
- generic/unregistered repository routing;
- deploy/release execution for an applicable target;
- author OS isolation or a platform-wide GPU/non-OpenAI process guard;
- a bundle binding input-channel/source-message identity, channel cursors, timer-origin journal proof or a signed
  GitHub artifact attestation.
