# Canonical completion evidence rollout — 2026-07-18

## Scope and verdict

The registered schema-v4 delivery profile now has the canonical completion-evidence writer and verifier installed on
build-1. At rollout time, a natural timer tick loaded the installed runtime and exited successfully without a queued
mission. The controlled live follow-up below now records the first completed bundle.

## Repository gate

- Source PR: `#268`.
- Reviewed head: `0bfd94ece7f2de35170d0551e98be1497b9a0520`.
- Required check: `static-checks`, run `29658311217`, success in 27 seconds.
- Exact merge: `83f193ae5de2f6036d6303a6bbb9fa126d61f173`.
- Linux static suite: 181 tests passed.
- Windows repository gate: `verify-local-ok` after the final source and documentation changes.

The bundle is closed and self-digesting. Its semantic verifier additionally requires the exact approved ADR-031
OpenAI tuple and policy hash, distinct runtime-attested author/reviewer sessions on one candidate tree, exact
candidate/review/PR identity, Git ancestry checkpoints, GitHub Actions run identities, green required CI and
post-verify records, cleanup, task archive and a terminal Central projection. Recomputed SHA-256 after weakening one
of those relations remains invalid.

## Build-1 installation

All five existing profile timers were stopped while no coordinator service was running. The rollout used a detached
worktree at the exact merge. The already armed capacity-canary `codex_bin` was overlaid into only that disposable
installation profile, so the installed profile contains both:

```text
completion_evidence = true
codex_bin = /home/uap/.local/libexec/uap/codex-capacity-canary-20260718
```

The normal installer and its exact check both returned `hermes-flow-v2-install-ok`. Source/installed hashes matched:

```text
delivery_coordinator.py  810e1374341392a98352b312e0ce3d940a3cab7448a72ae319eeebd60e5774cb
flow_contract.py         d786f0fa3ebb3266c7cafe6c1d7e78a91db8b724006cf730ddf3f82266792a7b
systemd service          1e61d90c54e40afb0a1fff354aafd775fb4c359565e4ce4971240f324e8ac5ff
installed live profile   d742da62abc7fec8c6a1c3ee0fb02c8641b7caffed98a123926ce5df2f323b7a
```

The live-profile hash intentionally differs from the committed profile because the pre-announced one-shot capacity
wrapper remains armed. The disposable overlay and installed file matched each other byte-for-byte. Before the
installer ran, an initial disposable text substitution removed the optional `codex_bin` line; the exact pre-install
inspection caught it, the file was repaired, and no runtime file had yet been copied.

## Natural timer observation

After `daemon-reload`, all five previously active timers returned to `active`. The registered timer naturally fired
at `2026-07-18 19:46:59 UTC`; no `systemctl start` of its service or coordinator CLI was used. The service reported:

```text
InvocationID=00e652a31c2a412caeb57a06cb45318a
ExecMainStatus=0
Result=success
stdout=null
```

The capacity marker remained absent (`capacity-marker-pending`), proving that the idle tick did not invoke Codex or
consume the armed fault. No Flux manifest changed in this rollout.

## Proven boundary

This rollout proves that exact merged source is installed, the registered profile opts in, the capacity wrapper was
preserved, systemd activation remains healthy and the verifier is covered by deterministic Linux/Windows gates.

At rollout time this did not yet prove that a real delivery created a valid `completion-evidence.json`; the follow-up
below records that later gate. The initial schema also
does not include channel-origin/source-event identity, Workspace/Telegram cursors, deploy revision or a signed GitHub
artifact attestation. A systemd `InvocationID` proves the service boundary but is not, by itself, cryptographic proof
that every invocation originated from the timer.

## First live bundle follow-up

Ordinary Telegram mission `mission-intake-0c72cde02b5ef62972a30bc998f316b9` completed on the registered profile after
the adversarial corrections recorded in
[`ordinary-telegram-capacity-recovery-2026-07-18.md`](ordinary-telegram-capacity-recovery-2026-07-18.md). Build-1 wrote
`completion-evidence.json` and the state digest checkpoint with mode `0600`.

```text
file SHA-256:       bef78e627ba69b32ab191874dcb31185ff037f82a2f037a071a3011f78a226f2
semantic SHA-256:   d05c16b75ade9800d9976b3416e5771b13650529dbe42c3306a22029f67601b6
mission sequence:   27 / completed
target PR:          PavelLizunov/hermes-flow-v2-pilot#8
candidate:          255d4e464864f316fc739bf72aa49a750e3e1c5c
merge/default:      53eca7e419781679d730575f60848b902a8b7de6
CI run:             29659412330
```

The bundle bound distinct runtime-attested Sol author and Terra reviewer sessions on the same candidate/tree, the
reviewer's read-only sandbox and source attestation, exact PR/CI/merge/default ancestry, fresh-main post-verify,
explicit `delivery_mode: none`, cleanup, task archive and the terminal Central projection. It also recorded 21 service
invocation IDs in chain SHA-256 `b7138627e0ee82fb65c159dcc27990eef941c6766ae8f831b6dbc7a9a8c71780`.

The installed verifier returned:

```text
hermes-flow-completion-evidence-ok d05c16b75ade9800d9976b3416e5771b13650529dbe42c3306a22029f67601b6
```

This accepts the first live canonical bundle for the registered no-deploy profile. The schema omissions listed above
remain: the bundle is not yet the final signed Product Operating Contract completion certificate.
