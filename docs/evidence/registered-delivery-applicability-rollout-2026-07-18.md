# Registered delivery applicability — rollout evidence (2026-07-18)

## Scope

This record covers one narrow Product Operating Contract correction: the registered `hermes-flow-v2-pilot` target
has no deploy or release step, so its mission must carry explicit `delivery_mode: none` and Central must require a
separate `delivery: not_applicable` event before terminal completion. Fresh-main repository verification is no longer
allowed to imply deployment.

This does not implement deploy/release. Those modes remain fail-closed until exact artifact, environment,
deployed-revision and health evidence is defined.

## Exact change and gates

PR [#262](https://github.com/PavelLizunov/unified-agent-platform/pull/262) landed:

```text
head:  a0a33cc44ca69825618ad48d8581612df95ae34d
merge: 32e207a33e2d995fc8a35fa06cf7ad991154a802
CI:    29654498694 (static-checks passed in 38 seconds)
```

The server-owned Workspace/Telegram intake targets and repo-owned schema-v4 profile now carry
`delivery_mode: none`. Central stores it in immutable `mission.accepted` data and will not complete that mission until
all prior gates, PR merge, default-branch verification and `delivery: not_applicable` are present. Legacy accepted
missions without `delivery_mode` retain their prior completion contract. Registry values that declare `deploy` or
`release`, and schema-v4 profiles with those unsupported modes, fail before acceptance/activation.

The exact head passed:

- repository `verify-local-ok` twice;
- 24 mission-adapter tests, including one adapter-to-real-MissionStore completion component test;
- all 111 delivery-coordinator tests;
- mission runtime, event-contract, deployment and Flow contract suites;
- every `tests/static/test_*.py` on Linux;
- all 41 Hermes unit tests;
- every `tools/**/test_*.py`, including both exact pinned Hermes and Workspace overlays.

The Windows pinned-Hermes overlay checkout produced its known CRLF fingerprint mismatch. The exact same overlay test
passed on Linux before the commit; no upstream fingerprint was relaxed.

## Central Flux rollout

Flux source and production Kustomization both converged to the exact merge:

```text
master@sha1:32e207a33e2d995fc8a35fa06cf7ad991154a802
```

The changed server-owned intake environment caused a normal pod-template rollout. Replacement pod
`hermes-agent-677d9d565b-rm6m4` became Ready at `2026-07-18T17:45:59Z`. Its mounted mission runtime matched the exact
merge source:

```text
aed46e025fd49f8f9837488f455c0c43955b637ca730f76301cb7975772f1491
```

An in-pod import resolved both `workspace` and `telegram` to exactly:

```json
{
  "dispatch_profile": "build1-flow-pilot-registered-v4",
  "delivery_mode": "none"
}
```

Central health returned HTTP 200. A read-only projection of the previously completed ordinary Workspace mission
`mission-intake-f53871c022ce187501a0e9d9021b8823` remained terminal with legacy `delivery_mode = null`, proving live
backward projection compatibility.

## Build-1 exact install and preserved capacity canary

The standard installer and `--check` both returned `hermes-flow-v2-install-ok` from detached merge
`32e207a33e2d995fc8a35fa06cf7ad991154a802`. Installed coordinator and exact source hashes matched:

```text
1ee70a1e78a69bff2763f5dc291af8570599ee202ac879528b718a247ddfa684
```

The repo-owned registered profile source hash was:

```text
67577a2ada8970168735e71c28c8ac4263bd5febe955c29f55221567c5a9481b
```

The controlled capacity canary was already armed before this rollout. After the exact install, the live registered
profile was re-armed with only its temporary `codex_bin` wrapper added; deleting that one field made the installed JSON
equal to the repo-owned profile byte-for-structure and retained `delivery_mode: none`. Its armed file hash was:

```text
87b953656b26f57ae066043839d548e999076bcc2dc93885909eb632aa5e5da4
```

All five profile timers returned to `active`. The registered timer's natural invocation at
`2026-07-18 17:50:59 UTC` returned `null` and exited successfully; no manual coordinator tick was used. The one-shot
capacity marker remained absent because no new ordinary Telegram mission had been accepted.

## Preserved rollout correction

The first post-install verification referenced the nonexistent path
`/home/uap/.local/libexec/uap/swarm-bin/delivery_coordinator.py`. The command therefore stopped after the successful
installer/check and before capacity re-arming. Its EXIT trap restored all previously active timers, but the registered
profile temporarily contained the normal repo-owned Codex path instead of the canary wrapper.

The registered service was inactive and no new mission/capacity marker existed. The registered timer was stopped,
systemd was reloaded, the wrapper was restored over the new exact `delivery_mode: none` profile, and the actual
installed coordinator at `/home/uap/swarm-bin/delivery_coordinator.py` was hash-checked. The natural idle tick above
then verified the corrected operational state. The temporary transfer copy was removed.

## Accepted claim and remaining boundary

Accepted:

> For the registered no-deploy pilot, delivery applicability is immutable server-owned mission state and Central
> requires explicit not-applicable evidence before successful completion. Legacy missions remain compatible and
> unsupported deploy/release declarations fail closed.

Not accepted:

- generic deploy or release execution;
- artifact digest, environment or deployed-revision attestation;
- post-verify against a running deployed revision;
- rollback;
- the still-pending live capacity failure/recovery canary;
- ordinary Telegram and cross-channel question/answer live proof.
