# A7 lifecycle rollout evidence — 2026-07-17

## Scope

This evidence records the reviewed merge and live rollout of the A7 observation/lifecycle baseline. It proves the
code and exact pinned Hermes overlays are installed in Central Hermes and build-1. It does **not** claim that the final
Telegram-bound non-toy autonomous canary has passed.

No new service, dashboard, workflow engine, provider, local inference, GPU workload, swarm or Spark execution was
introduced by this rollout.

## Reviewed changes

| Change | Exact reviewed head | Merge commit | Gate |
|---|---|---|---|
| [PR #235](https://github.com/PavelLizunov/unified-agent-platform/pull/235) — lifecycle/observation baseline | `4a113dca8c1d24188074be4fc98cecf4ad7f8735` | `29195d6ff1e7a4f6f0c631d273def9e1e560df88` | exact-head CI green; separate read-only Terra review: `PASS / No actionable findings` |
| [PR #236](https://github.com/PavelLizunov/unified-agent-platform/pull/236) — accept the exact deployed legacy build-1 overlay | `d8957871a77895113d04c8be8b9876fd3fd67886` | `a2cd6ea7ef4d97bfbb8838748d2275c64bf739f0` | `static-checks` green; separate read-only Terra review thread `019f6e3c-7863-7951-926f-3cff8650d67d`: `PASS / No actionable findings` |

Both reviewed heads were checked as ancestors of their merge commits. PR #236 retains the previously known legacy
`kanban.py` fingerprint and adds only the exact fingerprint observed on build-1; unknown drift remains fail-closed.
The migration restores the pinned pristine upstream source before applying the current overlay.

## Central Flux rollout

Flux reported both objects Ready at the exact final revision:

```text
GitRepository/uap-platform  master@sha1:a2cd6ea7ef4d97bfbb8838748d2275c64bf739f0  Ready=True
Kustomization/uap-platform  master@sha1:a2cd6ea7ef4d97bfbb8838748d2275c64bf739f0  Ready=True
```

The `v39-build1-live-legacy` rollout created pod `hermes-agent-6df868fbd8-kvrw5` on `uap-home-2`; it was Ready with
zero restarts. Mounted files matched the reviewed overlay:

```text
92d6c82cf7c7adf3eace25173aa00a8434367a4403f14942fee60013056bd6bb  hermes_cli/kanban.py
44f462aec94cdc8f93ee00986ba2c90929d3c0c4b7dc79950eb6bb62a63e1500  hermes_cli/kanban_db.py
6b5c98f313f2f99d751847ed893d40456fb4b046569dcb60d119a54e3f7d3132  hermes_cli/main.py
b7fe3d4ed69a5ba3466072bcb805c2fe2d14ccff20f225987db57a105ff70fea  hermes_cli/uap_missions.py
```

An authenticated read-only mission-list request returned HTTP 200 and initialized the lazy store. The gateway health
endpoint returned Hermes `0.18.0`; `/opt/data` was mode `0700`, `missions-v1.sqlite3` was `0600`, SQLite
`integrity_check` returned `ok`, and the active journal mode was `delete`.

## Build-1 rollout and recovery

The first PR #235 installation attempt failed before writes because the actual deployed legacy `kanban.py` fingerprint
`924dcf6b2b277575d1d065aff209347ce5abc96ab158bc80b749f4c3552992cd` was not in the exact migration set. The live
files remained unchanged and the four profile timers were restored. PR #236 added that exact legacy fingerprint
alongside the prior known fingerprint and preserved rejection of unknown input.

On the final merge checkout, the four profile timers/services were stopped. The pre-install invariant check first
observed `failed(signal 15)` units; `reset-failed` converted the stopped oneshot services to the required `inactive`
state before installation. Installation and the independent `--check` then both returned
`hermes-flow-v2-install-ok`. Live build-1 files matched the current hashes above for `kanban.py`, `kanban_db.py` and
`main.py`.

The four enabled profiles were schema v3 with mode `0600`:

```text
flow-pilot-a7-3k  timer=active  last service result=success
flow-pilot-a7-3l  timer=active  last service result=success
vpnrouter-a7-3i   timer=active  last service result=success
vpnrouter-a7-3j   timer=active  last service result=success
```

Older disabled disposable profile files remain schema v1 and are not enabled units. They are lifecycle inventory,
not runtime authority; they were intentionally not migrated as part of the exact live-profile rollout.

## Post-verification

The full workstation validation gate ran after both rollouts and ended with:

```text
secret-scan-ok
iac-static-ok
sops-decrypt-ok
hermes-owner-secret-decrypted-ok
sops-owner-secret-kubernetes-ok
verify-local-ok
```

The live smoke checks also observed both k3s nodes Ready, the final Hermes pod Running with zero restarts, Flux
controllers Ready, scheduling on `uap-home-2`, and SOPS decryption through the node-local age key.

## Remaining product gate

This rollout closes the deployment gap for the A7 lifecycle/observation code. Product Operating Contract completion
still requires one clean uninterrupted non-toy mission that is Telegram-bound before execution and autonomously
converges through author, tests, independent exact-SHA review, PR/CI, merge, post-verify, Central terminal state,
matching Workspace/Telegram projection and disposable cleanup.
