# One-click project onboarding attested canary — 2026-07-20

## Verdict

**PASS for one owner-submitted Rust project on GitHub-hosted macOS with no deploy.** After one Workspace form
submission, the standing systemd timers created a private repository, admitted setup and activation through protected
UAP pull requests, installed a server-owned delivery profile, completed an OpenAI-only Sol/Terra delivery with
independent exact-SHA review and macOS CI, and exposed the project only after Flux applied the ready catalog entry.

No owner approval, repository path, model choice, shell command, mission acceptance, coordinator invocation, PR merge
or Flux reconcile was supplied after submission. Read-only observation did not advance the run.

## Exact identities

| Field | Value |
|---|---|
| Request | `project-onboarding-3b9c8d6a8d46515b61136feb2ec6d5b7` |
| Project | `uap-macos-onboarding-proof-20260720` |
| Repository | `PavelLizunov/uap-macos-onboarding-proof-20260720` (private) |
| Preset / target | Rust / GitHub-hosted macOS |
| Canary mission | `project-canary-8d258da32f2cf0de41c605879e7d1c6d` |
| Native task / run | `t_12538e58` / `66` |
| Final request state | `ready`, `100%`, no error |

The request records 14 exact invocations of `hermes-project-onboarding.service`. Its invocation chain starts at
`cc0360e5844b49f289c186503a9c851f`, ends at `617b509906c748b6916f4242c5027eed`, and hashes to
`f5aa2d433b63d855e2e7378d3ebafe565fc7989ca7d5100908bf106b487d8997`.

## Protected setup and activation

The setup checkpoint used UAP PR [#368](https://github.com/PavelLizunov/unified-agent-platform/pull/368):

- head `26335b57dcfe3b3366b0cbd51b6f5e1328cbb035`;
- required `static-checks` run `29775357623`, passed;
- merge `a36e22a9677590490ca1fd1ef604e791815752e8`.

The installed profile was `build1-uap-macos-onboarding-proof-20260720-registered-v4`, canonical SHA-256
`357c9e13c50f78187ca98aebc699b2240960e47c775b304900a9b9f695c71a13`. The raw installed profile and the value
returned by production `delivery_coordinator.load_profile()` had the same canonical hash before the canary started.
Its persistent delivery timer was enabled and active.

After the canary completed, UAP PR [#369](https://github.com/PavelLizunov/unified-agent-platform/pull/369) activated
the project:

- head `733f9a2777137ace8a5ac740cca5aec1bb4eb526`;
- required `static-checks` run `29776307754`, passed;
- merge `ab1db0b3c4b724320d4216d959a161a163f1f386`;
- Flux GitRepository and Kustomization applied that exact master revision; the replacement Central pod became Ready.

The public catalog then returned only the bounded projection: category `registered`, status `ready`, delivery mode
`none`, and test target `github-macos`.

## Autonomous delivery

The deterministic complex route used:

- author `gpt-5.6-sol`, `xhigh`, `workspace-write`, session
  `019f812f-eb4a-7b51-b74c-b4b547ebb663`;
- reviewer `gpt-5.6-terra`, `xhigh`, `read-only`, distinct session
  `019f8132-de56-75f0-988f-7e9ea5012174`;
- route decision `57ceef17c20e4ea78c1e3abfedc6b6e1bc958032ecbc74e06b72ac885f0d15c5`;
- policy `openai-autonomy-v2`, SHA-256
  `9f5a110961635a501c31d7323b2656be54c15092eca47d3f551a31ce0156cfca`.

Candidate `98eebe136f80c2a45305add7a6b269a956936f2d` changed only `README.md`, `src/lib.rs` and `src/main.rs`.
The independent reviewer accepted that exact SHA with no findings. Target PR
[#1](https://github.com/PavelLizunov/uap-macos-onboarding-proof-20260720/pull/1) passed macOS run
`29775890019`, merged as `04a6b3bb1ec8c61f31145f414f733312098fe442`, passed fresh-main
`cargo test --all-targets`, and completed task/branch/worktree cleanup. Central committed five passed gates and three
delivery projections, with delivery explicitly not applicable.

The delivery coordinator itself records one exact systemd invocation,
`29d41b9efd474a7faa7e94322bb530b8`, under
`hermes-delivery-coordinator@uap-macos-onboarding-proof-20260720-registered-v4.service`.

## Closed evidence bundles

The exact completion bundle is
`docs/evidence/completion/project-canary-8d258da32f2cf0de41c605879e7d1c6d.json`:

- closed-schema digest `535a0abdee9245c6b9f5b3a73661d8c9b462269fc5498160258e292701522bda`;
- byte SHA-256 `02ca486ee66565ed49567d104e88e737273173d60612dfbaac4407599430f64f`;
- installed verifier: `hermes-flow-completion-evidence-ok`.

The exact onboarding certificate is
`docs/evidence/onboarding/project-onboarding-3b9c8d6a8d46515b61136feb2ec6d5b7.json`:

- closed-schema digest `6469019953e8cdbc941edc52921dd2ec33200750dd708d1a6a01e3f41e208c7f`;
- byte SHA-256 `d869ac787d1cf34d7c5fccc65a900957e8b438f5e007d46172edf930c140d8f0`;
- installed verifier: `hermes-flow-project-onboarding-evidence-ok`;
- byte-for-byte link to the completion bundle passed.

The protected-master evidence workflow verifies both closed schemas and their cross-link before issuing GitHub
artifact attestations. Post-merge attestation verification is a separate publication gate.

## Preserved negative evidence and fixes

The previous disposable request `project-onboarding-c7a832b0fb752340cf7ec685610e8f56` was not rewritten as success.
It exposed three production-semantics defects:

1. build-1's installed `gh` did not expose `headRefOid` in `gh pr list`; PR #363 replaced it with the supported
   `commits` field and added an exact command regression;
2. the certificate compared Central's public project projection with internal-only registry fields; PR #366 attested
   the exact public shape;
3. completion evidence hashed the coordinator-effective profile while onboarding compared the raw profile without
   explicit defaults; PR #367 made rendered and runtime-loaded canonical hashes identical and tested that invariant
   through production `load_profile()`.

The previous request terminated fail-closed on the third mismatch. The clean request documented here was submitted
only after all three fixes were merged, installed and verified; no runtime implementation changed between its
submission and terminal `ready`.

## Allowed claim

It is correct to say that one bounded Workspace action can create and prepare a new private Rust project for
autonomous OpenAI-only delivery with GitHub-hosted macOS CI, protected UAP setup/activation, exact systemd invocation
chains, closed completion/onboarding evidence and a ready catalog result.

This does not claim arbitrary existing-repository inference, live Go/Python/Web preset canaries, access to the owner's
Mac mini, deploy/release support, concurrent/HA onboarding, or cryptographic proof that a unit invocation could not
have been started manually. The live campaign observed only standing timer starts, and no manual start was issued.
