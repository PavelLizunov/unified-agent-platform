# Concrete owner terminal result rollout — 2026-07-19

## Result

Central Hermes no longer commits the constant `Delivery completed, merged, and verified` for a successful delivery.
At the existing terminal-authority boundary it now renders one bounded deterministic result from facts already present
in the validated mission projection:

- accepted owner goal;
- merged PR URL;
- verified default-branch revision URL;
- passed tests, review, CI, post-verify and cleanup gates;
- delivery applicability;
- sorted changed paths.

Workspace and Telegram already consume the same Central projection, so this required no channel-specific state, new
schema, dependency, service or model call.

## Git and required CI

```text
PR                         #277
author head                93dcab59e9e2ba9bd3667295640036348b699424
squash merge               40255f04c415b5c0248f6f1847bb191e24d6ac33
required CI run            29662991623
static-checks              success
```

The local live-cluster gate also completed with `verify-local-ok`. Linux checks passed the MissionStore runtime,
deployment/config rendering and exact pinned Hermes mission overlay.

## Exact Flux rollout

```text
GitRepository/uap-platform  master@sha1:40255f04c415b5c0248f6f1847bb191e24d6ac33  Ready
Kustomization/uap-platform  master@sha1:40255f04c415b5c0248f6f1847bb191e24d6ac33  Ready
pod                         hermes-agent-99f754d5f-gwcqg
pod Ready / restarts        1/1 / 0
config revision             v50-concrete-terminal-result
merged runtime SHA-256      43fb1d61747c5e2e1721a4533a3a615d9f503b0adda86f7f04fc6e50a00f87d6
mounted runtime SHA-256     43fb1d61747c5e2e1721a4533a3a615d9f503b0adda86f7f04fc6e50a00f87d6
```

## In-pod component proof

An in-pod temporary MissionStore projected a disposable successful mission with the exact target PR #8, verified
merge revision and the four files from the earlier ordinary Telegram campaign. Central committed this result:

```text
Completed: Add a read-only summary command and update API, CLI, tests, and README
PR: https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/8
Merge: https://github.com/PavelLizunov/hermes-flow-v2-pilot/commit/53eca7e419781679d730575f60848b902a8b7de6
Checks: tests, review, CI, post-verify, cleanup passed
Delivery: not applicable
Changed files (4): README.md, src/lib.rs, src/main.rs, tests/journal.rs
```

The component asserted byte-for-byte equality between the `mission.completed` payload, Central projection and the
result embedded by `telegram_text()`. It also proved that the terminal event remained pending for its Telegram
subscription. The command emitted `concrete-terminal-result-ok`.

## Proven boundary and remaining gate

This proves merged code, exact deployed bytes and the shared Central/Telegram rendering contract. It is a synthetic
temporary-store component proof, not a second real owner delivery. The previously completed Telegram mission remains
immutable with its old generic terminal event. The next real cross-channel question/resume delivery should produce the
first live concrete result (and a schema-v2 completion bundle) without an operator invocation.
