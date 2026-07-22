# Routine docs routing live canary — 2026-07-23

## Verdict

The bounded `routine_docs` route introduced by UAP PR
[#414](https://github.com/PavelLizunov/unified-agent-platform/pull/414) passed one autonomous live delivery canary.
An explicit README-only owner goal was classified before dispatch, taken by the standing systemd timer, authored by
runtime-attested `gpt-5.6-luna` at `medium`, independently reviewed by runtime-attested `gpt-5.6-sol` at `low`, and
completed through the existing tests, required CI, exact-head merge, post-verify and cleanup gates.

This proves the narrow deterministic route. It does not prove a general semantic task estimator, a Spark production
route, reduced target-repository CI, or a separate QA actor.

## Installed implementation

| Item | Exact value |
|---|---|
| UAP implementation PR | `#414` |
| UAP merge | `4ebe80d3ac9c85bfa34c6a85aefb75900d480e35` |
| Central rollout annotation | `v84-routine-routing` |
| Installed coordinator SHA-256 | `67a76d00062d4b17d3e6a537d5f62faf7b047ab9a8c116dfe030c8768a5ccb5f` |
| Delivery profile | `build1-flow-pilot-registered-v4` |
| Policy | `openai-autonomy-v2` |
| Policy SHA-256 | `9f5a110961635a501c31d7323b2656be54c15092eca47d3f551a31ce0156cfca` |

Before mission acceptance, Flux `GitRepository/uap` and `Kustomization/uap` both reported
`master@sha1:4ebe80d3ac9c85bfa34c6a85aefb75900d480e35`. The Ready Central pod carried
`config-revision=v84-routine-routing`. Build-1 installed the coordinator from the same merge, and source and installed
hashes matched before its standing timers resumed.

## Autonomous mission

The owner/API goal was:

> Update README only: add one short note that the read-only summary, history, and latest commands never modify the
> journal file. Do not change code or dependencies.

| Item | Exact value |
|---|---|
| Mission | `mission-intake-f1b23aa34b02ff6fdb70113d345d065d` |
| Project | `flow-ledger` / `PavelLizunov/hermes-flow-v2-pilot` |
| Accepted execution class | `routine_docs` |
| Accepted expected file bound | `2` |
| Route | `standard` |
| Route decision | `3c0d507c909f6ed1138974afb5b4c46224b542a374e2b81c5818f10c43d19dd7` |
| Base SHA | `3478909060b49a0727bdb48420a076921b59e1f7` |
| Candidate/reviewed SHA | `0d51be8a53a2076bfef727bc3846a411f41c5902` |
| Target PR | [#14](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/14) |
| Exact merge | `8ef8f3dca4d21a834e5278bf4270911138305194` |
| Changed files | `README.md` only |
| Review cycles | `1` of maximum `2` |
| Natural activation | systemd invocation `e5cb778e87a0467f90ba90500d5b29ce` |
| Wall time | `3m 56s` |

No manual poll, coordinator invocation, route override, model selection, approval or repair command was used after
acceptance. The one systemd invocation performed the complete delivery.

## Runtime model and usage evidence

The author and reviewer model identities below came from Codex rollout `turn_context`, not only requested CLI
arguments. Both reported provider `openai`; the reviewer used a distinct session and a read-only sandbox against the
exact candidate SHA.

| Role | Model / effort | Session | Input | Cached input | Output | Requests |
|---|---|---|---:|---:|---:|---:|
| Author | `gpt-5.6-luna` / `medium` | `019f8c0a-87cc-7d21-a431-225852da4533` | 62,680 | 55,040 | 845 | 5 |
| Reviewer | `gpt-5.6-sol` / `low` | `019f8c0b-f7a5-7f42-afd1-a77fd21f5640` | 75,263 | 50,176 | 847 | 5 |
| Total | — | — | 137,943 | 105,216 | 1,692 | 10 |

The observed cache share was therefore `76.3%`; it is measured runtime telemetry, not an estimated `96.1%`. New
uncached input was 32,727 tokens. The installed terminal formatter reported an OpenAI API-price equivalent of
`$0.19–$0.23` using its 2026-07-22 price snapshot. Subscription execution did not create an API invoice, so that
number is an optimization comparison rather than a billed amount.

The earlier project-onboarding example supplied by the owner used 10,064,683 input tokens across Sol/Terra. The two
missions are not equivalent benchmarks, but the bounded docs canary used 98.6% fewer input tokens and demonstrates
that a plainly routine docs goal no longer inherits the conservative all-profile Sol/Terra route.

## Gates and cleanup

The terminal Central projection reached sequence 28 with exactly these required gates passed:

- author checks;
- independent exact-SHA review;
- required multi-platform CI;
- fresh-main post-verify;
- task/worktree/branch cleanup.

The candidate modified one allowed Markdown file, stayed below the two-file bound, produced no quality failure and
did not require a second generation. The durable coordinator state ended at `phase=complete`, the Kanban root was
archived, garbage collection ran, and disposable local/remote branches and worktrees were absent.

## Preserved failed attempt and discovered cancellation race

An initial operator canary was intentionally excluded from the routing claim. Passing Cyrillic through a Windows
PowerShell-to-SSH pipeline replaced its non-ASCII text with question marks, so mission
`mission-intake-4da6bcb41f37399b10d29cfb062c598d` was accepted without `execution_class=routine_docs`. It was
administratively cancelled and is terminal `cancelled` in Central. Before cancellation was observed, its already
running delivery merged target PR #13, which added an equivalent README note; the clean canary PR #14 refined that
wording. This makes PR #14 a real but deliberately tiny one-file documentation change, not the initial addition.

That late cancellation also exposed a restart defect: cancellation after an exact merge still called failed-PR
finalization, while GitHub had already deleted the merged head branch. The unit failed closed with `failed PR identity
no longer matches the durable candidate`. The production residue was reconciled only after verifying that PR #13 was
merged and its local/remote worktrees and branches were already absent; the task was then archived and its durable
state reached `phase=complete`, `outcome=cancelled`. The follow-up regression in this evidence PR makes merged
missions skip failed-PR finalization while retaining normal cleanup and archive convergence.

## Honest boundary

The production classifier accepts only an explicit docs-only owner instruction and binds the classification plus its
two-file expectation into the immutable Central event and coordinator state. Actual cumulative Git paths are checked
after author execution and must all be Markdown or under `docs/`. Any ambiguity, code change, scope overflow, owner
gate, quality failure or policy mismatch remains conservative/fail-closed. Existing repository checks and required CI
are unchanged.

`gpt-spark-codex-5.3` remains outside the production allowlist because this campaign did not obtain an exact runtime
identity/effort/sandbox canary for Spark. Adding Spark or a new QA actor remains a separately reviewed policy change;
neither is needed to close the immediate over-routing defect.
