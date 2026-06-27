# Next Steps

> Two parallel tracks. **Track A** is the new north star: pilot the external **hermes-agent** as the
> vibe-coding harness. **Track B** is the **foundation work that does not go away** — the cluster is
> NOT HA and `uap-ops-1` is an over-concentrated SPOF. The pivot does **not** resolve Track B; both
> must progress.
>
> Context: [docs/infrastructure.md](infrastructure.md). Decisions: [DECISIONS.md](../DECISIONS.md).
> This doc **references** [BUILD-PLAN.md](../BUILD-PLAN.md) and [REVIEW-CODEX.md](../REVIEW-CODEX.md)
> rather than restating their detail. Last reviewed: 2026-06-23.

---

## Status banner

- **NOT HA.** One k3s server (`uap-home-1`, single embedded-etcd member) + one agent (`uap-home-2`).
  A 3rd **independent** k3s server in a separate failure domain is required before any HA claim. Do
  **not** turn `uap-home-2` into a second server (2-member etcd is not HA) — see
  [CLAUDE.md → Important Boundaries](../CLAUDE.md).
- **The quality gate is ENFORCED.** The repo is public, the ruleset `protect-master` is active (PR
  required + `static-checks` CI a required/strict check), and direct push to master is blocked. The
  "agent ships unreviewed code" model is now backed by an enforced CI gate (human review stays absent by
  design) — see Track A4 (DONE) and the platform-hardening items.
- **Model+agent backend is fully in GitOps** (Track B0 DONE).

---

## Track A — hermes-agent vibe-coding pilot

**Goal:** drive autonomous, self-verified coding from a phone, with a native-FC brain and Claude/Codex
subscriptions doing the actual edits. **Decisive constraint:** hermes-agent **requires native
function-calling** — the subfleet/Claude chat path cannot be its brain (it would connect and chat but
every tool goes dark). Detail + citations in the two research docs.

### Phase A1 — Local function-calling brain on the RTX (proof of FC) — ✅ DONE (2026-06-23)

*Why first:* cheapest way to prove the hermes-agent tool loop end-to-end with **no** cloud egress and
**no** subscription risk, on hardware we already own.

- On `desktop-m922ij2` (RTX 5060 Ti 16 GB), serve a Hermes/Qwen-family FC model via **vLLM**
  (`--enable-auto-tool-choice --tool-call-parser hermes`) or **llama.cpp** (`--jinja`).
- Raise context to **>= 64k** (hermes-agent rejects smaller at startup; Ollama defaults are far too low).
- **Done when:** a trivial hermes-agent run actually **invokes a tool** (file write / shell) against the
  local model — structured `tool_calls`, not text.
- *Caveat:* the desktop is **not always-on**, so this brain is opportunistic; the durable brain is Codex
  (A5).

> **Result (2026-06-23):** proven via **Ollama 0.16.1 + `gpt-oss:20b`** (native Windows; already on disk → no model
> download over the RU network). `/v1/chat/completions` with a `tools` array returns a **structured `tool_calls`**
> (`get_weather({"city":"Paris"})`, `finish_reason=tool_calls`), the tool-result round-trip yields a final answer, and
> a greeting yields no tool call. Served `context_length=65536`, **100% GPU**, ~14.7 GB VRAM. WSL2/Docker absent, so
> vLLM-in-WSL2 deferred; `gpt-oss` chosen over a fresh Hermes/Qwen pull for the no-download reason. Proof:
> `tests/smoke/local-fc-toolcall.ps1` → `local-fc-toolcall-ok`. Runbook: `runbooks/local-fc-model.md`. STATUS.md →
> "Local FC Brain". **The strict A1 wording ("a *hermes-agent* run invokes a tool") completes in A2** — A1 proved the
> exact endpoint contract hermes-agent requires; pointing hermes-agent at it (tailnet bind + `allow_private_urls`) is A2.

### Phase A2 — hermes-agent on an always-on Linux node, behind the egress — ✅ DONE (2026-06-24)

- Run the **prebuilt `nousresearch/hermes-agent`** image (not `curl|bash` — the installer pulls
  PyPI/npm/GitHub, awkward on RU egress) on an always-on Linux node that can reach the egress proxy.
- Persist `~/.hermes` (config, keys, SQLite state, skills, memory) on a volume; run as **non-root** with
  `terminal.backend: docker`; keep the default deny-by-default permission model; set
  `security.allow_private_urls: true` only as needed to reach LAN models (e.g. the RTX over tailnet).
- **Placement:** `uap-home-2` (2 vCPU / 4 GB, no GPU) is the most plausible always-on host;
  `uap-ops-1` (2 GB, no swap, already overloaded) should **not** take it. Decide bare-container-on-node
  vs eventual k3s workload (a community Helm chart exists; not official).
- **Done when:** the gateway runs persistently, survives a node reboot, and a CLI chat round-trips
  through it to the A1 brain.

> **In progress (2026-06-24):** owner chose **k3s via Flux** (not bare Docker) and to wire the **Codex brain
> directly** (pulling A5's brain forward) rather than the opportunistic RTX brain. The full recipe was **proven
> in the real image in-cluster** (`hermes chat -q` → `codex_app_server` → gpt-5.5 → tool executed, `BRAIN-OK`).
> Manifests merged (PR #8) and **deployed via Flux** — `hermes-agent` is **1/1 Running** on uap-home-2; the
> `kubectl exec` round-trip **in the deployed pod** wrote `BRAIN-OK` (brain executed a tool through the egress).
> **A2 DONE.** The 4 non-obvious knobs + verify/rotate steps: `runbooks/hermes-agent-codex-brain.md`. The brain is
> the always-on Codex subscription through the egress, so this workload does **not** depend on the GPU desktop.
> Chosen k3s/Flux over bare Docker, and the Codex brain (pulled forward from A5) over the opportunistic RTX brain.

### Phase A3 — Telegram gateway (phone control) — ✅ DONE (2026-06-24)

- BotFather `/newbot` → `TELEGRAM_BOT_TOKEN` in `~/.hermes/.env`; lock down with
  `TELEGRAM_ALLOWED_USERS` / DM pairing (deny-by-default).
- Use **outbound long-poll** (default) — no inbound port, NAT/RU-friendly. If NAT idle timeouts kill the
  poll, shorten `messaging.telegram.poll_timeout`.
- **Done when:** a phone message reaches the agent and a tool-using reply comes back.

> **Done (2026-06-24):** a phone message round-trips through the gateway to the Codex brain (gpt-5.5) and back
> ("17×23 = 391"), verified end-to-end (PR #10). Non-obvious fix: api.telegram.org is **blocked direct** from the
> cluster, and hermes's per-profile `os.environ` is **isolated** (multiplex) — so the proxy + `TELEGRAM_ALLOWED_USERS`
> had to go in hermes's **managed scope** (`/etc/hermes/.env`, loaded last with override into `os.environ`,
> authoritative for every profile + subprocess). The same fix gives the **gateway-driven Codex brain** the egress
> (codex spawn = `os.environ.copy()`). Token via SOPS; details in `runbooks/hermes-agent-codex-brain.md`.

### Phase A4 — First `claude -p` coding worker (the vibe-coding gate) — ✅ DONE (PR #23; north-star demo PASSED, PR #25)

- Install the **Claude Code** bundled skill; it shells `claude -p '<task>'` in print mode and reads back
  the JSON result (session id, turns, cost, tokens). Auth via the **Claude Max** subscription OAuth,
  reusing the carried-forward headless-auth + egress know-how. **LIVE (PR #23).**
- Drive a **real, small change in this repo** end-to-end: idea (phone) → hermes-agent plans → `claude -p`
  edits in a **git worktree** → **the change's own tests pass (the enforced gate from the hardening
  work)** → commit/push via `uap-ops-1`.
- **Done:** a verified change landed **without the owner reviewing the diff** — the worker autonomously
  shipped it through the enforced CI gate (**north-star demo PASSED, PR #25**). The agent's self-test +
  the now-enforced CI was the gate.

### Phase A5 — Codex brain + redundancy — `codex exec` + worktree isolation ✅ DONE (PR #24)

- Switch the durable brain to the **ChatGPT/Codex** subscription via the **`codex_app_server`** runtime
  (`model.openai_runtime: codex_app_server`, provider `openai-codex`) — native FC, **no API key**, OAuth
  (`~/.codex/auth.json`). Codex CLI must reach OpenAI **through the egress proxy**. Two Plus accounts give
  rate-limit headroom. **DONE** (brain live, A2/A3).
- Add **`codex exec`** as a second coding skill alongside `claude -p` to **split coding load**, with
  per-worker git worktree isolation. **DONE (PR #24).**
- **Redundancy:** keep the **local RTX FC model** (A1) as a fallback brain; bring **`pavels-mac-mini`**
  online (enable SSH) as a second worker / small local model host.
- **Done when:** the agent runs with the Codex brain by default, fails over to the local brain when
  egress/subscription is unavailable, and either coding engine can take a task.

> **Do NOT** point hermes-agent's brain at the subfleet endpoint at any phase — it is FC-less. subfleet
> stays the backend for the owner's **other** projects (Telegram bot + web sessions), not the coding path.

---

## Track B — Foundation work (independent of the pilot)

Open infrastructure debt from [STATUS.md](../STATUS.md) and the 2026-06-19 cross-review
[REVIEW-CODEX.md](../REVIEW-CODEX.md). Progresses regardless of Track A. (owner) = owner action,
(agent) = agent action.

### B0 — Bring the model+agent layer fully into GitOps (quick, do early) (agent) — ✅ DONE

- `clusters/prod/infra/litellm.yaml`, `hermes.yaml`, `litellm-keys.sops.yaml`, and `hermes-keys.sops.yaml`
  are **now committed and referenced** by `clusters/prod/infra/kustomization.yaml`, along with the
  `hermes-code-configmap.yaml` and every hermes-agent manifest — so Flux reconciles all of them. **DONE.**
- The `hermes-keys` Secret (`LITELLM_KEY`, `HERMES_KEY`, optional `HERMES_KEYS_JSON`) is **authored as a
  SOPS file and in the kustomization** — Flux can reconcile Hermes. **DONE.**
- `sops-smoke.sops.yaml` is likewise committed but intentionally **left out** (a decrypt smoke fixture) —
  keep it that way.
- Add a `validate_iac.py` check that flags any `*.yaml` under `clusters/prod/**` not referenced by a
  sibling kustomization (catches orphans like `litellm-keys.sops.yaml`).
- **Note (post-pivot):** confirm with the owner whether the litellm/hermes (Hermes-legacy) layer is still
  intended now that the direction is the external hermes-agent — it may be parked rather than GitOps-ified.
- **Done when:** the kustomization references every running `uap-system` workload (and the Secrets they
  need), or the exceptions are explicitly justified. Until then, do not claim full GitOps coverage.

### B1 — Reach real HA: 3rd independent k3s server + failover drill (owner+agent)

- (owner) Provision a **3rd k3s server in a separate failure domain** (a non-RU VPS is doubly useful — it
  also serves as the egress node, ADR-018). Needs **owner input**: VPS provider + credentials.
- (agent) Join as a server (`--server https://<tailnet-ip-1>:6443`, `--flannel-iface=tailscale0`); keep
  the etcd member count **odd**. First make the Ansible k3s join reproducible (notify a restart on
  config/token change; recorded two-run idempotency test).
- (owner-approved) Run the **destructive failover drill**: 3x Ready, power off any one node, confirm
  `kubectl` still answers and pods survive.
- **Done when:** the 3-node failover milestone is green with owner sign-off. Only then may anything claim
  "HA".

### B2 — Reduce the `uap-ops-1` blast radius (owner+agent)

`uap-ops-1` (2 GiB, no swap) simultaneously holds sing-box egress, Vaultwarden, plaintext R2 creds, the
GitHub push key, a cluster-admin kubeconfig, and an SSH key authorized on **both** k3s nodes — and sits
on the **same Proxmox host** as `uap-home-1`. Already DONE: secret perms tightened, Vaultwarden token +
RSA key rotated, broad `gh` OAuth removed → repo-scoped SSH deploy key, daily `ops-backup` timer.
Remaining:

- (owner) **R2 least privilege:** rotate to a **bucket-scoped** R2 key (separate from interactive rclone)
  and add an R2 **lifecycle / Object Lock / versioning** policy — the bucket has none, so a compromise can
  overwrite/delete `prod/` and `dr/` (REVIEW-CODEX #1).
- (owner) **GitHub→cluster takeover path:** enable a **master ruleset** (free; the modern replacement for
  classic protection) requiring the CI check, since Flux follows mutable `master` with `prune:true` and
  the kustomize-controller can do `*` on `*`.
- (agent) **Migrate egress + Vaultwarden into the cluster** (an in-cluster `singbox-egress` already exists
  for subfleet) or back them with **tested** recovery runbooks (REVIEW-CODEX #5).
- **Done when:** ops-1 no longer holds an unscoped R2 key, the GitHub→cluster path requires review, and
  egress+Vaultwarden are either in-cluster or recoverable from a tested runbook.

### B3 — Finish and prove DR (owner+agent)

- (owner) **Independent age-key escrow:** the age **private** key was found **only** on `uap-home-1`. Put
  a copy in a verified **off-homelab, owner-controlled** escrow and **prove a decrypt**. Never put the key
  value in git/markdown/prompts/logs.
- (agent) **Canary cross-node Secret restore:** the drill proved etcd objects/nodes/Flux resources but has
  **not** read back a known **Secret value**. Restore onto a clean disposable node using **only** the R2
  snapshot + original server token, then read and compare a deliberately created **canary Secret**.
- (owner) **Proxmox VM backups:** still pending — configure them.
- **Done when:** an off-homelab escrow decrypt succeeds, the canary Secret round-trips on a clean node,
  and Proxmox VM backups run.

---

## Platform hardening (cross-cutting, do alongside Track A4)

These make "the agent ships unreviewed code" actually safe; they gate A4.

- **Enforce the gate:** ✅ DONE — GitHub Actions CI (`static-checks`) runs on every push/PR, the repo is
  public, and the `protect-master` ruleset requires a PR + the `static-checks` check (strict), so direct
  push to master is blocked. (A PreToolUse commit secret-scan hook remains a nice-to-have defense-in-depth.)
- **Bring hermes tests into the local gate** (`python -m unittest discover -s hermes/tests -p 'test_*.py'`).
- **Isolate coding workers:** docker backend (`--cap-drop ALL`, `no-new-privileges`, `--pids-limit`,
  capped tmpfs, repo bind-mounted, NO host secrets in env); deny-first `.claude/settings.json`
  (`**/*.sops.yaml`, `age-key.txt`, `~/.codex/auth.json`); `--max-turns` + `--max-budget-usd` per run.
- **Per-worker git worktrees** before enabling concurrent subagents (replaces the prose file-ownership
  rule in AGENTS.md).
- **Attribution:** canonical per-executor git identity + SSH commit signing; agent+session commit trailers.
- **Reproducible toolchain:** pinned `requirements-dev.txt`; `__pycache__/`/`*.pyc` in `.gitignore`.

---

## Sequencing

- **B0** and the **gate-enforcement** hardening are ✅ DONE — both removed live risk.
- **Track A** (the pilot) proceeded **in parallel**: it mostly uses the RTX, the subscriptions, and one
  always-on Linux node, none of which block on HA work. A4 landed **after** gate enforcement, so
  "self-test passed" is real (north-star demo PASSED, PR #25).
- **B1 (3rd node + failover)** and **B3 (DR proof)** gate any "HA ready" / "DR complete" claim and need
  **owner input** (VPS, escrow) — start those conversations now.
- **B2** hardening should land before the platform takes on more load or secrets.

## Owner inputs needed

- Remote VPS provider + credentials (3rd k3s server **and** the non-RU egress node).
- R2 bucket-scoped key + lifecycle policy.
- Off-homelab age-key escrow location.
- Approval for destructive tests (node shutdown, restore-over-VM, k3s reset).
- Confirmation that the 2x ChatGPT Plus accounts may be used for the Codex brain, and Claude Max for
  `claude -p`; and (cleanest auth) whether one of the Plus accounts is the owner's own.
