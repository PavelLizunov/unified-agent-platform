# Infrastructure Reference

> Consolidated, human-readable map of the UAP fleet: hardware, network, what runs where, the
> subscriptions, and the target hermes-agent architecture. This is a **reference**, not the live
> source of truth — for current operational state always defer to [STATUS.md](../STATUS.md).
> Target architecture and the 2026-06 pivot are tracked in [docs/next-steps.md](next-steps.md) and
> the research notes under [docs/research/](research/).
>
> Last reviewed: 2026-06-23.

## TL;DR

- **3 always-on Linux VMs** on local Proxmox form the operational core: a k3s server, a k3s agent,
  and an operator VM. **No GPU on any of them.**
- **2 GPU/personal machines** (Windows desktop with an RTX 5060 Ti, Mac mini) are on the tailnet but
  are **NOT always-on** and are **NOT** k3s/etcd members — they are future external agent-workers.
- **NOT HA.** One k3s server + one agent = a single etcd member. A 3rd independent k3s server in a
  separate failure domain is still required before any HA claim. See
  [CLAUDE.md → Important Boundaries](../CLAUDE.md).
- Network = **Tailscale mesh**; cloud LLM egress from Russia goes through a **sing-box / VLESS+REALITY**
  proxy (ADR-018), because Anthropic/OpenAI/OpenRouter are unreachable directly from RU.
- **Model backend today:** subfleet (the Claude subscription wrapped as an OpenAI-compatible **chat**
  API) behind a LiteLLM gateway, plus the bespoke single-file `hermes.py` agent.
- **Where we're going:** adopt the external **NousResearch hermes-agent** as the vibe-coding harness —
  brain = Codex (ChatGPT) subscription or a local FC model on the RTX; coding = `claude -p` + `codex exec`
  as skills; phone control via Telegram. The bespoke Hermes is parked as a fallback.

---

## 1. Tailscale fleet

Every machine is on one tailnet. Tailnet IPs are the stable path for SSH and smoke tests; LAN SSH has
shown intermittent resets (see [CLAUDE.md](../CLAUDE.md)).

| Machine | Tailnet IP | OS | CPU / RAM / GPU | Role | Always-on |
|---|---|---|---|---|---|
| `uap-home-1` | `100.106.223.120` | Debian 12 | 4 vCPU / 8 GB / no GPU | k3s **server**, embedded etcd (control plane) | **Yes** |
| `uap-home-2` | `100.94.228.67` | Debian 12 | 2 vCPU / 4 GB / no GPU | k3s **agent** (worker only) | **Yes** |
| `uap-ops-1` | `100.82.241.121` | Debian 12 | 2 vCPU / 2 GB (no swap) / no GPU | operator / deploy VM — **not** a k3s node; holds git `origin` + push key, runs `kubectl` | **Yes** |
| `desktop-m922ij2` | (tailnet) | Windows 11 | 32 cores / 32 GB / **RTX 5060 Ti 16 GB** | workstation; future agent-worker + **local LLM host** | **No** |
| `pavels-mac-mini` | (tailnet) | macOS (Apple Silicon) | — / RAM unknown / Apple GPU | future agent-worker + small local LLM; **SSH currently off** | **No** |

Notes:
- The two always-on workers with real compute (`uap-home-1`, `uap-home-2`) have **no GPU**. The only
  GPU in the fleet is on the **not-always-on** Windows desktop — so a local-model brain on the RTX is
  only available when the desktop is on. This is the single most important placement fact.
- `uap-ops-1` runs on the **same physical Proxmox node** as `uap-home-1`, so it shares a failure
  domain with the control plane (see Track B in [next-steps.md](next-steps.md)).
- Windows-to-`uap-ops-1` tailnet SSH has intermittently timed out after enrollment; workstation→ops
  checks default to LAN until resolved. `uap-ops-1` itself reaches both k3s nodes over tailnet fine.
- The Windows workstation does **not** run sshd (TCP 22 closed) and has **no** git `origin`; all pushes
  go through `uap-ops-1`.

### Proxmox host

| VMID | VM | Resources |
|---|---|---|
| 201 | `uap-home-1` | 4 vCPU / 8 GB / 80 GB |
| 202 | `uap-home-2` | 2 vCPU / 4 GB / 32 GB |
| 203 | `uap-ops-1` | 2 vCPU / 2 GB / 30 GB |

Proxmox endpoint is LAN-only. **Proxmox VM backups are still pending** (k3s/etcd DR is in R2; the VMs
themselves are not yet backed up).

---

## 2. Network and egress

**Mesh — Tailscale.** Every device gets a stable name and peer-to-peer WireGuard reachability; relay
fallback otherwise. This is the "reach it from any device, no single gateway" foundation.

**k3s over tailnet.** The cluster network runs over Tailscale: `--node-ip=<tailnet-ip>`,
`--flannel-iface=tailscale0`, `--tls-san=<tailnet-ip>` (ADR-021). Consequence: an in-pod `tailscale`
sidecar can't expose a Service (the node would be unreachable over a network that is itself Tailscale) —
so tailnet exposure is done with `tailscale serve` **on the node** (LiteLLM) or via **NodePort**
(Hermes, `:30890`). See `runbooks/litellm-tailnet.md`.

**Cloud LLM egress (the RU constraint).** Anthropic / OpenAI / OpenRouter are not reachable directly
from Russia. Outbound LLM traffic goes through a **sing-box VLESS+REALITY** proxy to a non-RU exit
(ADR-018), in two forms today:
- **In-cluster** `singbox-egress` (Flux-managed) — what the subfleet egress uses to reach Anthropic.
- **Host-local** sing-box on `uap-ops-1` (`127.0.0.1:12080`, systemd --user) — ad-hoc, predates the
  in-cluster one; flagged as blast-radius in REVIEW-CODEX.

**Backups egress.** Cloudflare R2 (EU endpoint) is reachable **directly** from RU with no proxy, so
k3s etcd-snapshot offsite backups don't need the VLESS path.

The carried-forward know-how — a working non-RU egress and headless Claude/Codex subscription auth — is
exactly what the hermes-agent pilot reuses.

---

## 3. What runs where, today

> Source of truth for live state is [STATUS.md](../STATUS.md). This is the orientation map.

### k3s cluster (`uap-home-1` + `uap-home-2`)

- k3s `v1.35.5+k3s1`. Server on `uap-home-1` (embedded etcd), agent on `uap-home-2`. System pods Ready.
- **GitOps:** Flux reconciles `clusters/prod` from the GitHub remote over a read-only SSH deploy key,
  with **SOPS/age** decryption. The age **private** key lives only in-cluster (`flux-system/sops-age`) —
  so `sops -d` does **not** work on `uap-ops-1`; verify decrypted secrets in-cluster with `kubectl`.
- **Offsite DR:** k3s etcd-s3 snapshots → Cloudflare R2 (bucket `uap-k3s-snapshots`, `prod/`). A
  cross-node restore drill passed (canary-Secret value verification still pending — see
  `runbooks/restore-drill.md`).

### Model + agent layer (namespace `uap-system`)

**Important GitOps-coverage nuance** (verified against `clusters/prod/infra/kustomization.yaml` +
`git status`):

- **Flux-managed (in the kustomization):** `singbox-egress`, the subfleet token-service, and the
  **subfleet bridge** (`:18902`). Committed and reconciled.
- **Deployed + smoke-verified, but NOT reconciled by Flux:** `litellm.yaml` and `hermes.yaml` are
  **untracked** in git and **not** referenced by the kustomization. `litellm-keys.sops.yaml` *is*
  committed but is **also not referenced**, so Flux does not apply it either. And `hermes.yaml`
  consumes a `hermes-keys` Secret that has **no manifest in the repo at all**. These workloads were
  applied manually (`kubectl`). Until the manifests (and the missing Secret) are committed and added to
  the kustomization, Flux does not own them — treat "LiteLLM/Hermes are live" as "running and verified",
  not "reconciled by GitOps". (Tracked as follow-up **B0** in [next-steps.md](next-steps.md).)

| Component | What it is | Endpoint | GitOps |
|---|---|---|---|
| **subfleet** | Rust gateway wrapping the **Claude subscription** as an OpenAI-compatible **chat** API; spawns the real `claude` CLI per request. Drops `tools`/`tool_calls` — chat passthrough only. | `subfleet-bridge.uap-system.svc:18902/v1` | **Flux** |
| **LiteLLM** (v1.89.0) | The OpenAI-compatible gateway devices/agents hit; routes model groups to subfleet. Groups: `smart-cloud` (opus), `smart-cloud-think`, `balanced-cloud` (sonnet), `cheap-cloud` (haiku), `smart-cloud-pinned` (`claude-opus-4-8`). Reached from tailnet via `tailscale serve` on `uap-home-1`; master key via SOPS `litellm-keys`. | `litellm.uap-system.svc:4000` | **Not reconciled** (manifest untracked) |
| **Hermes (bespoke, "Hermes-legacy")** | Single-file stdlib `hermes/hermes.py`; turns the chat backend into a **prompt-based ReAct/ReWOO** tool-using agent (native FC is infeasible through the subfleet CLI). Read-only kube tools, SSRF-guarded HTTP, per-tool scopes. 41 unit + 8 integration tests. | NodePort `:30890` (in-cluster `:8900`) | **Not reconciled** (untracked; needs a `hermes-keys` Secret) |

### Operator VM (`uap-ops-1`) — ad-hoc, outside GitOps

- The deploy/control machine: git `origin` (SSH, repo-scoped read-WRITE deploy key), `kubectl`, full
  toolchain (`tofu`, `ansible`, `flux`, `sops`, `age`, `gh`, `tailscale`, `jq`).
- Also runs **ad-hoc, NOT in GitOps:** host-local **sing-box** egress and **Vaultwarden**. A daily
  age-encrypted `ops-backup` timer ships Vaultwarden + `~/.secrets` + units to R2.
- This VM's **concentration of secrets + capabilities is the dominant open risk** — see
  [REVIEW-CODEX.md](../REVIEW-CODEX.md) and Track B of [next-steps.md](next-steps.md).

---

## 4. Subscriptions (the brains and the coders)

| Subscription | Count | Used for | Notes |
|---|---|---|---|
| **ChatGPT Plus** | 2 (shared with friends) | Target **brain** for hermes-agent via the **Codex `codex_app_server`** runtime (native function-calling, **no API key**, OAuth) | The sharers don't use Codex, so the Codex capacity is effectively ours; two accounts = rate-limit headroom. |
| **Claude Max ($200)** | 1 | **Coding execution** via `claude -p` (full Claude Code harness) and as the backend behind subfleet | The Claude subscription **cannot** be hermes-agent's *brain* (the subfleet/Claude path drops `tool_calls`; hermes-agent has no prompt-based fallback). Excellent as a **coding subprocess** and for subfleet chat. |

Why this split: Codex can be a hermes-agent brain because the Codex CLI is a drivable app-server that
owns its own native tool loop; the Claude CLI has no equivalent runtime in hermes-agent. So **Codex =
brain, Claude = a coder.** Spreading coding across `claude -p` and `codex exec` keeps either subscription
under its limits.

---

## 5. Target architecture: the hermes-agent vibe-coding harness

> Full rationale + citations: [docs/research/nousresearch-hermes-agent.md](research/nousresearch-hermes-agent.md)
> and [docs/research/hermes-codex-subscription-brain.md](research/hermes-codex-subscription-brain.md).
> Phased rollout: [docs/next-steps.md](next-steps.md).

**North star:** vibe-coding. The owner supplies ideas + infrastructure; the agent ships **verified**
code. The owner does **not** review generated code, so the agent's **own self-testing is the quality
gate** (today that gate is unenforced — see next-steps Track A4 and the CI work).

**Harness:** the external **NousResearch hermes-agent** (MIT) — tool-calling agent with skills, local
SQLite/FTS memory, subagents, cron, checkpoints/rollback, git worktrees, 20+ messaging platforms. It
**supersedes** the bespoke `hermes.py` ("Hermes-legacy"), which is parked as a fallback.

```
            phone (Telegram, outbound long-poll — NAT/RU-friendly, no inbound port)
                                  |
                          hermes-agent gateway
                     (Docker, on an always-on Linux node)
                                  |
         +------------------------+-----------------------------------+
     BRAIN (native function-calling — REQUIRED)            CODING (skills, shelled out)
   +--------------+---------------+                  +----------+----------+
   Codex codex_app_server     local FC model         claude -p             codex exec
   (ChatGPT sub, OAuth,       (RTX 5060 Ti, vLLM/    (Claude Max,          (ChatGPT sub)
    no API key)                llama.cpp, >=64k ctx)   Claude Code harness)
         |                          |                       |
      egress proxy             local, no egress         egress proxy        egress proxy
   (non-RU, ADR-018)                                  (reuses subfleet creds)
```

**Hard constraints:**
- hermes-agent **requires native function-calling** with **no** prompt-based fallback. A FC-less
  endpoint (our subfleet/Claude path) lets it connect and chat but every tool silently goes dark — so
  **do not** point hermes-agent's brain at subfleet.
- The brain must reach the cloud (Codex) **through the egress proxy**, or be a **local** FC model on the
  RTX (no egress, but only when the desktop is on).
- On a restricted RU network, **prefer the prebuilt `nousresearch/hermes-agent` Docker image** over the
  `curl | bash` installer (which pulls from PyPI/npm/GitHub).

**What changes vs stays:**
- **Redundant for THIS project's coding path:** the subfleet OpenAI-bridge (coding now goes through
  `claude -p` directly).
- **Retained:** subfleet for the owner's **other** projects (Telegram bot + web sessions); the shared
  **egress**; the **headless Claude/Codex auth** know-how; the always-on **k3s + Flux + SOPS** platform.

---

## 6. Pointers

- Live state: [STATUS.md](../STATUS.md)
- Decisions / ADRs: [DECISIONS.md](../DECISIONS.md) (esp. ADR-018 egress, ADR-019 Garage, ADR-021 k3s-over-tailnet, and the new ADR-022..025)
- Build plan (pre-pivot staging): [BUILD-PLAN.md](../BUILD-PLAN.md)
- Risks: [RISKS.md](../RISKS.md), cross-review [REVIEW-CODEX.md](../REVIEW-CODEX.md)
- hermes-agent research: [docs/research/](research/)
- Next steps / pilot plan: [docs/next-steps.md](next-steps.md)
