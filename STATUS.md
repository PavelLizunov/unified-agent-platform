# Current Status

Last updated: 2026-07-12

## Phase

- Current phase: **post-Stage 0P** — infra bootstrap done; the **model + agent layers are LIVE** in `uap-system`
  (see "Model & Agent Layer" below). Active direction (2026-06-22/23 **pivot**): **vibe-coding** — adopt the
  external NousResearch **hermes-agent** as the harness (the bespoke `hermes/hermes.py` is parked). See
  `docs/next-steps.md`, `docs/infrastructure.md`, `docs/research/`.
- HA status: **not HA ready and deferred indefinitely by owner decision (2026-07-12)**. Two local k3s VMs
  (one server/control-plane, one agent) = a single etcd member. The active strategy is one control-plane,
  R2 backups, and the verified restore drill; adding a third server is not an active owner action.
- k3s status: **local bootstrap running on `uap-home-1` with `uap-home-2` joined as an agent**.
- **Cross-node Secret restore: PASS 2026-07-12.** A snapshot created after a throwaway canary Secret was fetched
  back from R2 and restored on clean `debian-xfce` with only the snapshot + original server token. The snapshot
  supplied the encryption config automatically and the Secret value matched byte-for-byte. All canary resources,
  credentials, k3s state and the test snapshot were removed; production and the target returned healthy.
- **Brain reality (current, since 2026-07-11):** the live hermes-agent brain is **Codex `gpt-5.6-luna`** through
  `codex_app_server` (`provider: openai-codex`). Owner device-auth restored the ChatGPT-Plus OAuth lineage; an
  explicit in-pod Luna probe returned `LUNA-PROBE-OK`. The ops-1 `qwen-35b`/`ornith-9b` local-models-router, which served as
  brain from 2026-07-06 through 2026-07-11, remains the documented manual fallback. Coding delegation stays on build-1.
- ✅ **Quality gate is ENFORCED.** The owner does not review code; the agent's self-test + CI **is** the gate, and it
  is now enforced. The repo is **public**, the GitHub ruleset `protect-master` is **active**, a PR is **required**, and
  the `static-checks` CI check (`.github/workflows/ci.yml`) is a **required (strict) status check** — direct push to
  `master` is **BLOCKED**. Deploys are PR-gated: branch → PR → green `static-checks` → merge → Flux reconciles `master`
  (`prune:true`). Human code review remains absent by design. See `docs/next-steps.md` (Platform hardening).
- **Post-A4 hardening pass — DONE 2026-06-28** (against the Codex bug-hunt, `BUG-HUNT-CODEX-2026-06-28.md`).
  8 items **merged** (each independently reviewed): secret-scan SOPS hole (structural `ENC[` check +
  provider-token patterns + fixtures now run in CI), backup completeness (root dump, no pipe-masking,
  expected-file manifest), this doc-set's drift, `hermes-legacy` **parked** + documented, `validate_iac`
  orphan path-bug, `verify-local` `-Require` (false-green), `configure-github-flux.sh` ADR-026 alignment,
  and a PV-`Retain` DR live-smoke (`tests/ops/check-pv-reclaim.ps1`). **#35** (pin hermes-agent runtime —
  image digest = v0.17.0, `codex@0.142.0`, `claude@2.1.193`, rclone digest — + harden: no-RBAC SA,
  `automountServiceAccountToken:false`, seccomp RuntimeDefault, TCP probes) and **#36** (harden
  `singbox-egress-ha`: drop-all-caps, seccomp, no-RBAC SA, TCP probes) are **MERGED + live** (owner-merged
  2026-06-30, rolled and verified — see the follow-up below). `runAsNonRoot`/cap-drop on the agent pod
  remain deferred + documented (s6 needs root; Codex runs danger-full-access).
- **2026-06-30 follow-up:** caught and fixed a real regression before the owner could hit it — PR #35 was
  branched before #38 merged and reverted #38's warn-not-fatal backup fix back to FATAL ("root avoids
  skips" is false: `hermes backup` drops to uid 10000 internally regardless of dump-container privileges).
  GitHub's mergeable check was stale (computed pre-#38); a local rebase surfaced the real conflict. Pushed
  a correction onto `chore/pin-harden-hermes-agent` (commit `dafa3f9`) that keeps #38's logic and only the
  legitimate digest pins — **PR #35 is now MERGEABLE + green, still owner-gated.** PR #36 was unaffected
  (no file overlap). Also committed the 3 local-only Codex audit docs that never made it into git (PR #39,
  merged) and closed the doc gaps they exposed: a stale CLAUDE.md bug-hunt pointer, and a 5th hermes-legacy
  finding (summarizer drops the untrusted-tool-result boundary) missing from `hermes/README.md`'s
  accepted-as-parked-risk list. Ported the BOM-proof base64 SSH transport to `check-ops-node.ps1` /
  `check-ops-deploy-path.ps1`, and in the process found it had also silently broken the already-merged
  `check-pv-reclaim.ps1`: `.gitattributes` forces `*.ps1` to CRLF on a Windows checkout, and the stray
  `\r` corrupts the remote bash parse. Fixed all three by stripping CR before base64-encoding (PR #40,
  merged). Also added (owner-approved): seed-if-absent install of the
  [ponytail](https://github.com/DietrichGebert/ponytail) anti-overengineering coding skill (native Hermes
  plugin, `full` mode) into hermes-agent's boot initContainer — bundled into PR #35 rather than a
  competing PR on the same file. Dependabot #1-4 (SHA-pin Actions) still open; not yet actioned.
- **2026-06-30 PR #35/#36 merged + rolled — post-roll verify DONE.** `hermes-agent`: pod 1/1 Running,
  `hermes --version`/`codex --version`/`claude --version` match the pins exactly, dedicated SA +
  `automountServiceAccountToken:false` live, `tests/ops/check-pv-reclaim.ps1 -Require` →
  `pv-reclaim-ok`, ponytail installed at `/opt/data/plugins/ponytail` and **enabled** on first real boot
  (`hermes plugins list` confirmed it then). On 2026-07-12 it was found installed but disabled, so the owner chose
  to remove the dead plugin/bootstrap and retain only two concise managed coding/report rules. `claude -p` verified
  working end-to-end. `singbox-egress-ha`: pod
  1/1 Running, `sing-box check` valid, reachability confirmed from inside hermes-agent (telegram=302,
  chatgpt=403 — the expected signature). The Codex OAuth later expired because of its single-use refresh-token
  lineage; the local router carried the brain from 2026-07-06 until owner device-auth restored Codex on 2026-07-11
  (#119). `claude -p` uses separate OAuth and was unaffected.
- **Egress ops hardening — DONE 2026-07-10** (the vpnrouter-gateway goal, `docs/research/vpnrouter-gateway-egress-goal.md` §10).
  Phase 0 verdict (#107): `vpnrouter-gateway` is a TUN/L3 LAN gateway — it cannot render our HTTP-CONNECT-proxy
  egress (no `mixed`/`:12080` inbound, no `urltest`, always emits `direct`), so Level 1/2 adoption = no-go; the
  dependency-free alternative was adopted instead. Shipped: **SNI pre-flight gate** in
  `infra/sops/gen-singbox-failover.py` (#108) — `--against <deployed>` diffs fresh-vs-deployed servers keyed by
  `(host, port)` (the subscription renames nodes), FAILS CLOSED (exit 3) on any REALITY `server_name` change or
  pool add/remove; ack = `--allow-sni-drift` / `ALLOW_SNI_DRIFT=1`; regression test in CI (`tests/static/`).
  **Decrypt-verify guard** in the regen runbook (#109) — the freshly-encrypted `.sops.yaml` is piped into
  `sops -d` on `uap-home-1` BEFORE the PR, so a transport-corrupted secret fails locally instead of as Flux
  "no identity matched" post-merge. **First real rotation through the new pipeline (#110):** the gate caught the
  deployed pool lagging the subscription (+United States VLESS), acked → 7-server secret + `config-rev`
  v3-7servers → Flux rolled the pod → verified live from build-1 through the new pod (telegram=302,
  anthropic=401, exit IP non-RU); hermes Telegram long-poll auto-reconnected with no escalation. The 2026-07-09
  incident class (silent SNI drift, corrupted secret transport, blind config edit) is now surfaced/blocked at
  authoring time.

## Proxmox

- Endpoint: `https://192.168.0.169:8006/` (local LAN only).
- Proxmox version observed: `8.4.1`.
- Online nodes:
  - `pve-ninitux`
  - `pve-ninitux3`
- Offline node observed:
  - `pve-ninitux2`
- Shared storage used: `nfs-share`.
- Bridge used: `vmbr0`.
- Storage change made: `nfs-share` content types now include `import` so cloud images can be imported.

## Local VMs

| VMID | Name | Proxmox node | IP | Resources | Status |
|---|---|---|---|---|---|
| 201 | `uap-home-1` | `pve-ninitux` | `192.168.0.201` | 4 vCPU, 8 GB RAM, 80 GB disk | running |
| 202 | `uap-home-2` | `pve-ninitux3` | `192.168.0.202` | 6 vCPU, 8 GB RAM, 32 GB disk | running |
| 203 | `uap-ops-1` | `pve-ninitux` | `192.168.0.203` | 2 vCPU, 2 GB RAM, 30 GB disk | running |
| 102 | `uap-build-1` | `pve-ninitux3` | `192.168.0.99` | 8 vCPU, 16 GB RAM, 100 GB disk | running |

`uap-home-2` was resized to 6 vCPU / 8 GB (#86/#87). `uap-build-1` (VMID 102) is an **always-on Ubuntu 22.04 dev/build
VM** — **not a k3s node and not in GitOps**; it hosts the build-1 track services (see "Build-1 track" below).

## Tailnet

| Device | Tailnet name | Tailnet IP |
|---|---|---|
| `uap-home-1` | `uap-home-1.tail9fd337.ts.net` | `100.106.223.120` |
| `uap-home-2` | `uap-home-2.tail9fd337.ts.net` | `100.94.228.67` |
| `uap-ops-1` | `uap-ops-1.tail9fd337.ts.net` | `100.82.241.121` |
| `uap-build-1` | `uap-build-1.tail9fd337.ts.net` | `100.85.56.31` |
| Windows | `desktop-m922ij2.tail9fd337.ts.net` | `100.114.172.40` |
| Mac | `pavels-mac-mini.tail9fd337.ts.net` | `100.116.97.112` |

## VM Baseline

- OS: Debian 12 (bookworm).
- User: `uap`.
- SSH keys: from `infra/ssh/agent-authorized-keys.pub`.
- SSH hardening:
  - `PasswordAuthentication no`
  - `PermitRootLogin no`
- `sudo -n true`: verified for user `uap`.
- `qemu-guest-agent`: installed and active.
- Tailscale: installed and authenticated.

## k3s

- Server installed on: `uap-home-1`.
- Agent installed on: `uap-home-2`.
- Version: `v1.35.5+k3s1`.
- Runtime: `containerd://2.2.3-k3s1`.
- Server internal IP: `100.106.223.120`.
- Agent internal IP: `100.94.228.67`.
- Config tracked at:
  - `infra/k3s/uap-home-1.config.yaml`
  - `infra/k3s/uap-home-2.agent.config.yaml`
- Local credential file: `kubeconfig.uap-home-1` (ignored by git).
- System pods verified Ready:
  - `coredns`
  - `local-path-provisioner`
  - `metrics-server`
- Smoke deployment verified with `registry.k8s.io/pause:3.10`.
- `uap-home-2` can reach `uap-home-1:6443` over tailnet.
- Scheduling on `uap-home-2` verified with a targeted `registry.k8s.io/pause:3.10` pod.
- Reboot test: passed. `uap-home-1` rebooted and k3s returned Ready.
- Manual etcd snapshot created and listed:
  - `uap-local-20260617T134555Z-uap-home-1-1781703956`
  - size: `1646624` bytes

## GitOps

- Flux installed: `v2.8.8`.
- Runtime controllers installed:
  - `source-controller`
  - `kustomize-controller`
  - `helm-controller`
  - `notification-controller`
- Image automation controllers are intentionally not installed.
- Flux manifests are pinned in `clusters/prod/flux-system/gotk-components.yaml`.
- SOPS/age configured:
  - public recipient stored in `.sops.yaml`;
  - private age key stored outside git on `uap-home-1`;
  - Kubernetes Secret: `flux-system/sops-age`.
- SOPS CLI installed on `uap-home-1`: `v3.13.1`.
- SOPS smoke fixture: `clusters/prod/infra/sops-smoke.sops.yaml`.
- SOPS decrypt smoke: passed with the node-local age key.
- Namespace applied from skeleton:
  - `uap-system`
- Flux Git sync **active**: `GitRepository` + `Kustomization` `uap-platform` reconcile `clusters/prod` from the
  GitHub remote via a read-only SSH deploy key + SOPS decryption. First real SOPS secret applied by Flux:
  `k3s-etcd-snapshot-s3-config` in `kube-system`.

## Model & Agent Layer (LIVE — 2026-06-23)

The model + agent value layers are deployed in namespace `uap-system`. **All of them are now Flux-reconciled**
(verified against `clusters/prod/infra/kustomization.yaml`): `litellm.yaml`, `litellm-keys.sops.yaml`, `hermes.yaml`,
`hermes-keys.sops.yaml`, and every hermes-agent manifest are referenced by the kustomization. **B0 is DONE.**

- **subfleet** (Flux-managed): wraps the **Claude subscription** as an OpenAI-compatible **chat** API (spawns the
  bundled `claude` CLI per request; drops `tools`/`tool_calls`). `subfleet-bridge.uap-system.svc:18902`. Egress to
  Anthropic via the in-cluster `singbox-egress` (VLESS+REALITY, ADR-018). Retained for the owner's **other**
  projects (a Telegram bot + web sessions); redundant for in-repo coding (which uses `claude -p` directly).
- **LiteLLM** v1.89.0 — deployed + smoke-verified, **Flux-reconciled** (`clusters/prod/infra/litellm.yaml` +
  `litellm-keys.sops.yaml` are now referenced by the kustomization). OpenAI gateway, groups
  `smart-cloud`/`-think`/`balanced-cloud`/`cheap-cloud`/`smart-cloud-pinned`; tailnet via `tailscale serve` on
  `uap-home-1`; `opus-4-8` verified end-to-end.
- **Hermes-legacy** (bespoke `hermes/hermes.py`) — deployed + smoke-verified, now **Flux-reconciled** (`hermes.yaml`
  + its `hermes-keys` SOPS Secret are referenced by the kustomization). Prompt-based ReAct/ReWOO tool agent,
  NodePort `:30890`, 41 unit + 8 integration tests. **PARKED** — superseded by the external hermes-agent direction.

LiteLLM/Hermes and the hermes-agent stack are now *running + verified* **and** *reconciled by GitOps* — **B0 is DONE**
(see `docs/next-steps.md`).

## Local FC Brain — Track A1 (PROVEN 2026-06-23)

Phase A1 of the hermes-agent pilot: a **local, native-function-calling** brain on the RTX, no cloud egress.

- **Host:** `desktop-m922ij2` (RTX 5060 Ti 16 GB, Blackwell sm_120, driver 610.62 / CUDA 13.3); **not always-on**, so
  this brain is **opportunistic** (the live durable brain is now the ops-1 local-models-router — `qwen-35b`/`ornith-9b`;
  see "Brain reality" in Phase).
- **Stack:** **Ollama 0.16.1** (native Windows) serving **`gpt-oss:20b`** — already on disk, so **no model download
  over the RU network**. Chosen over a fresh Hermes/Qwen pull for that reason; `--tool-call-parser hermes` (vLLM) /
  `--jinja` (llama.cpp) are the equivalents if a Hermes/Qwen GGUF is swapped in. **WSL2/Docker are NOT installed**, so
  vLLM-in-WSL2 is deferred (heaviest path).
- **Proof (the A1 "Done" gate):** against `http://127.0.0.1:11434/v1/chat/completions` with a `tools` array, the model
  returns a **structured `tool_calls`** object — `get_weather({"city":"Paris"})`, `finish_reason=tool_calls` — **not
  text**; feeding the tool result back yields a correct final answer (`finish_reason=stop`); a bare greeting yields
  **no** tool call. Served `context_length=65536` (>= 64k), **100% GPU**, ~14.7 GB VRAM (`/api/ps`).
- **Reproduce:** `powershell -ExecutionPolicy Bypass -File .\tests\smoke\local-fc-toolcall.ps1 -StartOllama` →
  `local-fc-toolcall-ok`. Runbook: `runbooks/local-fc-model.md`.
- **Not yet done (Phase A2):** running hermes-agent itself against this endpoint (bind Ollama to the tailnet +
  `security.allow_private_urls: true` for the CGNAT `100.64/10` range). A1 proves the *endpoint contract*, not the
  hermes-agent startup/run.

## hermes-agent — Track A2 (DEPLOYED + verified 2026-06-24)

Phase A2: the external NousResearch **hermes-agent** gateway as a Flux-managed k3s workload, brain = the **Codex /
ChatGPT-Plus subscription** (`codex_app_server`) reached through `singbox-egress`. Owner chose the GitOps/k3s path
over bare Docker.

> **Current again since 2026-07-11 (#119).** Codex `gpt-5.6-luna` is the live brain after owner re-auth and the
> owner's cost-sensitive model switch. The local
> `qwen-35b`/`ornith-9b` interval (2026-07-06 through 2026-07-11) proved the manual fallback path; its router and
> runbook remain available. See "Brain reality" above.

- **Proven in the real image (2026-06-24):** running `nousresearch/hermes-agent:latest` (v0.17.0) in-cluster,
  `hermes chat -q` drove the Codex brain (gpt-5.5) to **execute a tool end-to-end** (wrote a `BRAIN-OK` file). The
  Codex subscription reaches OpenAI through the cluster egress (chatgpt.com); raw `curl` probes are unfaithful
  (Cloudflare resets curl's TLS fingerprint, not the real Rust codex CLI).
- **Deployed via Flux (PR #8, merged):** `Deployment hermes-agent` in `uap-system` is **1/1 Running** on
  `uap-home-2` (manifests `clusters/prod/infra/hermes-agent{,-config}.yaml` + the SOPS `codex-auth.sops.yaml`, all
  in the kustomization). The bootstrap initContainer (codex install onto the PVC + cred seed into hermes's OWN auth
  store + chown to uid 10000) succeeded; the gateway runs persistently (no messaging platform yet — that's A3). The
  4 non-obvious knobs (creds in hermes's own store, not `~/.codex`; `codex_app_server`; codex `danger-full-access`;
  uid-10000 + egress env) are in `runbooks/hermes-agent-codex-brain.md`.
- **Owner action done:** `codex login` on the desktop with the owner's own ChatGPT Plus → `~/.codex/auth.json`,
  which seeds the `codex-auth` secret.
- **Verified (A2 Done):** the `kubectl exec` round-trip **in the deployed pod** wrote `BRAIN-OK` — the brain
  (gpt-5.5) executed a tool through the egress.
- **A3 (Telegram) DONE 2026-06-24:** a message from the owner's phone round-trips through the gateway to the Codex
  brain (gpt-5.5) and back ("17×23 = 391") — the harness is now **phone-driven** (PR #10). The fix was non-obvious:
  hermes's per-profile `os.environ` is isolated (multiplex), so the egress proxy + Telegram allowlist had to go in
  hermes's **managed scope** (`/etc/hermes/.env`, loaded last with override) — which also feeds the gateway-driven
  Codex brain (codex spawn = `os.environ.copy()`). See `runbooks/hermes-agent-codex-brain.md`. **Next: A4** (coding
  skills — `claude -p` / `codex exec` — the actual vibe-coding gate).
- **Caveat:** the seed shares the Codex CLI's single-use refresh-token lineage — see the runbook (rotate/re-seed if
  the brain starts 401-ing). Hardening follow-ups: non-root, pinned GHCR image, autonomous-run permission policy.
- **Config-ownership hybrid DONE 2026-06-25 (PR #16, merged):** GitOps owns only the brain via a **managed config
  overlay** (`/etc/hermes/config.yaml`, ConfigMap key `managed-config`) that deep-merges per-leaf over the PVC config
  and WINS — `hermes config` now reports `Managed config keys: model.{provider,openai_runtime,model}` and refuses
  dashboard/CLI edits to them ("managed by your administrator"). The initContainer no longer clobbers the PVC every
  boot: `config.yaml` + codex `config.toml` are **seed-if-absent** and the bot token is **replaced in-place**
  (preserving dashboard-written `.env` lines — Discord/MCP tokens, `/sethome` chat-IDs — across restarts). A
  fail-closed guard aborts boot if the managed brain overlay is missing/malformed. So the **dashboard is now a
  durable self-serve surface** for soft config while the brain stays reproducible. Independently reviewed; pod rolled
  once to `v5-config-hybrid`, healthy. See the "Config ownership" section in `runbooks/hermes-agent-codex-brain.md`.
- **PVC DR backup DONE 2026-06-25 (PR #17, merged):** the node-local `hermes-agent-data` PVC (NOT in the etcd→R2
  snapshots) now has a daily **`CronJob hermes-agent-backup`** — FULL `hermes backup` (consistent sqlite snapshot,
  incl. the `.codex` brain DBs) → `r2:uap-k3s-snapshots/hermes-agent-backup/`, keep-7, direct to R2 (so it works
  while the egress is down). Fail-loud integrity guards (non-empty + valid zip + `.codex` present). PV flipped to
  `reclaimPolicy: Retain`. **Verified:** a manual job shipped a 40MB zip to R2. Restore + hardening follow-ups
  (client-side encryption; current shared R2 credential scope is an owner-accepted risk) in
  `runbooks/hermes-agent-dr.md`.
- **Egress outage RESOLVED 2026-06-25 (PR #19, merged) — HA failover egress.** The single German VLESS+REALITY exit
  had died server-side (`singbox-egress` logged `EOF` to chatgpt.com/api.telegram.org/ipify/dns alike), taking the
  Codex brain + Telegram offline. Fix: a **separate `singbox-egress-ha`** (Deployment + Service + SOPS config) running
  sing-box with a **`urltest`** outbound that auto-fails-over across the owner's **6-server** subscription (3 VLESS+REALITY
  + 3 WS+TLS `*.ninitux.top`, the WS exits more DPI-resistant; PR #21, verified 6/6 + `BRAIN-OK-6`) —
  probe every 30s, route the fastest LIVE server, migrate in-flight connections off a dead one; **no `direct` outbound**
  (no RU-origin leak). hermes-agent (brain + Telegram) is repointed at it (config-rev `v6-egress-ha`). **subfleet stays
  on the single-fixed `singbox-egress` (untouched)** — its OAuth is IP-pinned and must NOT sit behind a rotating egress.
  Regenerate the server list with `infra/sops/gen-singbox-failover.py` (see `runbooks/llm-egress-vless.md`). **Verified:**
  `sing-box check` valid + 12/12 live reachability (telegram 302 / chatgpt 403) pre-deploy; in-cluster the **brain
  round-trip wrote `BRAIN-OK`** and Telegram reconnected. Per-server probe: Iceland rock-solid, Germany good, Netherlands
  dead (urltest excludes it). Independently reviewed (the split fixed a subfleet IP-pin blocker).
- **subfleet egress note (updated 2026-07-09):** subfleet is **LIVE + healthy** (v0.3.1; bridge + token pods 1/1
  Running; served `claude-opus-4-8` on 2026-07-09 through the pinned `singbox-egress`). Its dead German exit was
  **rotated to a live ninitux server** (#103/#104). subfleet stays on the **single-fixed `singbox-egress`** (NOT the
  rotating HA egress) because its Claude OAuth is IP-pinned. **Only genuinely-open caveat:** the exit-IP change means the
  IP-pinned OAuth pin may need re-validation (re-run `claude setup-token` from the new exit IP) if it starts failing —
  verify on the next auth error rather than pre-emptively. Do NOT fold subfleet onto the rotating HA egress.
- **A4 (claude -p coding worker) DONE 2026-06-26 (PR #23):** Anthropic's `claude` CLI runs as an autonomous
  `claude -p` worker INSIDE the hermes-agent pod, alongside the Codex brain. Claude Max OAuth (a portable 1-year
  `claude setup-token`) was obtained via a **server-side device-flow** (run in the pod under a PTY through the egress;
  owner clicked the URL + pasted the code), stored in the SOPS secret `hermes-agent-claude`, injected as env
  `CLAUDE_CODE_OAUTH_TOKEN`. The claude CLI installs in the initContainer (seed-if-absent, mirrors codex); deny-first
  `/opt/data/.claude/settings.json` is defense-in-depth (the pod is the real boundary, Bash is unconstrained).
  **Verified in-cluster:** `claude -p` returns a result through the egress with the secret-injected token, and the
  deny rule blocks a decoy secret read. Recipe + gotchas in memory `uap-claude-worker`; config-rev `v7-claude-worker`.
- **A5 coding engines + worktree isolation — verified 2026-06-26:** BOTH coding engines work in-cluster —
  `codex exec "<task>"` (the 2nd engine, via the Codex auth + egress) edits files autonomously, and `claude -p -w <name>`
  runs in an **isolated git worktree** (`.claude/worktrees/<name>`, its own branch) so a coding task never touches the
  main checkout.
- **NORTH-STAR MILESTONE — A4 demo PASSED 2026-06-26 (PR #25):** the hermes-agent `claude -p` worker autonomously
  shipped a real change (a kustomization-orphan check in `validate_iac.py` + its test, 10 turns / $0.63) in an isolated
  git worktree, **self-verified** (its own test + `validate_iac` green), and it landed in `master` via the required
  `static-checks` CI — **with NO human diff review**. The thesis is proven: the worker's self-test + the enforced CI
  is the quality gate, not human review. (This run was orchestrated — task chosen + worker invoked via `kubectl exec`
  + the patch bridged to ops-1 for the push. The remaining AUTOMATION is wiring a phone message → hermes → worker →
  ops-1 push so the whole loop runs unattended from the phone.)

## Build-1 track (post-2026-06-30)

`uap-build-1` (VMID 102, `pve-ninitux3`, Ubuntu 22.04, 8c/16 GB/100 GB, LAN `192.168.0.99`, tailnet `100.85.56.31`) is
an **always-on dev/build VM** running a stack of agent services as **systemd units — NOT k3s, NOT in GitOps**, so they
are absent from the cluster sections above. Landed after the 2026-06-30 hardening pass:

- **local-models-router (#71)** — the ops-1 router that served `qwen-35b`/`ornith-9b` as the live brain from
  2026-07-06 through 2026-07-11 and remains the manual fallback (see "Brain reality" in Phase);
  `runbooks/local-models-router.md` + `docs/local-qwen-hermes-handoff.md`.
- **Knowledge system (#95/#96/#97)** — SQLite `knowledge.db` engineering-knowledge registry + local e5-large
  embeddings + a 12-status lifecycle with `--approve` gates; `runbooks/knowledge-system.md`.
- **Hermes Kanban swarm pilot (#94/#98/#99)** — native multi-agent orchestration (KB → swarm → artifacts → verify →
  synth → KB write-back, retrieval-first); `runbooks/hermes-kanban-swarm-pilot.md`.
- **hermes-workspace webcenter (#101)** — the user-facing web center on `build-1:3000` (tailnet-only).
- **ai-search (#105)** — zero-key web-search CLI (DuckDuckGo via the VLESS proxy; exa/tavily/brave opt-in from a key
  file); `runbooks/ai-search.md`.
- **Egress ops hardening (#108/#109/#110)** — SNI pre-flight gate + decrypt-verify guard + first gated rotation through
  the new pipeline (also summarised in the "Egress ops hardening — DONE 2026-07-10" bullet under Phase).
- **Proxy-mode spec (#112)** — the vpnrouter-gateway proxy-mode handoff spec (`docs/research/`).

## Repeatable Bootstrap

- OpenTofu/Terraform-compatible provisioning skeleton added under `infra/tofu`.
- Local Proxmox environment described at `infra/tofu/environments/local-proxmox`.
- Proxmox VM module added at `infra/tofu/modules/proxmox-vm`.
- Ansible bootstrap skeleton added under `infra/ansible`.
- Current local inventory: `infra/ansible/inventories/local.yml` uses tailnet IPs for SSH and keeps LAN IPs as metadata.
- Future 3-server template inventory: `infra/ansible/inventories/prod.example.yml`.
- Parameterized smoke-test config: `tests/smoke/uap-smoke-config.ps1`.
- Static IaC validation: `tests/static/validate-iac.ps1`.
- Unified local gate: `tests/verify-local.ps1`.
- Secret scan: `tests/static/secret-scan.ps1`.
- Validation matrix: `runbooks/validation-matrix.md`.
- Local FC brain runbook (Track A1): `runbooks/local-fc-model.md`.
- Local FC tool-call smoke test (opportunistic, GPU desktop): `tests/smoke/local-fc-toolcall.ps1`.
- Restore drill runbook: `runbooks/restore-drill.md`.
- Offsite backup runbook: `runbooks/offsite-backups.md`.
- Flux remote Git runbook: `runbooks/flux-remote-git.md`.
- Cloudflare R2 setup runbook: `runbooks/cloudflare-r2-k3s-snapshots.md`.
- Git remote readiness helper: `tests/git/check-git-remote.ps1`.
- S3 env readiness helper: `tests/s3/check-s3-env.ps1`.
- Operator node runbook: `runbooks/uap-ops-node.md`.
- Operator node bootstrap script: `infra/ops/bootstrap-ops-node.sh`.
- GitHub + Flux sync helper for the operator node: `infra/ops/configure-github-flux.sh`.
- Operator node readiness helper: `tests/ops/check-ops-node.ps1`.
- Operator deploy-path helper: `tests/ops/check-ops-deploy-path.ps1`.
- `uap-ops-1` deploy tools installed and verified:
  - `git`
  - `ansible-playbook`
  - `tofu`
  - `kubectl`
  - `flux`
  - `sops`
  - `age`
  - `gh`
  - `tailscale`
  - `jq`
- `uap-ops-1` SSH key generated on the VM and authorized on `uap-home-1` and `uap-home-2`.
  - public key fingerprint: `SHA256:fJ6yGmMjF6Mk7NC3OXqmcRu5u5h0Tp88DhglVqLJmDU`
- `uap-ops-1` is authenticated in Tailscale as `100.82.241.121`.
- LAN SSH to `uap-ops-1` is verified. Tailnet SSH to `uap-ops-1` was intermittently timing out immediately after
  enrollment, so `tests/ops/check-ops-node.ps1` still defaults to LAN until tailnet SSH is stable.
- `uap-ops-1` has a node-local kubeconfig at `~/.kube/config` with mode `0600`. The kubeconfig is not stored in git.
- `kubectl` from `uap-ops-1` can read k3s nodes and Flux deployments through the tailnet API endpoint.
- `uap-ops-1` can SSH to `uap-home-1` and `uap-home-2` over tailnet, so it is usable as the deploy/control machine.
- The ops-node git copy now has the GitHub `origin` (set up via `configure-github-flux.sh`); `master` is pushed and Flux syncs from it.
- Local workstation currently does not have `tofu`, `terraform`, or `ansible` installed, so static validation skips
  those CLI-specific checks unless the tools are installed.

## Git Remote Readiness

- GitHub `origin` configured (**public** repo `PavelLizunov/unified-agent-platform`; read-only SSH deploy key for Flux,
  plus a repo-scoped read-WRITE deploy key for pushes — both live on `uap-ops-1`); `master` pushed; `gh` authed on
  `uap-ops-1`. Direct push to `master` is blocked by the `protect-master` ruleset — deploys are PR-based (see Phase).
- The Windows workstation has a **read-only** `origin` (the public GitHub URL, added when the repo went public) for
  `git fetch`/sync only; pushes still route via `uap-ops-1` (the write deploy key lives there).
- `infra/ops/configure-github-flux.sh` was run on `uap-ops-1` to create the repo, push, add the deploy key, and create the Flux git-auth secret.
- Local Windows SSH public key exists:
  - fingerprint: `SHA256:YLFbDMRbeUldpLQW8dmMihAQbRgCVBhmQGTW98rgm9c`
  - comment: `windows`
- GitHub and Bitbucket did not accept that key during the last SSH probe.
- Windows tailnet IP `100.114.172.40` responded to ping, but TCP `22` was not listening during the last check.
- Flux Git sync is enabled and reconciling (see GitOps section).

## Pending

Canonical list: `BACKLOG.md`. Highest-impact open items under the current single-control-plane strategy are
off-homelab age-key escrow, Proxmox VM backups and owner retrieval of the staged Vaultwarden admin token. The third
k3s server / HA failover path is deferred indefinitely for budget and is not an active owner action. R2 credential
scope/lifecycle are accepted as-is by owner decision.

## Plan Fact-Check (2026-06-18)

BUILD-PLAN / ARCHITECTURE / DECISIONS were fact-checked against current (June 2026) reality. Corrections applied
to the design docs only (no infra change yet):

- **Object storage:** MinIO community edition was archived (Feb 2026, no patches) -> replaced by **Garage** (ADR-019).
- **Restate storage:** the "durable journal -> Postgres" mapping was wrong -> Restate uses an embedded log + local
  RocksDB + async S3 snapshots (Garage), not Postgres (ADR-020).
- **RU egress:** Anthropic/OpenAI/OpenRouter are unreachable from Russia -> new egress ADR (ADR-018; VLESS+REALITY
  or a non-RU LiteLLM node). New risks RISKS #15/#16.
- **k3s-over-Tailscale:** flannel-over-`tailscale0` confirmed (native `--vpn-auth` still experimental) -> ADR-021;
  `--advertise-address` added to the Stage-1 command.
- **Budget VPS:** 1 vCPU / 1 GB is half the k3s server minimum; etcd idles ~1.4-1.6 GB (RISKS #9 hardened).
- Confirmed current/healthy: k3s v1.35.5, Flux v2.8.8 (CNCF Graduated), SOPS v3.13.1, OpenTofu 1.12.2,
  CloudNativePG (pin >=1.29.1), Restate v1.6.x (runtime BSL / SDK MIT), Hermes Agent, Mission Control v2.0.1.

## Offsite Backups (2026-06-19)

- k3s etcd-s3 enabled on uap-home-1 -> Cloudflare R2 (EU jurisdiction), bucket uap-k3s-snapshots, folder prod.
- S3 creds: SOPS secret clusters/prod/infra/k3s-etcd-snapshot-s3-config.sops.yaml, applied to kube-system by Flux.
- Verified: snapshot uploaded to R2 (prod/uap-r2-verify-...); scheduled snapshots auto-upload. Retention: the
  `etcd-snapshot-retention` value (7) is LOCAL-disk; k3s prunes SCHEDULED S3 snapshots too, but MANUAL/on-demand R2
  snapshots are NOT auto-pruned. Owner accepted the current no-lifecycle policy on 2026-07-12; the prior
  "retention 7" claim for all R2 objects was inaccurate.
- Verified 2026-07-12: the canary cross-node drill restored from an R2-fetched snapshot on a clean host and read
  back the encrypted Secret value using only the snapshot + original server token. A separate
  `encryption-config.json` was not required. The test namespace, snapshot and disposable k3s state were removed.
- R2 reachable directly from RU via the EU endpoint (no proxy needed for backups).
- Operator-node services (ad-hoc on uap-ops-1, NOT yet in GitOps): sing-box VLESS egress, Vaultwarden. Flagged as a
  blast-radius/SPOF + secrets-at-rest concern in REVIEW-CODEX.md; migrate into the cluster (Stage 3) or back up +
  document with a recovery runbook.

## Cross-Review Remediation (REVIEW-CODEX.md, 2026-06-19)

Done:
- ops-1 live secrets perms tightened (Vaultwarden `rsa_key.pem` 0644->0600, `~/.config/gh` 0755->0700).
- Stale handoff docs corrected (CLAUDE.md Git Remote Readiness; restore-drill encryption-config theory softened to a
  canary TODO; R2-retention wording).
- Ansible k3s playbooks now converge: notify-restart on config/token change + version-aware install (not binary-only).
- BUILD-PLAN Stage 2: honest HA milestone (node-loss test vs pod-delete) + version-pin requirements.
- ops-1 services backup LIVE: `ops-backup.timer` (systemd --user) daily age-encrypted archive of Vaultwarden +
  `~/.secrets` + units -> `r2:uap-k3s-snapshots/ops-backup/`; first run verified. See
  `runbooks/uap-ops-services-backup.md`.
- #3 GitHub least-privilege: broad `gh` OAuth token removed from ops-1; pushes now use a repo-scoped read-WRITE SSH
  deploy key (origin = SSH), push/fetch verified. Branch protection is now **APPLIED**: the repo was made **public**,
  the ruleset `protect-master` is **active** (PR required + the `static-checks` CI check required/strict), and direct
  push to `master` is **blocked**. The CI gate (`.github/workflows/ci.yml`) is therefore an **enforced required check**,
  not just a signal (see `docs/next-steps.md` → Platform hardening). DONE.
- #4 Vaultwarden rotated: admin token regenerated and stored as an Argon2 PHC hash in `.env` (no longer plaintext);
  RSA identity key regenerated (0600). New admin token staged at `~/vaultwarden/admin-token.NEW.txt` on ops-1 for
  owner retrieval (move to a password manager, then delete).
- #9 cross-node Secret restore passed on 2026-07-12; snapshot + original token restored the exact canary value.
- Owner accepted the current R2 credential scope and lifecycle as-is on 2026-07-12; do not rotate automatically.
- #11 kubeconfig permissions hardened on 2026-07-12: the live unquoted `0644` value had been interpreted as mode
  `0420`; the authoritative config is now the quoted string `"0600"`, the live kubeconfig is `root:root` mode `0600`,
  and k3s plus both nodes remained healthy without a service restart. Static validation prevents regression.
- #11 LAN firewall hardened on 2026-07-12: the boot-persistent `uap-k3s-lan-firewall.service` drops LAN ingress to
  `6443/tcp`, `10250/tcp`, and `8472/udp`. A timed-rollback canary and the durable deployment both kept tailnet API
  and kubelet access open; both nodes, metrics, and workloads remained healthy. LAN DROP counters were observed.

Pending (owner action): independent off-homelab age-key escrow (verify decrypt); retrieve the staged Vaultwarden
admin token; optional — revoke the old "GitHub CLI" OAuth grant in GitHub settings. HA/VPS work is deferred
indefinitely for budget and resumes only after a new owner decision.
