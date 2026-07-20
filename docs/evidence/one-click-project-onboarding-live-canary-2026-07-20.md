# One-click project onboarding live canary — 2026-07-20

## Verdict

**PASS for the ADR-035 Rust/GitHub-macOS/no-deploy boundary.** One owner action in
`Settings -> Проекты и доступы` created a private GitHub repository, installed its server-owned delivery profile and
persistent timer, ran a real autonomous code change through macOS CI and independent exact-SHA review, merged and
post-verified it, then activated the project in the catalog. The final Workspace state was `100%`,
`Проект готов: его уже можно выбирать и использовать автономно`, and the new project radio was selected with status
`Готов к автономной работе`.

No owner approval, repository path, model name, shell command, manual mission acceptance, coordinator invocation,
merge or Flux reconcile was supplied after the form submission. Read-only observation did not mutate the run.

## Final request identity

| Field | Value |
|---|---|
| Request | `project-onboarding-170ac9b31190f8b6d4eb263cac3bf35d` |
| Project | `uap-macos-oneclick-final-20260720` |
| Repository | `PavelLizunov/uap-macos-oneclick-final-20260720` |
| Preset | `rust` |
| Test target | GitHub-hosted macOS (`test-macos`) |
| Delivery mode | `none` |
| Created | `2026-07-20T16:55:13.975Z` |
| Ready | `2026-07-20T17:17:45.572Z` |

The authenticated Central request ended at checkpoint `ready`, progress `100`, with no error. The live public
project projection returned category `registered`, status `ready`, delivery mode `none` and only the safe test target
`github-macos`.

## Repository and runtime setup

The driver created the private repository with dependency-free Rust starter code, a committed deterministic
`Cargo.lock`, and `.github/workflows/ci.yml` targeting `macos-latest`. Bootstrap commit:

`9a35b81345deadba2342b2881c809c27aadc84cb`

The setup change was admitted through the protected UAP repository rather than changing the live catalog directly:

- UAP setup PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/358>
- head: `a3bc96320c7f4f02b5d90c0e1c89ca4307a67ecb`
- required `static-checks`: run `29761741026`, job `88417765338`, passed
- merge: `7ea35e44a36aa26132f034cc055e9251da310325`
- Flux source and Kustomization both applied that exact revision before the canary was accepted.

The installed profile was
`build1-uap-macos-oneclick-final-20260720-registered-v4`. It kept the repository, checkout, allowed path prefixes,
test command, required CI and OpenAI-only route server-side. Its persistent one-minute coordinator timer was enabled
and active before the canary mission appeared.

## Autonomous delivery canary

Central mission `project-canary-351ea8ba5094f4e60f00ffa1cb87ac51` was accepted by the natural timer at
`2026-07-20T17:01:12.690Z`. It used native task `t_f382f293`, run `64`, and the deterministic complex route:

- author: `gpt-5.6-sol`, `xhigh`, `workspace-write`, session
  `019f807e-0dbf-7e71-a352-a725721e9abe`;
- reviewer: `gpt-5.6-terra`, `xhigh`, `read-only`, distinct session
  `019f8081-5590-7200-b55f-96f3496ce74b`;
- route decision: `1c6c46de97af5d26598af44ab065df1a0652c25eeddf1abc71be1d56ae74be47`;
- policy: `openai-autonomy-v2`, SHA-256
  `9f5a110961635a501c31d7323b2656be54c15092eca47d3f551a31ce0156cfca`.

The first candidate `ce932fe9bbefb550a23c8f34fa36380f3b333951` passed macOS CI run `29762164778`, but the
independent reviewer rejected it because the documented CLI output lacked an executable-level test. The coordinator
recorded exactly one review rejection and automatically started correction cycle 2; no owner question was created.

The repaired candidate `bca946e9caf4e668fdf42761683e19c339456763` added the CLI integration assertion while preserving
the requested dependency-free boundary. The second macOS CI run `29762565767`, job `88420540996`, passed. A new
read-only Terra session reviewed that exact SHA and returned `accept` with no findings. Source-attestation SHA-256:

`45b1f4b50d9fbdcc09d58cb0fd3f038c71966cd9761890dd3152a7507ceff5a4`

Target delivery:

- PR: <https://github.com/PavelLizunov/uap-macos-oneclick-final-20260720/pull/1>
- accepted candidate and PR head: `bca946e9caf4e668fdf42761683e19c339456763`
- merge: `c46dcf5222e95e5a4fb013319d4dd9f0aa67b33e`
- fresh-main post-verify: `/usr/local/bin/cargo test --all-targets`, exit `0`, at the same merge SHA
- changed paths: `README.md`, `src/lib.rs`, `src/main.rs`
- cleanup: task archived, local and remote delivery branches deleted, both disposable worktrees removed.

Central committed exactly one `mission.completed` at sequence `23`, projection `d881139ab1917110`. It projected all
five passed gates (`tests`, `review`, `ci`, `post-verify`, `cleanup`), merged PR/default-branch deliveries and explicit
`delivery: not_applicable`.

## Canonical completion evidence

The coordinator wrote the closed completion bundle before terminal publication. The installed verifier returned:

```text
hermes-flow-completion-evidence-ok cd261e80b19e34e96f16a7b7af1ea7e6380372493c5f7124a805fbe1b57a64b3
```

The bundle binds the mission/task/run, route and policy, runtime-attested author/reviewer sessions, exact reviewed
SHA, PR and required CI run, merge/default SHA, post-verify, cleanup and a two-invocation systemd chain. Installed
coordinator SHA-256 was `da0be7d9f3cafd946b9e695f017a48101e6e689cf0e68bc78be8a9ae63ba137b`;
profile SHA-256 was `f551e122385236cd091fd1d2898c254eb8e5156d6d8f6ca44a33e8218bdb068d`.

## Catalog activation

After the terminal canary, the onboarding timer opened the final activation PR automatically:

- UAP activation PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/359>
- head: `23f6e52d7aee360ca66d1dec3694bfdc5c553472`
- required `static-checks`: run `29762965718`, job `88421910274`, passed
- merge: `c87055a1bc2cf361ef9be18f168c64df94490827`
- Flux GitRepository revision: `master@sha1:c87055a1bc2cf361ef9be18f168c64df94490827`, Ready
- Flux Kustomization applied the same exact revision, `ReconciliationSucceeded`.

The next natural onboarding tick advanced the durable request to `ready`. A browser-authenticated Workspace check
observed the new ready radio checked and the server-selected current project equal to
`uap-macos-oneclick-final-20260720`.

## Corrections before the clean attempt

The earlier disposable campaigns are retained as negative evidence. They exposed two production-semantics defects
instead of being rewritten as success:

1. A Codex wrapper could return non-zero after an otherwise trusted `turn.completed`; PR #356 added a conservative
   terminal-success classification while preserving strict rollout/model/sandbox attestation. It passed required run
   `29760453862` and merged as `4c023247dfbfe953330842b9458f4f6856a9533f`.
2. The Rust bootstrap omitted `Cargo.lock`, so authoritative checks regenerated it outside the allowed candidate and
   restart classified the interrupted phase ambiguously. PR #357 committed a deterministic lockfile and made schema-v4
   check mutation use the existing guarded invalid-candidate cleanup. It passed run `29761408240` and merged as
   `da266a8f6fa0bba362e23e420b00bf95a5d439c9`.

The final request above was submitted only after both corrections were merged, installed and verified. No runtime
implementation changed between its submission and terminal `ready` checkpoint.

## Allowed claims and remaining boundary

It is now correct to say:

> From Workspace, the owner can create and prepare a new private Rust project with one action after entering its name,
> preset and description. UAP creates the repository, installs a fail-closed registered profile and timer, proves a
> real OpenAI-only delivery through independent review and GitHub macOS CI, and exposes the project only after the
> canary, protected UAP PR and Flux rollout are green.

This proof does not claim:

- automatic invention of project requirements; the owner still enters name, preset and description;
- an arbitrary existing repository can be inferred from natural language or made executable without a reviewed
  profile;
- Go, Python or Web presets have a live onboarding canary (their behavior is hermetically tested only);
- access to the owner's Mac mini; the proved macOS gate used an ephemeral GitHub-hosted runner;
- deploy/release support for this project; applicability was explicitly `none`;
- concurrent/HA onboarding; Central intentionally services one pending onboarding request at a time;
- cryptographic proof that every systemd invocation was timer-triggered. The bundle binds exact unit and invocation
  identities, and live observation saw only persistent timer starts, but unit identity alone is not timer provenance;
- a final independent third-party completion audit. That audit is the next gate after this evidence lands.
