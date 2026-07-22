# vpnctl production deploy live canary — 2026-07-22

## Verdict

**PASS for the registered `vpnctl` production-deploy boundary.** An ordinary Workspace chat message selected the
server-owned `vpnctl` project, created one Central mission, completed independent OpenAI author/reviewer delivery,
merged the exact reviewed candidate, deployed the exact merge to VM 119 (`vpnctld`), verified its production health
and cleaned the disposable execution state. No repository path, model, shell command, approval, manual coordinator
tick, merge or deploy command was supplied by the owner.

This is the first live acceptance of `delivery_mode: deploy`. It proves only the closed
`vpnctld-systemd-v1` driver and `vpnctl-production` environment; every other deploy driver and all release modes remain
fail-closed.

## Ordinary input and execution identity

| Field | Value |
|---|---|
| Input | ordinary Workspace chat (`/api/send-stream`, not the mission API) |
| Workspace session | `e2afa14e-8fb5-4481-9b81-a36720b1a253` |
| Hermes run | `run_3d1de3ed49639a51d3b0e91d47184444` |
| Mission | `mission-intake-e2d2812bf5197db2a0c68754f2351b20` |
| Project | `vpnctl` / `PavelLizunov/vpnctl` |
| Profile | `build1-vpnctl-registered-v4` |
| Native task / run | `t_39656ad4` / `70` |
| Owner question | none |

The accepted goal requested a small production-health documentation and regression-test change. Server-side routing
selected `vpnctl`; the browser did not submit a repository path, delivery driver or execution command.

## Author, review and GitHub delivery

- author: `gpt-5.6-sol`, `xhigh`, `workspace-write`, session
  `019f8934-887b-7fb1-bbb9-bd292b217a6f`;
- reviewer: `gpt-5.6-terra`, `xhigh`, `read-only`, distinct session
  `019f893f-049a-7c51-b5aa-7d1202deebdd`;
- route decision: `40b63edef21afb3d271d10bb80a47f840bf5005e9fb54f09e462922884e07320`;
- candidate and reviewed SHA: `b49ebb74a60c1b2622c6e0c6a095cdbcf5ca57a5`;
- changed paths: `README.md`, `daemon/tests/sub_endpoint.rs`;
- target PR: <https://github.com/PavelLizunov/vpnctl/pull/127>;
- required CI run: `29909605783`, all required Rust, e2e and secret-scan checks passed;
- exact merge/default revision: `770dce039235c3f895ed0020cb4f050c66a31659`;
- fresh-main `cargo check`, `fmt`, `clippy`, `test` and `cargo deny` all exited `0`.

## Production deployment proof

The closed driver built the merged revision as an unprivileged account, then invoked the VM's forced-command deploy
identity. The root-owned installer atomically replaced the approved payload, checked the full installed digest and
would have restored the previous payload if activation or health verification failed.

| Field | Verified value |
|---|---|
| Mode | `deploy` |
| Driver | `vpnctld-systemd-v1` |
| Environment | `vpnctl-production` |
| Proxmox guest | VM 119, `vpnctld`, node `pve-ninitux3` |
| Tailnet address | `100.88.198.106` |
| Deployed revision | `770dce039235c3f895ed0020cb4f050c66a31659` |
| Installed-payload SHA-256 | `a538a378c6f55da2ff5f0a84ee01e8ed2b422bb60bf273d2c76de889719ce456` |
| Health URL | `http://vpnctld:18402/api/v1/health` |
| Health observation | HTTP `200`, `{"status":"ok","version":"0.8.0"}` at `2026-07-22T10:25:26Z` |
| Deployment attempts | exactly `1` |

Central projected six passed gates (`tests`, `review`, `ci`, `post-verify`, `deployment`, `cleanup`) and three
deliveries: merged pull request, verified default branch and verified deployment with the same complete revision and
artifact digest. Terminal sequence `26` returned a concrete Russian result with the change summary, PR, merge,
deployment environment/revision, files, duration, models and token counts.

## Negative evidence and correction

The first terminal projection attempt was not rewritten as success. Deployment itself had already completed and the
durable state recorded one verified attempt, but the mission stayed at `deploying · 95%`: the Central/coordinator
schemas allowed exact deployment fields while `mission_adapter.py` still rejected those fields on
`delivery.upsert`.

PR [#397](https://github.com/PavelLizunov/unified-agent-platform/pull/397) added the missing closed adapter schema and
strict validation for environment, digest and revision. Required `static-checks` passed and exact merge
`f3a0ee6b3a7bf7a55f1619459b20288b421f1c8c` was installed on build-1. Source and installed adapter SHA-256 both
equalled `2fd124c5b2d2d51d5ac619fa0fe0b36e48043ef00f716cd574c6e75f973ee54b`.

After all 21 registered coordinator timers were restored, the next `vpnctl` tick replayed only the deterministic
projection. The mission converged to `completed · 100%`; `deployment_attempts` remained `1`, proving that the already
verified production mutation was not repeated.

## Completion bundle and fleet monitoring

The closed schema-v4 completion bundle is published at
[`completion/mission-intake-e2d2812bf5197db2a0c68754f2351b20.json`](completion/mission-intake-e2d2812bf5197db2a0c68754f2351b20.json).
The deterministic verifier returned:

```text
hermes-flow-completion-evidence-ok 78b04981326f82c6d1ec3c4a3ed72815c8ad9352fdebdecc02e1946db9527966
```

The bundle binds ordinary Workspace input, mission/task/run, exact route and runtime sessions, candidate/review,
PR/CI/merge, production revision/digest/health, cleanup and a ten-invocation coordinator chain.

VM 119 is also part of the repo-owned Proxmox/Tailscale inventory introduced by PR #390. On ops-1,
`uap-healthcheck.timer` remained active at the 20-minute cadence. Four consecutive observations at `09:20`, `09:42`,
`10:01` and `10:21` UTC returned `uap-healthcheck: all checks OK`; a missing, renamed or moved Proxmox guest and an
offline required tailnet peer now alert instead of silently changing the execution fleet.

## Allowed claim

It is now correct to say:

> For the registered `vpnctl` project, an ordinary owner goal can autonomously complete routing, coding, tests,
> independent exact-SHA review, PR/CI, merge, exact-revision production deployment, health verification, terminal
> reporting and cleanup without an operator or owner approval.

This evidence does not claim automatic deployment for other projects, arbitrary execution of newly discovered
Proxmox guests, release-mode support, HA coordinator execution or complete cross-channel chat transcript replication.
