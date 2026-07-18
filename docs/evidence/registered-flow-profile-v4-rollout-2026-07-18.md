# Registered schema-v4 delivery profile rollout — 2026-07-18

## Verdict and boundary

PASS for installation and standing idle activation of one reusable registered repository profile.

The repo-owned `flow-pilot-registered-v4` profile is installed on build-1, its systemd timer is enabled, and its first
timer-triggered invocation returned `null` with status 0 because no matching Central mission existed. No manual
coordinator/service invocation was used. This proves a continuously available exact-profile consumer; it does not yet
prove ordinary Workspace/Telegram goal intake or a live schema-v4 delivery. The Central intake registry remains absent,
so owner intake is still production-disabled and fail-closed.

## Git and review identity

| Object | Identity |
|---|---|
| Base before the profile PR | `fbb7bc8d0078bc8f528c15f52e6f96f6264bf253` |
| PR | [#245](https://github.com/PavelLizunov/unified-agent-platform/pull/245) |
| Reviewed PR head | `4c62b7c222907945e5e51a0473d9c136f5b7767a` |
| Squash merge installed on build-1 | `c19d4bd331c52b087698672479f23a914ac25b8d` |
| Independent review | Terra `xhigh`, exact head, read-only, PASS; thread `019f7542-17b9-7ce1-92d8-50c75b2e1384` |
| Required UAP CI | `static-checks`, success on the reviewed head |

The author gate was `verify-local-ok`; independent Linux runs passed 33 flow-contract and 110 delivery-coordinator
tests. The reviewer independently loaded the exact profile and resolved the deterministic `complex` route to Sol
author and Terra reviewer, both `xhigh`.

## Installed profile contract

```text
schema_version: 4
dispatch_profile: build1-flow-pilot-registered-v4
repository: PavelLizunov/hermes-flow-v2-pilot
goal source: immutable Central mission binding
candidate boundary: Cargo.lock, Cargo.toml, counter.py, src/, test_counter.py, tests/
maximum changed files: 12 cumulative from the durable base SHA
required CI: test-linux, test-windows, test-macos, test-python
crash injection: disabled
profile SHA-256: f1c16275e11e62a0a3b7276d87df7dea483c7b134ca3be732f3dd81f2be87b23
```

The installed profile and its source in the exact merge worktree had the same SHA-256. The directory mode was `0700`
and the file mode was `0600`.

## Runtime attestation

The stopped-profile installer and its immediate `--check` both returned `hermes-flow-v2-install-ok`. The three pinned
build-1 Hermes files reported `exact-patched`. Installed/source hashes matched pairwise:

| Runtime object | SHA-256 |
|---|---|
| `delivery_coordinator.py` | `2cc82c91ea4b95b873423ebe9ae1063d5da9415c9f88ad5767b9a1541e039d55` |
| `mission_adapter.py` | `98fc90aa7b5886648bdd3c145956932c87ff311b35089711a8abdd42a79b2923` |
| `flow_contract.py` | `8718da06b6363d0db7e7c8abfdeb8642b6ceafc21d673ebb60990d7c33d4030f` |
| `flow-policy.json` | `5d1a99929ebf23daad922c05e923199e0e7cca137d0263f9722c49f2ddddcf60` |

The four previously active exact-profile timers were restored after installation. The new fifth timer was enabled at
`12:50:43 UTC`. Its first automatic invocation started and finished at `12:52:15 UTC`:

```text
timer ActiveState=active
LastTriggerUSec=Sat 2026-07-18 12:52:15 UTC
service Result=success
ExecMainStatus=0
service ActiveState=inactive
service SubState=dead
journal payload: null
```

After the tick there was no new delivery state and exact-name scans for Codex, Ollama, vLLM and Spark processes were
empty.

## Fail-closed production boundary

The live Central pod still had no `HERMES_MISSION_INTAKE_ROUTES` environment variable and direct gateway `/health`
returned HTTP 200. Therefore neither an owner API call nor an ordinary channel message can dispatch this profile yet.
The next rollout must wire stable Workspace/Telegram message identity to the already deployed owner-intake primitive
and enable only the exact `workspace`/`telegram` mapping to `build1-flow-pilot-registered-v4`.
