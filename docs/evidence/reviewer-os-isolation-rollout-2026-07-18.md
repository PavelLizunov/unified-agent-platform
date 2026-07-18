# Reviewer OS isolation rollout — 2026-07-18

## Scope

This record covers the narrow reviewer process boundary added to the existing build-1 delivery coordinator. The
original rollout did not include a real Codex review through the new boundary; the controlled follow-up below now
records one completed runtime-attested reviewer after two production corrections. It still does not claim a completed
Product Operating Contract, author isolation or generic protection for secrets stored outside the enumerated host
credential locations.

## Immutable GitHub identity

- PR: `PavelLizunov/unified-agent-platform#266`
- author head: `8cdf151753fab83252eb991151c0c0044b6dead6`
- required GitHub Actions run: `29656944054`
- required check: `static-checks`, passed in 35 seconds
- merge commit: `a0d8f3914ef1d1462b8b378feee2866cb69e65b8`

Local and Linux verification before merge:

- `tests/verify-local.ps1`: `verify-local-ok`
- coordinator tests: 113/113 on Windows and Linux
- Linux static discovery: 174/174
- Python bytecode compilation and `git diff --check`: passed

## Boundary implemented

Every reviewer Codex command is wrapped by `systemd-run --user` in a deterministic transient unit bound to the active
`hermes-delivery-coordinator@<profile>.service`. The durable model-attempt ID names the child unit. Missing or invalid
parent identity, missing `systemd-run`, an unexpected user-runtime directory or transient-unit failure stops review
fail-closed.

The child unit applies:

- `PrivateUsers=true`;
- `ProtectSystem=strict` and `ProtectHome=read-only`;
- explicit read-only source checkout, all delivery worktrees and mission state;
- explicit writable mission-local model home and configured Codex runtime home only;
- `ProtectProc=invisible` and `ProcSubset=pid`;
- `PrivateTmp=true`;
- inaccessible common credential stores and the whole per-user runtime directory;
- removal of inherited control-plane/credential environment names;
- `NoNewPrivileges`, `RestrictSUIDSGID`, `LockPersonality`, bounded runtime and parent `BindsTo`/`After`.

The existing exact-SHA source attestation, separate reviewer session, exact route/model/runtime attestation and Codex
`read-only` sandbox remain mandatory. The Linux boundary is additive; it does not replace those gates.

## Adversarial preflight history

The first disposable build-1 probe intentionally tested actual writes rather than only inspecting unit properties.
Without `PrivateUsers=true`, user-systemd accepted `ProtectSystem`, `ProtectHome` and `ReadOnlyPaths`, but the child
still wrote into all three protected directories. The implementation was not published in that state.

After adding `PrivateUsers=true`, the exact candidate wrapper:

- read the candidate;
- failed to write source, worktree or mission-state paths;
- wrote only to model home and Codex runtime home;
- could not read the real build-1 delivery credential file;
- could not read unrelated `/proc` environment;
- could not access the user-runtime bus or query the user-systemd manager environment;
- retained a writable private `/tmp`.

The corrected exact-wrapper preflight printed `exact-reviewer-wrapper-preflight-ok` before PR publication.

## Installed build-1 proof

The exact merge was installed with all five coordinator timers stopped. Installer `install` and `--check` both
returned `hermes-flow-v2-install-ok` before timers resumed. The already armed capacity-canary profile was restored
before timer start; its only difference from the repo profile remained the approved `codex_bin` wrapper.

Exact hashes:

```text
2a96d8c22f28d0912dffae62191737d8e04a2fa0bfaf04b516d9936d0f7021e2  merge/tools/swarm/delivery_coordinator.py
2a96d8c22f28d0912dffae62191737d8e04a2fa0bfaf04b516d9936d0f7021e2  /home/uap/swarm-bin/delivery_coordinator.py
1e61d90c54e40afb0a1fff354aafd775fb4c359565e4ce4971240f324e8ac5ff  merge/tools/swarm/systemd/hermes-delivery-coordinator@.service
1e61d90c54e40afb0a1fff354aafd775fb4c359565e4ce4971240f324e8ac5ff  /home/uap/.config/systemd/user/hermes-delivery-coordinator@.service
```

`systemd-analyze --user verify` passed. The installed unit exposes the exact parent identity through:

```text
Environment=UAP_COORDINATOR_UNIT=hermes-delivery-coordinator@%i.service
```

An installed-code exact-wrapper probe repeated the write, credential, `/proc`, user-runtime and allowed-output
assertions and printed `installed-exact-reviewer-wrapper-probe-ok`.

All five standing timers were active after rollout. Four observed natural ticks of
`hermes-delivery-coordinator@flow-pilot-registered-v4.service` returned `null` with `Result=success` and exit status 0.
No manual coordinator tick was invoked.

The capacity wrapper remained exact and armed:

```text
profile codex_bin = /home/uap/.local/libexec/uap/codex-capacity-canary-20260718
capacity marker = pending
```

Central's latest mission was still `mission-intake-f53871c022ce187501a0e9d9021b8823`, terminal `completed/complete`;
no new owner mission had arrived during this rollout.

## Honest boundary

At rollout time, this evidence proved that the merged and installed coordinator could create the enforced Linux
reviewer boundary and that the boundary denied the tested writes and credential/process/runtime access. It did not yet
prove a full Codex review inside that boundary; the follow-up below records that later gate.

## Controlled live follow-up

The next ordinary Telegram mission reached a real reviewer and exposed an actual ordering defect. `After=` made the
transient child wait for its still-activating oneshot parent while that parent waited for the review. PR #271 (merge
`a360e61`, required run `29659665632`) removed only that ordering edge and retained `BindsTo=`.

Restart then preserved the same candidate but correctly classified the interrupted attempt as ambiguous. That safe
quarantine had no convergence transition. PR #272 (merge `ea597a9`, required run `29660284068`) added a reviewer-only
retry after proving the old unit was unloaded, the checkout was clean at the exact candidate and the draft PR was
unchanged. Author ambiguity remains fail-closed.

The same mission then completed a real reviewer inside transient unit
`uap-review-4e34190fad46d832ab1d2c03.service`. Live properties retained the parent `BindsTo=` without the parent
ordering edge and showed the expected private-user, strict read-only filesystem/home, private tmp and hidden-proc
boundary with only the mission-local model and Codex homes writable. Runtime attestation recorded:

```text
model:              gpt-5.6-terra
reasoning effort:   xhigh
sandbox:            read-only
session:            019f76fd-40b7-73a2-a46a-32625a2e41ac
reviewed SHA:       255d4e464864f316fc739bf72aa49a750e3e1c5c
tree:               7feb4103e6e3cc7bf822ce3b003347ffa4aacf61
verdict:            accept
```

The distinct Sol author session, required multi-platform CI and exact-head merge subsequently passed. This accepts one
real Codex reviewer execution through the corrected OS boundary. It does not prove author isolation, hostile
same-UID resistance outside the unit, generic secret-store coverage or a clean campaign that began with both fixes
already installed.
