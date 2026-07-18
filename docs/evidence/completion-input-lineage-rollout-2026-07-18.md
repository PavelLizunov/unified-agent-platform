# Completion input-lineage rollout — 2026-07-18

## Result

Completion-evidence schema v2 is merged and installed on both Central Hermes and build-1. New registered ordinary
Workspace/Telegram missions persist only their server-owned input platform plus SHA-256 values for the canonical
source key and source message identity. The closed verifier binds the full source-key digest to deterministic
`mission-intake-*`; existing schema-v1 bundles remain valid.

This is a rollout and component proof, not a new live delivery bundle. The existing ordinary Telegram campaign bundle
remains schema v1 because its mission was accepted before this runtime.

## Git and required CI

```text
PR                         #275
author head                5db133988c3aff667c028e6f84bdbf5be85106e7
squash merge               3ccd7bf968502727a487f8bdf4fd53903881aedf
required CI run            29662214217
static-checks              success
```

The required job covered the full static fixtures, every `tools/**/test_*.py`, Kustomize rendering, the secret scan
and gitleaks. Focused Linux checks also passed 120 coordinator tests, 38 flow-contract tests, MissionStore runtime,
Central deployment/config rendering and both pinned Hermes overlays.

## Central Flux rollout

Flux reported both objects Ready at the exact merge:

```text
GitRepository/uap-platform  master@sha1:3ccd7bf968502727a487f8bdf4fd53903881aedf
Kustomization/uap-platform  master@sha1:3ccd7bf968502727a487f8bdf4fd53903881aedf
pod                         hermes-agent-5fbddc9c9b-qjrqs
pod Ready / restarts        1/1 / 0
config revision             v49-completion-input-lineage
merged runtime SHA-256      40d0dacaba382f89fec9dcaab3923b43cf29b7f4d31674a9b3120e6077b1e4a6
mounted runtime SHA-256     40d0dacaba382f89fec9dcaab3923b43cf29b7f4d31674a9b3120e6077b1e4a6
```

An in-pod temporary MissionStore accepted one synthetic ordinary Workspace turn as
`mission-intake-45f3a14747d9ae262aabd556b617b2ff`. The component assertion verified:

- `input_platform == workspace`;
- both stored source digests are 64 lowercase hex characters;
- the message digest equals SHA-256 of the supplied source-message identity;
- the mission suffix equals the first 32 characters of the source-key digest;
- replay of the same ordinary turn returned the same event with `created == false`.

The component emitted `mission-input-lineage-v2-ok`. Raw session/message identifiers are not copied into the
completion bundle.

## Build-1 installation

All five profile timers were stopped while no coordinator process was running. Installation used an archive of the
exact merge; both the installer and its exact check emitted `hermes-flow-v2-install-ok`.

```text
delivery_coordinator.py source/installed  3647c105facf0513ba84f4eef71b93f8eb594777d3efd58e9bf5e999e49b0784
flow_contract.py source/installed         2a31ea5417d688ac1a5cdc9d025c92ce785e40e1a18d8a0cc7920f43384d3271
registered profile source/installed       fd112cac7db99a8f848ec059a05a7d6b502f3d3d45cd42b777e3da693833cd40
```

The earlier controlled capacity wrapper had already fired and was only a pass-through afterward. This rollout
restored the exact repo-owned registered profile, so `codex_bin` is no longer overridden. After `daemon-reload`, all
five standing timers returned active. A natural registered-profile tick completed without a queued mission:

```text
InvocationID    e02ff5ce24eb4bf7b9102b44f39c2e40
Result          success
ExecMainStatus  0
```

The installed verifier accepted both closed versions:

```text
schema v1  hermes-flow-completion-evidence-ok 68975523c03b8a9817127c3b44176cbf714566fe98f11ba0ad062a905eeaf53e
schema v2  hermes-flow-completion-evidence-ok 677e934d0d8112b9f145be8ca9fd3543ee2c7e63f829520db17cbe3b74e1ee73
```

## Proven boundary and remaining gate

This rollout proves exact installed code, deterministic ordinary-input lineage, replay compatibility and installed
v1/v2 verification. It does not yet prove that a new real Workspace/Telegram delivery writes and verifies a schema-v2
bundle. The next live artifact should come from the planned cross-channel question/resume canary. Channel delivery
cursors, journal proof that every coordinator invocation came from the timer, artifact signing/attestation and
applicable deploy/release revision evidence remain outside schema v2.
