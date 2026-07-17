# Infrastructure Reference

> Consolidated, human-readable map of the UAP fleet: hardware, network, what runs where, the
> subscriptions, and the target hermes-agent architecture. This is a **reference**, not the live
> source of truth — for current operational state always defer to [STATUS.md](../STATUS.md).
> Target architecture and the 2026-06 pivot are tracked in [docs/next-steps.md](next-steps.md) and
> the research notes under [docs/research/](research/).
>
> Last reviewed: 2026-07-17.

## TL;DR

- **3 always-on Linux VMs** on local Proxmox form the operational core: a k3s server, a k3s agent,
  and an operator VM. **No GPU on any of them.**
- **2 GPU/personal machines** (Windows desktop with an RTX 5060 Ti, Mac mini) are on the tailnet but
  are **NOT always-on** and are **NOT** k3s/etcd members — they are future external agent-workers.
- **NOT HA; HA/VPS deferred indefinitely for budget.** One k3s server/control-plane + one agent = a single
  etcd member. The current strategy is one control-plane, R2 backups, and the verified 2026-07-12 restore drill.
  A 3rd independent k3s server remains a future HA prerequisite, not an active owner action. See
  [CLAUDE.md → Important Boundaries](../CLAUDE.md).
- Network = **Tailscale mesh**; cloud LLM egress from Russia goes through a **sing-box / VLESS+REALITY**
  proxy (ADR-018), because Anthropic/OpenAI/OpenRouter are unreachable directly from RU.
- **Model/agent runtime today:** Central external hermes-agent uses Codex `gpt-5.6-luna` through
  `codex_app_server`; build-1 delivery uses the automatic OpenAI-only Luna/Sol/Terra policy. subfleet/LiteLLM and the
  bespoke `hermes.py` remain installed separate/legacy capacities, not automatic coding fallbacks.
- **The harness is now LIVE:** the external **NousResearch hermes-agent** is the vibe-coding harness —
  phone control via Telegram, coding via `claude -p` + `codex exec` skills. The bespoke Hermes is parked
  as a fallback.
- **Brain today (2026-07-11 onward):** Codex `gpt-5.6-luna` via `codex_app_server` is live after owner re-auth (#119).
  The `local-models-router` on `uap-ops-1` remains the manual fallback over `qwen-35b` (RTX desktop) and
  `ornith-9b` (always-on Mac). See [runbooks/hermes-agent-codex-brain.md](../runbooks/hermes-agent-codex-brain.md)
  and [runbooks/local-models-router.md](../runbooks/local-models-router.md).

---

## 1. Tailscale fleet

Every machine is on one tailnet. Tailnet IPs are the stable path for SSH and smoke tests; LAN SSH has
shown intermittent resets (see [CLAUDE.md](../CLAUDE.md)).

| Machine | Tailnet IP | OS | CPU / RAM / GPU | Role | Always-on |
|---|---|---|---|---|---|
| `uap-home-1` | `100.106.223.120` | Debian 12 | 4 vCPU / 8 GB / no GPU | k3s **server**, embedded etcd (control plane); LiteLLM; in-cluster VLESS egress | **Yes** |
| `uap-home-2` | `100.94.228.67` | Debian 12 | 6 vCPU / 8 GB / no GPU | k3s **agent** (worker only); runs the **hermes-agent** brain pod + subfleet bridge (resized 6c/8G in #86/#87) | **Yes** |
| `uap-ops-1` | `100.82.241.121` | Debian 12 | 2 vCPU / 2 GB (no swap) / no GPU | operator / deploy VM — **not** a k3s node; git `origin` + push key, `kubectl`; hosts the **`local-models-router`** fallback endpoint `:8090` | **Yes** |
| `uap-build-1` | `100.85.56.31` | Ubuntu 22.04 | 8 vCPU / 16 GB / no GPU | always-on build/dev VM — **not** a k3s node, **not** in GitOps; runs the knowledge system, the Hermes Kanban swarm, ai-search, and the hermes-workspace webcenter (`:3000`) — all systemd | **Yes** |
| `desktop-m922ij2` | `100.114.172.40` | Windows 11 | 32 cores / 32 GB / **RTX 5060 Ti 16 GB** | workstation + GPU host; serves **`qwen-35b`** (llama.cpp) — the **primary local brain** | **No** |
| `pavels-mac-mini` | `100.116.97.112` | macOS (Apple Silicon, M4) | M4 / 16 GB / Apple GPU | serves **`ornith-9b`** (mlx) — the local **coder / fallback brain** | **Yes** |

Notes:
- The k3s nodes (`uap-home-1`, `uap-home-2`) and `uap-ops-1` have **no GPU**. The only **discrete/CUDA**
  GPU in the fleet is the RTX on the **not-always-on** Windows desktop — so `qwen-35b` (the primary brain)
  is only available when the desktop is on. The **always-on Mac mini** (Apple GPU) serves `ornith-9b`, the
  fallback brain / local coder that keeps working when the desktop is off. This brain topology is served
  through the `local-models-router` on `uap-ops-1` (see §3 and `runbooks/local-models-router.md`).
- `uap-ops-1` runs on the **same physical Proxmox node** as `uap-home-1`, so it shares a failure
  domain with the control plane (see Track B in [next-steps.md](next-steps.md)).
- Windows-to-`uap-ops-1` tailnet SSH has intermittently timed out after enrollment; workstation→ops
  checks default to LAN until resolved. `uap-ops-1` itself reaches both k3s nodes over tailnet fine.
- The Windows workstation does **not** run sshd (TCP 22 closed) and has **no** git `origin`; all pushes
  go through `uap-ops-1`.

### Proxmox hosts

Two hypervisors: `pve-ninitux` holds `uap-home-1` (+ `uap-ops-1` shares this host, and the VPNRouter
test VMs); `pve-ninitux3` holds `uap-home-2` + `uap-build-1` (so build-1's 16 GB constrains how far
`uap-home-2` can grow). Full map: [fleet-map.md](fleet-map.md).

| VMID | VM | Host | Resources |
|---|---|---|---|
| 201 | `uap-home-1` | pve-ninitux | 4 vCPU / 8 GB / 80 GB |
| 202 | `uap-home-2` | pve-ninitux3 | 6 vCPU / 8 GB / 32 GB (resized #86/#87) |
| 203 | `uap-ops-1` | pve-ninitux | 2 vCPU / 2 GB / 30 GB |
| 102 | `uap-build-1` | pve-ninitux3 | 8 vCPU / 16 GB / 100 GB (Ubuntu 22.04) |

Proxmox endpoint is LAN-only. Critical VMIDs `102/201/202/203` are backed up daily at `03:15` to
`backup-pve2`, a backup-only NFS export on the separate `pve-ninitux2` disk. The NFS server is excluded
from mounting its own export. VM203 passed archive integrity and isolated restore verification on 2026-07-13.

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
- **Offsite DR:** k3s etcd-s3 snapshots → Cloudflare R2 (bucket `uap-k3s-snapshots`, `prod/`). The 2026-07-12
  cross-node drill restored and decrypted an exact canary Secret value from an R2-fetched snapshot using only the
  snapshot + original server token; see `runbooks/restore-drill.md`.

### Model + agent layer (namespace `uap-system`)

**GitOps coverage** (verified against `clusters/prod/infra/kustomization.yaml`):

- **Flux-managed (in the kustomization):** `singbox-egress` (+ the HA egress), the subfleet token-service,
  the **subfleet bridge** (`:18902`), **LiteLLM** (`litellm.yaml` + `litellm-keys.sops.yaml`),
  **Hermes-legacy** (`hermes.yaml` + `hermes-keys.sops.yaml` + `hermes-code-configmap.yaml`), and the
  **hermes-agent** stack (config, Codex/Telegram/dashboard/Claude SOPS secrets, `hermes-agent.yaml`, and the
  daily PVC backup CronJob + its R2 secret). All committed and reconciled.
- **B0 is DONE:** the model+agent layer is now fully owned by Flux — "LiteLLM/Hermes are live" is now both
  "running and verified" **and** "reconciled by GitOps". (See **B0** in [next-steps.md](next-steps.md).)

| Component | What it is | Endpoint | GitOps |
|---|---|---|---|
| **subfleet** | Rust gateway wrapping the **Claude subscription** as an OpenAI-compatible **chat** API; spawns the real `claude` CLI per request. Drops `tools`/`tool_calls` — chat passthrough only. | `subfleet-bridge.uap-system.svc:18902/v1` | **Flux** |
| **LiteLLM** (v1.89.0) | The OpenAI-compatible gateway devices/agents hit; routes model groups to subfleet. Groups: `smart-cloud` (opus), `smart-cloud-think`, `balanced-cloud` (sonnet), `cheap-cloud` (haiku), `smart-cloud-pinned` (`claude-opus-4-8`). Reached from tailnet via `tailscale serve` on `uap-home-1`; master key via SOPS `litellm-keys`. | `litellm.uap-system.svc:4000` | **Flux** |
| **Hermes (bespoke, "Hermes-legacy")** | Single-file stdlib `hermes/hermes.py`; turns the chat backend into a **prompt-based ReAct/ReWOO** tool-using agent (native FC is infeasible through the subfleet CLI). Read-only kube tools, SSRF-guarded HTTP, per-tool scopes. 41 unit + 8 integration tests. **PARKED.** | NodePort `:30890` (in-cluster `:8900`) | **Flux** |
| **hermes-agent** | The **live** external NousResearch hermes-agent (vibe-coding harness). **Brain today = Codex `gpt-5.6-luna` via `codex_app_server`**; build-1 coding/review follows ADR-031's OpenAI Luna/Sol/Terra policy. The ops-1 local router is manual fallback only. | pod on `uap-home-2` (Telegram outbound long-poll) | **Flux** |

### Operator VM (`uap-ops-1`) — ad-hoc, outside GitOps

- The deploy/control machine: git `origin` (SSH, repo-scoped read-WRITE deploy key), `kubectl`, full
  toolchain (`tofu`, `ansible`, `flux`, `sops`, `age`, `gh`, `tailscale`, `jq`).
- Also runs **ad-hoc, NOT in GitOps:** host-local **sing-box** egress and **Vaultwarden**; the
  **`local-models-router`** systemd service (`local-model-router`) — the manual OpenAI-compatible fallback endpoint
  (`:8090`) for `qwen-35b`→RTX desktop and `ornith-9b`→Mac. It lives here because in-cluster pods cannot reach the
  tailnet `100.x` model boxes, but ops-1 can. It is not the current brain and must not be selected without owner
  approval. See
  `runbooks/local-models-router.md`. A daily age-encrypted `ops-backup` timer ships Vaultwarden +
  `~/.secrets` + units to R2.
- This VM's **concentration of secrets + capabilities is the dominant open risk** — see
  [REVIEW-CODEX.md](../REVIEW-CODEX.md) and Track B of [next-steps.md](next-steps.md).

### Build/dev VM (`uap-build-1`) — always-on, NOT in GitOps

Always-on Ubuntu 22.04 VM (8 vCPU / 16 GB, `100.85.56.31` / LAN `192.168.0.99`) for heavy build/dev +
repo work. Runs, all as **systemd** (not k3s, not Flux):

- the **knowledge system** — SQLite `knowledge.db` + local RU/EN embeddings; `tools/knowledge/`
  (`runbooks/knowledge-system.md`),
- the **Hermes Kanban swarm** — the native multi-agent orchestration pilot
  (`runbooks/hermes-kanban-swarm-pilot.md`),
- **ai-search** — a zero-key web-search CLI over the VLESS egress (`runbooks/ai-search.md`),
- the **hermes-workspace webcenter** (`:3000`, tailnet) — the owner+sister user-facing UI
  (`runbooks/hermes-workspace-webcenter.md`).

crates.io + rust-lang.org are RU-blocked, so cargo builds go through the VLESS egress
(`192.168.0.202:30880`); GitHub is wired via a fine-grained PAT on the box.

---

## 4. Subscriptions (the brain and coding routes)

> **Current state (2026-07-17):** the ChatGPT subscription is the live Central brain through Codex
> `codex_app_server`, and ADR-031's OpenAI Luna/Sol/Terra policy is the automatic build-1 coding/review route. The
> `qwen-35b`/`ornith-9b` ops-1 router is manual fallback only. Claude/subfleet remains installed separate capacity and
> is not an automatic route.

| Subscription | Count | Used for | Notes |
|---|---|---|---|
| **ChatGPT Plus** | 2 (shared with friends) | Live **brain** for hermes-agent via Codex `codex_app_server`, plus the standing-approved Luna/Sol/Terra delivery routes | Native function-calling, OAuth, no API key; exact route selection follows ADR-031. |
| **Claude (current non-Max plan)** | 1 | Separate legacy/other-project capacity behind subfleet and optional `claude -p` | Not an automatic UAP coding/review fallback; use requires an explicit owner decision. It cannot be hermes-agent's brain because the subfleet path drops `tool_calls`. |

Codex can be a hermes-agent brain because the Codex CLI is a drivable app-server that owns its own native tool loop;
the Claude CLI has no equivalent runtime in hermes-agent. Current UAP therefore uses Codex/OpenAI for both the brain
and automatic coding/review, while Claude remains an explicitly gated separate capacity.

---

## 5. Target architecture: the hermes-agent vibe-coding harness

> Full rationale + citations: [docs/research/nousresearch-hermes-agent.md](research/nousresearch-hermes-agent.md)
> and [docs/research/hermes-codex-subscription-brain.md](research/hermes-codex-subscription-brain.md).
> Phased rollout: [docs/next-steps.md](next-steps.md).

**North star:** vibe-coding. The owner supplies ideas + infrastructure; the agent ships **verified**
code. The owner does **not** review generated code, so the agent's **own self-testing is the quality
gate** — and that gate is now **enforced** (public repo + `protect-master` ruleset requiring a PR and the
strict `static-checks` CI check; direct push to master blocked). See next-steps Track A4 (DONE).

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
   (ChatGPT sub, OAuth,       (RTX 5060 Ti, vLLM/    (non-Max Claude,      (ChatGPT sub)
    no API key)                llama.cpp, >=64k ctx)   Claude Code harness)
         |                          |                       |
      egress proxy             local, no egress         egress proxy        egress proxy
   (non-RU, ADR-018)                                  (reuses subfleet creds)
```

> **Live today:** Central Hermes uses Codex `gpt-5.6-luna` through `codex_app_server`, and ADR-031's automatic
> OpenAI-only delivery routes use Luna/Sol/Terra on build-1. `qwen-35b`/`ornith-9b` behind the ops-1
> `local-models-router` are documented manual fallbacks, not current or automatic routes. See
> [runbooks/local-models-router.md](../runbooks/local-models-router.md) and
> [runbooks/hermes-agent-codex-brain.md](../runbooks/hermes-agent-codex-brain.md).

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
