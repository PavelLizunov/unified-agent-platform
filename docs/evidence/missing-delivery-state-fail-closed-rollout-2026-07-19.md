# Missing delivery-state fail-closed rollout — 2026-07-19

## Verdict

PASS for the installed safety boundary: an active or previously executed mission can no longer be silently treated as
fresh when its private `delivery-state.json` is missing.

The coordinator now initializes new state only for a demonstrably pristine mission. Projected task/execution history,
surviving mission-local execution artifacts, or an automatic owner-gate route whose approval checkpoint was lost stop
before Codex, Git or GitHub mutation. The one compatible exception is the existing generic `waiting_owner` recovery
with exactly one inert blocked/unassigned task, one open question and a deterministic ready route.

This is fail-closed detection, not reconstruction after total state loss. No production state file was deleted for the
rollout canary.

## Source and regression gate

| Fact | Value |
|---|---|
| source PR | [#286](https://github.com/PavelLizunov/unified-agent-platform/pull/286) |
| source commit | `632403a43b2cc6201b341fee02d9a69cc28afee0` |
| merge commit | `4eaa8f9dd285d5f6dd3bc66536c1afb07880a5de` |
| GitHub Actions run | [29676023329](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29676023329) |
| coordinator tests | `127` passed |
| repository gate | `verify-local-ok` |

The focused regressions are:

- `test_missing_delivery_state_with_projected_task_fails_closed`;
- `test_missing_delivery_state_with_local_artifacts_fails_closed`;
- `test_missing_delivery_state_initializes_only_pristine_mission`;
- `test_missing_automatic_owner_gate_state_does_not_recreate_approval`.

They also assert the absence of model, Git and GitHub mutation on the rejected paths. Existing generic
`waiting_owner` restart tests remain green.

## Exact build-1 installation

The rollout archive was generated from a detached worktree at the exact merge commit and copied to build-1 before the
installation window.

| Artifact | SHA-256 |
|---|---|
| exact merge archive | `fbef0baadcef9c9b07415eb3bb2e6d6f60a728e62f588799510a63b030e35c10` |
| previous installed coordinator | `bd7f2fbb9fecf134963c0590e66d75bc070e161288cd76995695647936a085eb` |
| merged source coordinator | `9092167cf458ead68c9c4a3d4ec9daa1eba9e9185b5e32e6cf858e238fda94f2` |
| installed coordinator | `9092167cf458ead68c9c4a3d4ec9daa1eba9e9185b5e32e6cf858e238fda94f2` |

All six coordinator services were inactive and no model actor was running before replacement. The repository-owned
installer returned `hermes-flow-v2-install-ok`; its independent `--check` returned the same token while every profile
timer remained stopped. That check verifies byte equality, executable/private modes and all three exact build-1 Hermes
overlay patches. `systemd-analyze --user verify` also exited zero.

The pre-existing enabled state was then restored for all six instances:

```text
flow-pilot-a7-3k
flow-pilot-a7-3l
flow-pilot-owner-gate-v4
flow-pilot-registered-v4
vpnrouter-a7-3i
vpnrouter-a7-3j
```

Every timer returned `enabled` and `active`. Each subsequently executed a natural tick with `Result=success`,
`ExecMainStatus=0`; no failed user unit remained.

## Accepted and unaccepted claims

Accepted:

> Build-1 runs the exact merged coordinator that refuses unsafe fresh initialization after loss of durable delivery
> state, while preserving pristine admission and the existing inert generic owner-question recovery.

Not accepted:

- automatic reconstruction of `base_sha`, quality counters, route decisions or candidate identity after total local
  state loss;
- a destructive live state-loss test against a real mission;
- HA or cross-host coordinator safety;
- proof for any deployment other than the six installed build-1 profiles.
