# Automatic capacity observation — rollout evidence (2026-07-18)

## Scope

This record covers the deployed observation boundary for the existing restart-safe Codex capacity state machine.
Central can now project a bounded `mission.notice`, Workspace renders it, Telegram derives its notification from the
same projection, and the delivery coordinator emits deterministic wait/recovery notices without creating an owner
question.

At the time of this rollout, this was deployment evidence rather than a successful live capacity canary. The later
ordinary Telegram campaign is recorded separately in
[`ordinary-telegram-capacity-recovery-2026-07-18.md`](ordinary-telegram-capacity-recovery-2026-07-18.md).

## Landed implementation

PR [#259](https://github.com/PavelLizunov/unified-agent-platform/pull/259) landed:

```text
head:  afb946040a85ddc7b68b879169c50dd7d27b0b56
merge: c82ee511a74f8d7b520ec4aacaf55547ea9ea688
CI:    29653318555 (static-checks passed)
```

The closed producer schema accepts only `mission.notice` values with:

- code `capacity_wait` or `capacity_recovered`;
- a bounded owner-facing message;
- an explicit boolean `owner_action_required`;
- an optional validated UTC `next_attempt_at`.

The reducer stores the latest notice in the canonical Central mission projection. Both Workspace and Telegram consume
that projection; neither owns retry state. The coordinator derives stable producer event IDs from the durable capacity
transition, publishes `capacity_wait` while the task is parked, and publishes `capacity_recovered` when the later tick
reclaims it. Capacity never creates an owner question and does not increment quality-failure counters.

The exact PR head passed the repository `verify-local-ok` gate. The focused suites included all 111 delivery
coordinator tests plus mission runtime, contract, deployment and both pinned Hermes/Workspace overlay tests. The exact
pinned Workspace source also passed client and SSR production builds.

## Preserved first rollout failure

Flux reconciled PR #259 merge `c82ee511a74f8d7b520ec4aacaf55547ea9ea688`, but the running Central pod did not
restart. The mission runtime is mounted from a ConfigMap through `subPath`, so changing the ConfigMap alone did not
replace the mounted file in the existing pod.

The mismatch was recorded before correction:

```text
existing pod:            hermes-agent-78b694f785-wwrzg
mounted runtime SHA-256: 0f08f2bcd200...
ConfigMap runtime SHA-256:
e0314e534ee100d98035911daef2a9a196759b9a12ab9796470a2abe2b884495
```

No live-capacity claim was made from that rollout.

## Corrected exact rollout

PR [#260](https://github.com/PavelLizunov/unified-agent-platform/pull/260) changed only the existing pod-template
revision annotation and its regression pin:

```text
head:  e993b22d9fe2cebb7d78f2984f63df12a17b6a70
merge: a7a407aa13c4e060dbf3bcdb8461d8c1b508d0e2
CI:    29653442641 (static-checks passed)
```

The exact head again passed `verify-local-ok`. Flux source and the production Kustomization both converged to merge
`a7a407aa13c4e060dbf3bcdb8461d8c1b508d0e2`. The replacement pod
`hermes-agent-55bf6c6bbd-wpsmm` became Ready. Its mounted runtime hash exactly matched the ConfigMap:

```text
e0314e534ee100d98035911daef2a9a196759b9a12ab9796470a2abe2b884495
```

An in-pod import asserted the two notice event types and the empty-projection `notice = null` invariant. Central
`GET /health` returned HTTP 200.

Build-1 installed the coordinator from the exact merge checkout. Installer and `--check` both returned
`hermes-flow-v2-install-ok`; source and installed coordinator hashes matched:

```text
f063862acdad1e607b76996794331f10e40613979821571ff02aff48ad17f799
```

All previously active approved profile timers were restored to their exact active state. The registered profile timer
was re-armed with the controlled capacity wrapper and remained active.

The live Workspace card hash matched the exact merged overlay:

```text
7b244d5739f0fe30f85470e90362c5f2e2ee8dd4bc8fe140ed0aea0cee6b82fa
```

Its exact source passed the production client and SSR builds. The first immediate HTTP probe caught the normal service
startup window and failed to connect; the subsequent systemd check found the service active, its log reported
`Hermes Workspace running at http://0.0.0.0:3000`, and the Dashboard returned HTTP 200. A browser reload recovered the
existing 20-event mission without an application, null-dereference or internal-server error.

## Accepted claim and remaining live gate

Accepted:

> The exact merged Central, coordinator and Workspace builds can project and render deterministic capacity wait and
> recovery notices through the one authoritative mission state, with `owner_action_required=false`, without changing
> mission progress or creating an owner question.

Not accepted at that rollout checkpoint:

- the exact live Codex capacity error envelope and exit ordering;
- a real `mission.notice: capacity_wait` followed by `capacity_recovered`;
- automatic same-model retry and whole-route fallback under live subscription capacity;
- no-duplicate author execution after a live capacity incident;
- ordinary Telegram intake for the armed canary;
- automatic cross-channel question generation/answer and first-class deploy/release applicability.

## Controlled live follow-up

The later ordinary Telegram campaign fired the pre-announced wrapper once with the exact trusted pre-turn CLI
compatibility message, then recovered automatically on the same approved Sol model. Central sequence 6 projected
`capacity_recovered` with `owner_action_required=false`; the mission did not create a question or increment quality
counters. It continued through runtime-attested Sol author and Terra reviewer sessions, PR/CI/merge/post-verify,
cleanup, terminal sequence 27 and a verified canonical completion bundle.

This closes the controlled deployed recovery gate, but not every item in the earlier list. The wrapper deliberately
injected the exact stderr phrase before Codex started; it was not a naturally occurring provider-capacity response.
The first retry recovered, so no `capacity_wait`, burst exhaustion or whole-route fallback event occurred. Those facts
remain outside the live evidence even though the deterministic state machine is covered hermetically.
