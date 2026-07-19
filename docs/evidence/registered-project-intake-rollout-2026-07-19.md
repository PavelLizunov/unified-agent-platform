# Registered project intake and owner UX rollout — 2026-07-19

## Verdict

**PASS for the registered text-intake and project-permission boundary.** Workspace and Telegram now use one
server-owned catalog for the registered `hermes-flow-v2-pilot`, `vpnctl` and `VPNRouter` repositories. The owner does
not provide a checkout path, delivery profile, model or command. Unknown repositories remain fail-closed.

This record does **not** claim a live voice canary or a completed delivery in each newly registered repository. Voice
intake is wired to the existing Hermes STT seam, but the deployed STT provider has no usable allowed backend or
credential and therefore fails before mission creation. The next ordinary `vpnctl` or `VPNRouter` owner goal will be
the first non-toy live delivery proof for that repository profile.

## Immutable Git and CI identity

Implementation:

- PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/302>
- PR head: `fd33c10d4949c2a63b01ea1d2c1c85a161e3fb1e`
- merge: `765eacaaf1b632c3f69fd3374519a8c28b132850`
- required CI: `static-checks` passed in run `29701646181`, job `88231562263`

Owner-facing language and truthful status follow-up:

- PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/303>
- PR head: `62940c6`
- merge: `03298bdacbe73a9ab7ffd5d552e24d1a609c7f47`
- required CI: `static-checks` passed in run `29702408375`, job `88233573905`

Both commits use `UAP Agent <slovnmi@gmail.com>` and the required Claude co-author trailer. The ruleset admitted both
changes only after the required strict check passed.

## Implemented boundary

The closed catalog contains exactly:

| Project ID | Owner label | Repository | Delivery mode |
|---|---|---|---|
| `flow-ledger` | Mission Ledger | `PavelLizunov/hermes-flow-v2-pilot` | `none` |
| `vpnctl` | vpnctl | `PavelLizunov/vpnctl` | `none` |
| `vpnrouter` | VPNRouter | `PavelLizunov/VPNRouter` | `none` |

Central returns only the safe public fields `project_id`, `label`, `repository`, `summary`, `aliases` and
`delivery_mode`. The exact dispatch profile and build-1 paths remain server-side. Workspace persists one validated
project ID in an HttpOnly, SameSite=Strict cookie. Telegram either matches an exact alias or durably stores the
original owner goal while asking for one exact registered project name. Replaying a lost project-selection response
returns the same mission receipt instead of accepting a second mission.

The owner command surface is limited to `/projects`, `/mission`, `/status`, `/help` and `/stop`. The command menu,
mission errors and voice failure message are Russian in the deployed runtime. Hidden diagnostics remain callable for
operators but no longer clutter the owner menu or help.

## Live Central and Workspace proof

Flux was explicitly reconciled after PR #303:

```text
GitRepository/uap-platform Ready=True
Kustomization/uap-platform Ready=True
revision=master@sha1:03298bdacbe73a9ab7ffd5d552e24d1a609c7f47
```

The rollout converged to:

```text
deployment=hermes-agent
config-rev=v57-owner-copy
ready=1 updated=1 available=1
pod=hermes-agent-68c659fb88-l47n5
phase=Running ready=true restarts=0
```

Mounted runtime hashes:

```text
23ba06478a1489c1aba7f61c2b49ce4ea134c1e6713cead2e3224dbe6f1036ae  hermes_cli/commands.py
d0d4f335193f976bf633e2e513aa34c85f9ab07d878e3bdf000abcee09a0b592  gateway/run.py
8cce8df0a142014ab8027505820536e1753398245bb9c37aa22fec4f7f344e94  gateway/platforms/api_server.py
bbeb74b5b6dac6625c2d1b2044bd39388c7fa140da388580088df7788ab67c32  hermes_cli/uap_missions.py
```

The live mounted source contains the Russian `Показать разрешённые проекты`,
`не удалось расшифровать голосовое сообщение` and `Не удалось создать задачу` paths.

The live Workspace checkout accepted the exact predecessor fingerprints, applied the overlay, passed the Vite client
and SSR production builds, restarted successfully and returned HTTP 200. Browser verification at
`/settings?section=projects` observed:

```text
heading=Проекты и доступы
projects=Mission Ledger, vpnctl, VPNRouter
loading=false
error=false
selected_project_id=flow-ledger
```

The last value persisted after navigation/reload, proving the server-owned selection cookie path rather than only a
client-side radio state.

## Live build-1 activation proof

The installer passed its exact install and `--check` gates before all timers resumed. Eight coordinator timers are
enabled, including the new persistent profiles:

```text
hermes-delivery-coordinator@vpnctl-registered-v4.timer
hermes-delivery-coordinator@vpnrouter-registered-v4.timer
```

At `2026-07-19 20:25:21 UTC`, both services completed a natural timer tick with:

```text
Result=success
ExecMainStatus=0
```

Installed hashes equal the reviewed source:

```text
c3c2baea7452ea280acd223e35f34f98764da2e4bf2988722dc496d784b74d52  delivery-vpnctl-registered-v4.json
5609423973b2d88ef24ca3c26763fd841c709fba682b4a313103d5dc13ad0a0d  delivery-vpnrouter-registered-v4.json
bce3b92fc43d87d5b755d2e44971098595bd2ed5f4dce8568f77195fa2917046  delivery_coordinator.py
0fdc0e93f9d28782a5b675422f7406a11b72ecf67c3819806f8d8232cc852789  mission_adapter.py
```

The source checkouts were clean and synchronized after a guarded fast-forward of VPNRouter:

```text
vpnctl      02ad996d584daa98bea4e11286018686995c34d9  HEAD...origin/main=0/0
VPNRouter   43649922d489b18665721105ad9aa29cd8768574  HEAD...origin/main=0/0
```

No mission was manually accepted or coordinator tick manually invoked for this proof. The observed coordinator
executions were natural timer reconciliation ticks with no eligible mission.

## Verification gates

The implementation and language follow-up passed:

- Windows `tests/verify-local.ps1` including secret scan, IaC validation, production Kustomize validation and live
  two-node smoke checks: `verify-local-ok`;
- exact pinned Hermes overlay on Linux, including transform fingerprints, bytecode, project intake and tamper checks;
- complete mission runtime regression suite;
- mission deployment and generated ConfigMap checks;
- complete delivery coordinator suite for the implementation PR (`130 tests passed`);
- GitHub required `static-checks`, including every `tests/static/test_*.py`, every `tools/**/test_*.py`, Kustomize and
  gitleaks.

## Voice boundary

The deployed Hermes runtime reports STT enabled and provider `local`, but the runtime capability probe at rollout time
reported:

```text
faster_whisper=false
local_whisper_command=false
openai_audio_backend=false
ffmpeg=true
```

Therefore Telegram voice notes are accepted as owner input only after a successful transcript, while the current
deployment returns a clear Russian retry/text instruction and creates zero mission state. Enabling voice requires a
separately owner-authorized STT credential/backend. ChatGPT/Codex subscription OAuth is not treated as an OpenAI Audio
API credential, and the platform does not silently add a cloud provider, local model or GPU fallback.

## Allowed claims

It is now correct to say:

> For the three registered no-deploy repositories, the owner can select a project in Workspace or name it in an
> ordinary Telegram text goal. The platform creates one durable mission and persistent build-1 timers service it
> without owner CLI, profile, model or checkout parameters.

It is not yet correct to say:

- arbitrary repositories are discovered from natural language;
- complete Workspace/Telegram chat history is replicated;
- Telegram voice transcription has passed a live canary;
- `vpnctl` and `VPNRouter` have each completed a non-toy mission through their new profile;
- any deploy/release boundary beyond explicit `delivery_mode=none` was proved.
