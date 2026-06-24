# Current Status

Last updated: 2026-06-23

## Phase

- Current phase: **post-Stage 0P** — infra bootstrap done; the **model + agent layers are LIVE** in `uap-system`
  (see "Model & Agent Layer" below). Active direction (2026-06-22/23 **pivot**): **vibe-coding** — adopt the
  external NousResearch **hermes-agent** as the harness (the bespoke `hermes/hermes.py` is parked). See
  `docs/next-steps.md`, `docs/infrastructure.md`, `docs/research/`.
- HA status: **not HA ready**. Two local k3s VMs (one server, one agent) = a single etcd member; a third
  independent server + a failover drill are still required.
- k3s status: **local bootstrap running on `uap-home-1` with `uap-home-2` joined as an agent**.
- ⚠️ **Quality gate is NOT enforced.** The owner does not review code, yet `tests/verify-local.ps1` runs only on
  manual invocation and Flux reconciles whatever lands on `master` (`prune:true`). A GitHub Actions CI gate
  (`.github/workflows/ci.yml`, job `static-checks`) was added 2026-06-23 as a **signal** (green on `6494e97`), but
  it is **not a required check** — rulesets/branch-protection need GitHub Pro or a public repo (verified via API
  403). See the Cross-Review residual below + `docs/next-steps.md` (Platform hardening).

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
| 202 | `uap-home-2` | `pve-ninitux3` | `192.168.0.202` | 2 vCPU, 4 GB RAM, 32 GB disk | running |
| 203 | `uap-ops-1` | `pve-ninitux` | `192.168.0.203` | 2 vCPU, 2 GB RAM, 30 GB disk | running |

## Tailnet

| Device | Tailnet name | Tailnet IP |
|---|---|---|
| `uap-home-1` | `uap-home-1.tail9fd337.ts.net` | `100.106.223.120` |
| `uap-home-2` | `uap-home-2.tail9fd337.ts.net` | `100.94.228.67` |
| `uap-ops-1` | `uap-ops-1.tail9fd337.ts.net` | `100.82.241.121` |
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

The model + agent value layers are deployed in namespace `uap-system`. **GitOps-coverage nuance** (verified
against `clusters/prod/infra/kustomization.yaml` + `git status`): only part is Flux-reconciled.

- **subfleet** (Flux-managed): wraps the **Claude subscription** as an OpenAI-compatible **chat** API (spawns the
  bundled `claude` CLI per request; drops `tools`/`tool_calls`). `subfleet-bridge.uap-system.svc:18902`. Egress to
  Anthropic via the in-cluster `singbox-egress` (VLESS+REALITY, ADR-018). Retained for the owner's **other**
  projects (a Telegram bot + web sessions); redundant for in-repo coding (which uses `claude -p` directly).
- **LiteLLM** v1.89.0 — deployed + smoke-verified, **NOT Flux-reconciled** (`clusters/prod/infra/litellm.yaml` is
  untracked; `litellm-keys.sops.yaml` is committed but not referenced by the kustomization). OpenAI gateway, groups
  `smart-cloud`/`-think`/`balanced-cloud`/`cheap-cloud`/`smart-cloud-pinned`; tailnet via `tailscale serve` on
  `uap-home-1`; `opus-4-8` verified end-to-end.
- **Hermes-legacy** (bespoke `hermes/hermes.py`) — deployed + smoke-verified, **NOT Flux-reconciled** (`hermes.yaml`
  untracked AND its `hermes-keys` Secret has no manifest in-repo at all). Prompt-based ReAct/ReWOO tool agent,
  NodePort `:30890`, 41 unit + 8 integration tests. **PARKED** — superseded by the external hermes-agent direction.

Treat "LiteLLM/Hermes are live" as *running + verified*, NOT *reconciled by GitOps*. Bringing them into the
kustomization (or formally parking them) is follow-up **B0** in `docs/next-steps.md`.

## Local FC Brain — Track A1 (PROVEN 2026-06-23)

Phase A1 of the hermes-agent pilot: a **local, native-function-calling** brain on the RTX, no cloud egress.

- **Host:** `desktop-m922ij2` (RTX 5060 Ti 16 GB, Blackwell sm_120, driver 610.62 / CUDA 13.3); **not always-on**, so
  this brain is **opportunistic** (durable brain is Codex, A5).
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
  (bucket-scoped key, client-side encryption) in `runbooks/hermes-agent-dr.md`.
- **⚠️ CURRENT BLOCKER (egress, 2026-06-25):** the **German VLESS+REALITY exit is DOWN** — `singbox-egress` logs show
  `EOF` opening connections to chatgpt.com, api.telegram.org, api.ipify.org and dns.google alike (the upstream VLESS
  connection to the German VPS fails at ~100ms). This is **independent of the work above** (`singbox-egress` is a
  separate, untouched deployment) and blocks BOTH the Codex brain and Telegram. The brain *config* is correct
  (managed keys verified); the round-trip will pass once the exit is restored. **Owner action:** check/replace the
  German VPS / VLESS endpoint (the owner-provided egress, `singbox-egress-config.sops.yaml`; see "Things That Need
  Owner Input").

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

- GitHub `origin` configured (private repo, read-only SSH deploy key for Flux); `master` pushed; `gh` authed on `uap-ops-1`.
- `infra/ops/configure-github-flux.sh` was run on `uap-ops-1` to create the repo, push, add the deploy key, and create the Flux git-auth secret.
- Local Windows SSH public key exists:
  - fingerprint: `SHA256:YLFbDMRbeUldpLQW8dmMihAQbRgCVBhmQGTW98rgm9c`
  - comment: `windows`
- GitHub and Bitbucket did not accept that key during the last SSH probe.
- Windows tailnet IP `100.114.172.40` responded to ping, but TCP `22` was not listening during the last check.
- Flux Git sync is enabled and reconciling (see GitOps section).

## Pending

1. Add a third server node before claiming k3s HA.
2. Decide whether the third node is a remote VPS or another independent failure domain.
3. Stage 3 (LiteLLM): owner provides Anthropic/OpenRouter keys; route LiteLLM through the VLESS egress (now working).
4. Investigate intermittent Windows-to-`uap-ops-1` tailnet SSH; LAN SSH is currently the verified workstation-to-ops path.
5. Configure Proxmox VM backups. (DR materials complete in R2: etcd snapshots in `prod/` + age-encrypted server
   token + `encryption-config.json` in `dr/`; cross-node restore drill passed 2026-06-19 — see `runbooks/restore-drill.md`.)

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
  snapshots are NOT auto-pruned — set an R2 lifecycle rule. (Corrected per REVIEW-CODEX.md; the prior "retention 7"
  for R2 was inaccurate.)
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
  deploy key (origin = SSH), push/fetch verified. Branch protection still NOT applied — **both classic protection
  AND rulesets require GitHub Pro on a private repo** ("rulesets are free on private" was WRONG; verified 2026-06-23:
  `POST /repos/.../rulesets` → 403 "Upgrade to GitHub Pro or make this repository public"). A CI gate
  (`.github/workflows/ci.yml`) was added 2026-06-23 as an unenforced **signal** (green); enforcing it needs Pro, a
  public repo, or a CI-gated deploy branch (see `docs/next-steps.md` → Platform hardening). Residual.
- #4 Vaultwarden rotated: admin token regenerated and stored as an Argon2 PHC hash in `.env` (no longer plaintext);
  RSA identity key regenerated (0600). New admin token staged at `~/vaultwarden/admin-token.NEW.txt` on ops-1 for
  owner retrieval (move to a password manager, then delete).

Pending (owner action): rotate R2 token to a bucket-scoped key + R2 lifecycle rule; independent off-homelab age-key
escrow (verify decrypt); foreign VPS (Stage 1 HA + Stage 3 egress); optional — revoke the old "GitHub CLI" OAuth grant
in GitHub settings, and enable branch protection if upgrading to GitHub Pro. Pending (agent): canary cross-node
Secret-restore drill; kubeconfig 0644->0600 + tailnet-only API firewall (needs restart).
