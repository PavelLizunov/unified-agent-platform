# runbooks/ — index

Operational procedures for the platform. Each row is derived from the runbook's own opening line.
Pick by the **trigger** column. Companion index for the helper code: [tools/README.md](../tools/README.md).
The two gate runbooks (`validation-matrix.md`, `vibe-coding-acceptance.md`) define what "done" means.

Some runbooks are Russian, some English — the platform docs are bilingual; the index is English.

| Runbook | Purpose | When to use |
|---|---|---|
| [ai-search.md](ai-search.md) | Free-tier web search / answer / page-read for Hermes (RU-egress aware): zero-key DuckDuckGo via VLESS, keyed exa/tavily/brave auto-enable. | Wiring or debugging agent web search on build-1. |
| [claude-routing-goal.md](claude-routing-goal.md) | GOAL: reliably route coding to `claude -p` on build-1 + honest tests (close the codex-`apply_patch` substitution gap). | Making the harness actually use `claude` for edits, and measuring it honestly. |
| [cloudflare-r2-k3s-snapshots.md](cloudflare-r2-k3s-snapshots.md) | Cloudflare R2 as the near-free offsite target for k3s etcd snapshots. | Configuring or rotating the R2 bucket for etcd DR. |
| [flux-remote-git.md](flux-remote-git.md) | Enable Flux Git sync once a real remote Git URL / deploy key exists. | (Historical) turning on GitOps Git sync; remote/key setup. |
| [garage-object-store.md](garage-object-store.md) | Garage S3-compatible object store (ADR-019) for app artifacts / checkpoints / app backups. | Standing up in-cluster S3 for apps — NOT for etcd DR. |
| [gitops-flux-sops.md](gitops-flux-sops.md) | Flux v2.8.8 + SOPS/age install state and controller list. | Reconciling GitOps or adding a SOPS-encrypted secret. |
| [hermes-access.md](hermes-access.md) | The three live ways to reach Hermes-agent: pod CLI (`hermes`), web dashboard / Desktop app, Telegram. | Connecting to Hermes from any device. |
| [hermes-agent-codex-brain.md](hermes-agent-codex-brain.md) | Deploy the in-cluster hermes-agent gateway via Flux with its brain (Track A2). | Deploying or repairing the k3s hermes-agent + brain. Note: the live brain is now the local-models router — see STATUS.md. |
| [hermes-agent-dr.md](hermes-agent-dr.md) | hermes-agent state-PVC daily R2 backup + restore — the PVC has no other safety net. | Backing up or restoring hermes-agent state after a node/disk loss. |
| [hermes-kanban-swarm-pilot.md](hermes-kanban-swarm-pilot.md) | Native Hermes Kanban multi-agent swarm pilot on build-1 (durable board, roles from soak data). | Running or extending the local-cloud multi-agent swarm. |
| [hermes-windows-client.md](hermes-windows-client.md) | Replicate the "Hermes Chat" launcher (Git Bash → `ssh hermes` via ops-1) on another Windows PC. | Giving a new Windows box a Hermes terminal. |
| [hermes-workspace-webcenter.md](hermes-workspace-webcenter.md) | hermes-workspace web command center on build-1 `:3000` (chat + kanban + memory + skills + terminal, tailnet-only). | The user-friendly browser UI for the owner (and sister). |
| [k3s-add-server-node.md](k3s-add-server-node.md) | Add a Linux server node to embedded etcd — only for a 3rd independent failure domain. | Growing toward real HA (never to make uap-home-2 a 2nd etcd member). |
| [k3s-agent-join.md](k3s-agent-join.md) | Join a Linux worker (non-etcd) node, e.g. uap-home-2. | Adding overflow/worker capacity without touching quorum. |
| [k3s-snapshots.md](k3s-snapshots.md) | k3s embedded-etcd local snapshot state + manual snapshot. | Taking or inspecting on-node etcd snapshots. |
| [knowledge-system.md](knowledge-system.md) | Engineering knowledge system on build-1: SQLite canonical registry (source of truth) + local RAG. | Recording or retrieving durable engineering knowledge. |
| [litellm-tailnet.md](litellm-tailnet.md) | Expose LiteLLM (`:4000`) to tailnet devices via host `tailscale serve` on uap-home-1. | Reaching LiteLLM from a laptop/phone. |
| [llm-egress-vless.md](llm-egress-vless.md) | Cloud-LLM egress from Russia (ADR-018): keep Tailscale and VLESS planes separate, tunnel only LLM traffic. | Configuring cloud-LLM reachability from RU. |
| [local-fc-model.md](local-fc-model.md) | Local native-function-calling brain on the RTX (Track A1, Ollama + `gpt-oss:20b`) at ≥64k context. | Standing up a no-egress FC brain for hermes-agent. |
| [local-models-router.md](local-models-router.md) | One OpenAI endpoint over `qwen-35b` (desktop RTX) + `ornith-9b` (Mac) for when paid limits are exhausted. | Running the fully-local fallback brain / coder. |
| [local-offload.md](local-offload.md) | Route token-heavy, quote-verifiable reads to the free local model (quote-gate) to save paid tokens. | Extracting facts from a big log/doc/corpus without burning context. |
| [offsite-backups.md](offsite-backups.md) | The backup layer beyond local k3s snapshots (etcd→R2 done; Proxmox VM backups pending). | Planning or checking offsite DR coverage. |
| [proxmox-local-bootstrap.md](proxmox-local-bootstrap.md) | Local Proxmox bootstrap path to reproducible Linux nodes before a remote quorum member. | Provisioning cluster VMs on Proxmox. |
| [restore-drill.md](restore-drill.md) | Verify k3s etcd snapshots actually restore — on a disposable VM only. | Proving recoverability / running a DR drill. |
| [subfleet-integration.md](subfleet-integration.md) | subfleet (Rust bridge + token-service) as LiteLLM's model backend over a Claude/Codex subscription. | Deploying or repointing the subscription model backend. |
| [uap-ops-node.md](uap-ops-node.md) | Create / bootstrap the disposable `uap-ops-1` operator VM (tofu, ansible, flux, kubectl, sops, gh). | Setting up or rebuilding the deploy box. |
| [uap-ops-services-backup.md](uap-ops-services-backup.md) | Daily backup + recovery for ops-1 non-GitOps services (Vaultwarden, etc.). | Protecting or restoring ops-1 stateful services. |
| [validation-matrix.md](validation-matrix.md) | The checks required before marking bootstrap/stability work done (local gate + smoke). | Gating any infra change before handoff. |
| [vibe-coding-acceptance.md](vibe-coding-acceptance.md) | GOAL: end-to-end vibe-coding acceptance test (idea → Hermes codes on build-1 → verify → push), objective scoring. | Proving the full agent user-cycle works. |
