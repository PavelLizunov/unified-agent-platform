# Hermes development readiness - baseline 2026-07-11

Status: **Phase 0 COMPLETE; goal execution IN PROGRESS**
Current verdict: **NOT READY**  
Goal: `runbooks/hermes-development-readiness-goal.md`

## Evidence boundary

- UAP source: `06c6f154f011446c759c23bd7bd9da0b01692756` (`master`); the initial baseline was taken at `fca5122`.
- Flux `GitRepository/uap-platform`: Ready at the same SHA.
- Flux `Kustomization/uap-platform`: Ready, Applied revision at the same SHA.
- Runtime: Hermes Agent `v0.18.0 (2026.7.1)`, upstream `7c1a0295`.
- Image: `nousresearch/hermes-agent@sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f`.
- This pass was read-only for cluster, GitHub repositories and target machines.
- No chat messages, secret values or environment dumps were read.

## Execution progress

- Phase 0 is complete: platform/runtime baseline, all 28 repositories, the five pilot refs, owner-gated
  boundaries and current M1-M12 verdicts are recorded below.
- The known M1 schema-drift fix is ready in draft PR #125, with a regression test. It is intentionally not
  merged because that would trigger a live Flux rollout outside an owner-approved window.
- Fleet/onboarding documentation drift was corrected in PR #126. M2 remains incomplete until the prompt/skill
  audit and behavioral routing runs prove the same topology end to end.
- PR #128 added `tools/readiness/readiness.py`, a read-only JSONL evidence collector for M1/M2/M3/M6/M9/M12.
  It cannot perform owner-gated write, failure-injection or authenticated-interface tests.

### Deterministic harness run

Command on ops-1 at `2026-07-11T09:26Z`:

```bash
python3 tools/readiness/readiness.py --output /tmp/hermes-readiness-2026-07-11.jsonl
```

The runner emitted exactly 21 records: **14 PASS / 7 FAIL**, and exited non-zero as required. Flux source and
applied revisions matched `master@sha1:06c6f154f011446c759c23bd7bd9da0b01692756`. The seven failures were:

1. M1 effective model: managed config has no canonical `model.default`, while the PVC/runtime resolve
   `gpt-5.6-luna` and the legacy managed alias is still present;
2. M3 build-1 -> Mac: SSH stops at host-key verification;
3. M6: no active branch ruleset for `VPNRouter`, `vpnctl`, `vpnrouter-gateway` or `suflyor`;
4. M12: `vpnctl` has CI/build entrypoints but no `AGENTS.md`.

The collector only reads model subtrees, redacts sensitive field patterns, truncates evidence and does not emit
full configs or raw status output. Its unit/self-check, secret scan, IaC static gate and all 41 Hermes tests pass.

## Baseline verdict by gate

| Gate | Baseline | Evidence / missing proof |
|---|---|---|
| M1 runtime/model truth | **FAIL** | PVC has `model.default: gpt-5.6-luna`; managed config pins stale `model.model: gpt-5.5`; Hermes v0.18 canonicalizes to `model.default`; dashboard and `hermes status` show `gpt-5.6-luna`, while banner shows `gpt-5.5` |
| M2 fleet truth | **FAIL** | `docs/fleet-map.md` still calls Qwen the only brain; `docs/templates/harvest-from-hermes-nastya.md` says Codex brain is off, contradicting #119/current runtime |
| M3 deterministic routing | **PARTIAL** | ops -> home-1/home-2/build-1 works; build-1 -> Debian works; Windows WinRM port is reachable; build-1 -> Mac stops at host-key verification; N>=3 behavioral routing not run |
| M4 worktree isolation | **NOT RUN** | Existing historical evidence is not a new M4 run across five pilot repositories |
| M5 tests/honesty | **NOT RUN** | Historical UAP acceptance exists; per-repo independent rerun + mutation evidence not collected |
| M6 Git/PR/CI | **FAIL** | Only UAP has an active default-branch ruleset; VPNRouter, vpnctl, vpnrouter-gateway and suflyor have none, so direct default-branch pushes are not mechanically blocked |
| M7 prompt integrity | **FAIL** | Managed documentation claims `model.model` owns the brain, but v0.18 runtime uses `model.default`; full precedence/duplication audit pending |
| M8 injection/secrets | **PARTIAL** | Historical UAP injection tests exist; current five-repo N>=3 corpus and output-redaction check not run |
| M9 interface agreement | **FAIL** | Dashboard/status and TUI banner disagree on effective model; session resume/reconnect not tested |
| M10 durability/recovery | **PARTIAL** | Pod and scheduled backups are healthy; task restart and restore smoke for this goal not run |
| M11 observability/limits | **PARTIAL** | Runtime/status and context limit artifacts exist; full task-to-PR trace and loop-stop test not run |
| M12 shared understanding | **FAIL** | `vpnctl` has no `AGENTS.md`; VPNRouter and suflyor contain semantic instruction conflicts; clean-session and second-agent handoff not run |

Any M1-M12 FAIL makes the current verdict `NOT READY` regardless of prior percentage-based acceptance.

## Live platform snapshot

### Cluster

- `hermes-agent`: 1/1 Running on `uap-home-2`, zero restarts for the current pod.
- `hermes-agent-backup`: the last three scheduled jobs completed.
- `hermes`, `litellm`, both sing-box egress deployments and subfleet deployments are Available.
- Dashboard `/chat` returns HTTP 302 to the basic-auth login flow, proving reachability but not authenticated UI behavior.

### Model/config split (M1 reproducer)

Managed `/etc/hermes/config.yaml`:

```json
{"provider":"openai-codex","openai_runtime":"codex_app_server","model":"gpt-5.5"}
```

PVC `/opt/data/config.yaml`:

```json
{"default":"gpt-5.6-luna"}
```

`hermes config show` reports both leaves in one model object. Installed v0.18 `_normalize_root_model_keys`
documents `default > model > name` and states that the runtime resolver reads `model.default`. Therefore
the GitOps leaf does not override the PVC leaf. This is a schema-drift bug, not a visual-only dashboard issue.

Required proof after a fix:

1. static regression rejects managed `model.model` for Hermes v0.18;
2. managed config uses `model.default`;
3. dashboard, `hermes status`, banner and merged config agree;
4. a new session/provider trace records the same model;
5. Flux is Ready at the fix SHA and the workload rollout is healthy.

## Fleet reachability baseline

| Path | Result | Evidence |
|---|---|---|
| workstation -> ops-1 | PASS | SSH over tailnet |
| ops-1 -> home-1 | PASS | hostname `uap-home-1` |
| ops-1 -> home-2 | PASS | hostname `uap-home-2` |
| ops-1 -> build-1 by IP | PASS | hostname `uap-build-1` |
| ops-1 -> alias `uap-build-1` | FAIL | alias is not defined on ops-1; Hermes has its own `/opt/data/.ssh/config` alias |
| build-1 -> Debian target | PASS | hostname `debian-xfce` |
| build-1 -> Windows target | PASS (transport only) | TCP 5985 reachable; no WinRM command executed |
| build-1 -> Mac target | FAIL | host-key verification stops SSH before authentication |

The direct ops-1 -> Mac failure is not itself a product defect because the documented route is via build-1.
The build-1 host-key failure is an actual readiness gap for Mac/Android target testing.

## Pilot repo-contract inventory

| Repo/ref | On build-1 | Contract sources | Baseline |
|---|---:|---|---|
| `unified-agent-platform@fca5122` | yes | `AGENTS.md`, `CLAUDE.md`, CI, validation/runbook indexes | available; current goal is its missing acceptance layer |
| `VPNRouter@c45e385` | no | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, many platform workflows | rich contract; target-command reconciliation pending |
| `vpnctl@f37c134` | yes, but stale/dirty | `CLAUDE.md`, `README.md`, `justfile`, CI; **no `AGENTS.md`** | build-1 clone is at `33b823f`, has leftover untracked markers, and lacks the `just` command required by its documented local gate |
| `vpnrouter-gateway@b595647` | no | `AGENTS.md`, `CLAUDE.md`, Cargo, CI | contract available; commands not independently rerun |
| `suflyor@8f8e11c` | no | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, Windows CI | contract available; Windows-only target route not exercised |

Cloning missing pilot repos and all write tests are deferred until the owner-approved pilot phase. GitHub tree/API
inspection was read-only.

### Phase 2 read-only repo-contract reconciliation

This pass compared the root agent instructions against the actual default branch, build entrypoints and CI at the
refs above. A file being present is only a structural PASS; contradictory or unenforceable instructions are a
semantic FAIL.

| Repository | Structural | Semantic | Read-only evidence / remaining gap |
|---|---|---|---|
| `unified-agent-platform` | PASS | PASS for repository-local rules | `AGENTS.md`, skills, `tests/verify-local.ps1` and protected `master` agree on PR-only delivery; live Flux and failure paths remain owner-gated |
| `VPNRouter` | PASS | **FAIL** | Root `AGENTS.md` instructs autonomous direct pushes/releases to `main`, while the Hermes acceptance contract requires branch -> PR -> CI and the branch has no protection; the same file contradicts itself about `origin`/`github`/`forgejo` remote names; target routing is written for a local Codex workstation rather than Hermes via build-1 |
| `vpnctl` | **FAIL** | **FAIL** | No `AGENTS.md`; `README.md`, `justfile` and CI agree on the Rust gate, including Docker SSH e2e and secret scan, but do not provide the full Hermes repo-contract; build-1 lacks `just` and its clone is stale/dirty |
| `vpnrouter-gateway` | PASS | PASS with owner gate | Root `AGENTS.md` states native-Linux build, deterministic gate, secret boundaries, destructive `apply` boundary, lab target and explicit owner approval before push/release; `main` still lacks mechanical protection and the gate has not been rerun in a clean build-1 worktree |
| `suflyor` | PASS | **FAIL** | `AGENTS.md` and CI correctly require three Windows Rust crates, but `CONTRIBUTING.md` still describes two; they disagree on the live secret-config path and release authority; `master` has no ruleset and the Windows target gate has not been rerun through Hermes |

CI at the audited refs was green for UAP, `vpnctl`, `vpnrouter-gateway`, `suflyor`, and VPNRouter's `dotnet test`
workflow on `main`. Green CI does not repair the contract or branch-protection failures above.

Required contract PRs, after the owner opens an external-write window:

1. `VPNRouter`: replace direct-main/autonomous-release instructions with its chosen branch/PR policy, normalize
   remote names, and document Hermes routes for Windows, Debian, Mac and Android targets.
2. `vpnctl`: add a concise root `AGENTS.md` sourced from `README.md`, `justfile` and CI; state build-1 bootstrap,
   Docker e2e, secret/generated boundaries, target requirements, PR policy and release/rollback ownership.
3. `suflyor`: reconcile `CONTRIBUTING.md` to the three-crate CI, canonical secret path and owner-only release rule.
4. All four non-UAP pilots: enable default-branch enforcement before any autonomous write-cycle.

### Pilot default-branch enforcement

| Repository | Default branch | Active repository ruleset | Baseline |
|---|---|---|---|
| `unified-agent-platform` | `master` | `protect-master` | PASS |
| `VPNRouter` | `main` | none | FAIL |
| `vpnctl` | `main` | none | FAIL |
| `vpnrouter-gateway` | `main` | none | FAIL |
| `suflyor` | `master` | none | FAIL |

CI workflows existing in a repository do not make them mandatory. M6 remains FAIL until each maintained pilot
default branch rejects a direct push and requires its relevant checks through a ruleset/branch protection policy.

### vpnctl read-only canary

- GitHub `main`: `f37c1345e0b82c9a3b3d792432a1d1eefb02a5ea`; five latest CI runs succeeded.
- build-1 clone: `33b823f7bcbc1474d8294fe9cbc662bbefae8e9d`; branch `main`.
- Worktree contains untracked `marker_a.txt` and `marker_b.txt` from historical concurrency testing.
- `/usr/local/bin/cargo` and `rustc` symlinks exist; `just` is not installed.
- Canonical commands are mechanically present in `justfile` and CI: check, fmt-check, clippy `-D warnings`,
  workspace tests, cargo-deny, gitleaks and Docker-backed ignored SSH e2e tests.
- No build/test was run because syncing/cleaning the stale clone and generating `target/` are outside Phase 0 read-only.

## GitHub repository inventory

`classify` means nonarchived but not yet assigned `active-maintained`, `support-only`, `research`,
`mirror/fork`, `release-only` or `private-sensitive`.

| Repository | Visibility | Archived | Updated | Scope |
|---|---|---:|---|---|
| `PavelLizunov/unified-agent-platform` | public | no | 2026-07-11 | pilot |
| `PavelLizunov/suflyor` | public | no | 2026-07-11 | pilot |
| `PavelLizunov/VPNRouter` | public | no | 2026-07-11 | pilot |
| `PavelLizunov/vpnctl` | public | no | 2026-07-11 | pilot |
| `PavelLizunov/boosty_api_rs` | public | no | 2026-06-15 | classify |
| `PavelLizunov/vpnrouter-gateway` | public | no | 2026-07-10 | pilot |
| `PavelLizunov/hermes-nastya` | private | no | 2026-07-10 | classify |
| `PavelLizunov/subfleet` | private | no | 2026-07-09 | classify |
| `PavelLizunov/homebrew-vpnrouter` | public | no | 2026-07-09 | classify |
| `PavelLizunov/ninitux-landing` | public | no | 2026-04-28 | classify |
| `PavelLizunov/test_methodology-toolkit` | private | no | 2026-06-24 | classify |
| `PavelLizunov/wgturn-core` | public | no | 2026-06-18 | classify |
| `PavelLizunov/whitelist-bypass-research` | private | no | 2026-06-17 | classify |
| `PavelLizunov/slipstream-rust` | public | no | 2026-06-14 | classify |
| `PavelLizunov/dns-tunnel-research` | private | no | 2026-06-08 | classify |
| `PavelLizunov/wb-price-scheduler` | private | no | 2026-06-08 | classify |
| `PavelLizunov/sing-box` | public | no | 2026-05-22 | classify |
| `PavelLizunov/edu` | public | no | 2026-05-21 | classify |
| `PavelLizunov/wgturn-server` | private | no | 2026-05-07 | classify |
| `PavelLizunov/vk-turn-releases` | public | no | 2026-04-02 | classify |
| `PavelLizunov/vpnrouter-android` | public | yes | 2026-07-01 | excluded |
| `PavelLizunov/TorrentMax` | public | no | 2026-02-24 | classify |
| `PavelLizunov/hytale-party-plugin` | public | yes | 2026-07-08 | excluded |
| `PavelLizunov/hytale-server-docker` | public | yes | 2026-07-08 | excluded |
| `PavelLizunov/mc-scripts` | public | yes | 2026-04-19 | excluded |
| `PavelLizunov/combine_project` | public | yes | 2026-05-11 | excluded |
| `PavelLizunov/fc-auto-installer` | public | yes | 2026-05-11 | excluded |
| `PavelLizunov/dbt-etlcraft-rebuild` | public | yes | 2024-09-21 | excluded |

Summary: 28 repositories, 21 nonarchived, 7 archived, 5 in the pilot wave.

## Tooling limitation observed

The desktop `uap-offload` endpoint was down during repo-contract extraction. The 269 KB instruction/CI corpus
was not silently loaded into the paid context. Only narrow matching lines and GitHub tree metadata were inspected.
Full quote-gated extraction remains pending after the desktop endpoint is started.

## Owner-gated work not executed

- merge of any `clusters/prod` fix, because Flux would deploy it live;
- authenticated dashboard/Telegram write-cycle;
- cloning or modifying missing pilot repos on build-1;
- sacrificial branches, PRs, mutation tests and target package installs;
- pod roll mid-task, model/egress/build-1 failure injection;
- Mac `known_hosts` modification;
- restore/destructive tests.

## Next actions

1. In an owner-approved live window, merge draft PR #125 and verify Flux, rollout, dashboard, banner,
   `hermes status` and a new provider trace all resolve the same model.
2. Complete the M2/M7 prompt, skill and precedence audit; add mechanism tests for every critical routing rule.
3. Reconcile `vpnctl` on build-1 without destroying its dirty worktree, then add the missing repo-contract through
   that repository's own PR/CI path.
4. Start desktop offload and run quote-gated extraction over the five repo contracts.
5. Ask the owner to classify the 16 nonarchived nonpilot repositories before expansion.
6. Owner action: enable default-branch rulesets on the four non-UAP pilot repositories before any autonomous
   write-cycle.
7. Only after those preconditions, run the N>=3 behavioral, worktree, mutation, PR/CI, injection, interface,
   failure and recovery tests required by M3-M12.
