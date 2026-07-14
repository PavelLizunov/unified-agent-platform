# tools/ — subsystem index

Standalone helper subsystems used by the platform. Most run **off-cluster** (systemd on
`uap-build-1` or `uap-ops-1`, or on-demand on a GPU box) — they are **NOT** in k3s and **NOT**
Flux/GitOps-managed. Each is stdlib-first (see the `ponytail:` notes in-tree for the deliberate
shortcuts). Read the owning runbook before changing behaviour.

| Subsystem | Purpose | Entrypoint | Owning runbook | Self-test |
|---|---|---|---|---|
| `offload` | Route token-heavy, quote-verifiable reads to the free local LLM so big inputs never burn paid tokens; a mechanical quote-gate rejects fabrication/injection. | `python tools/offload/offload.py extract -q "…" FILE [FILE…]` (also `offload health`) | [local-offload.md](../runbooks/local-offload.md) | `python tools/offload/test_offload.py` (offline; exercises the quote-gate) |
| `offload/soak` | Long-run soak-eval harness for the local model — tracks A (offload), B (coding), C (retrieval+injection), D (function-calling) looped to a wall-clock budget with deterministic graders. | `python tools/offload/soak/run_soak.py [--hours N]` | [docs/model-eval/qwen-agentworld/](../docs/model-eval/qwen-agentworld/) (V3_SOAK_GOAL.md) | requires a live local model server; the server-free unit is the shared quote-gate `python tools/offload/test_offload.py` |
| `knowledge` | Engineering knowledge system: SQLite canonical registry (source of truth) + local (sqlite-vec/ONNX, RU+EN) vector retrieval; lifecycle-filtered, default = active only. | `python tools/knowledge/knowledge.py <sync\|query\|record\|doctor\|…>` (deployed as the `knowledge` wrapper on build-1) | [knowledge-system.md](../runbooks/knowledge-system.md) | `python tools/knowledge/knowledge.py doctor` (env/db/model/gh health, exit 0 = ok) |
| `local-models` | One OpenAI-compatible endpoint in front of two local backends — `qwen-35b` (llama.cpp, desktop RTX) and `ornith-9b` (mlx_lm.server, Mac) — routed by model name, native `tool_calls` passed through. | `python tools/local-models/route.py` (systemd `local-model-router` on ops-1, `:8090`) | [local-models-router.md](../runbooks/local-models-router.md) | `python tools/local-models/route.py --selfcheck` (offline route-table asserts, prints `selfcheck ok`) |
| `readiness` | Read-only JSONL evidence collector for Hermes M1/M2/M3/M6/M9/M12 gates; never runs owner-gated mutations. | `python tools/readiness/readiness.py --output <path>.jsonl` on ops-1 | [hermes-development-readiness-goal.md](../runbooks/hermes-development-readiness-goal.md) | `python tools/readiness/readiness.py --self-check` |
| `hermes-mission` | Exact-version overlay that keeps one durable mission event log/reducer inside central Hermes and projects it to Workspace and Telegram; offline until owner-approved A6.4. | `python tools/hermes-mission/apply_overlay.py <pinned-hermes-checkout>` | [hermes-mission-contract-v1.md](../docs/hermes-mission-contract-v1.md) | `python tests/static/test_hermes_mission_runtime.py`; pinned overlay/API checks in `tools/hermes-mission/test_*.py` |
| `websearch` | `ai-search` — free-tier web search / cited answer / page-fetch for Hermes; zero-key DuckDuckGo via the VLESS proxy, keyed exa/tavily/brave auto-enable when the env key is present. | `python tools/websearch/ai_search.py <search\|fetch\|providers>` (deployed as `ai-search` on build-1) | [ai-search.md](../runbooks/ai-search.md) | `python tools/websearch/ai_search.py providers` (offline; shows which providers are ready) |
| `swarm` | Kanban watchdog plus ADR-028 quota-aware routing, repository guards, SHA-bound review and terminal-state validation. | `python tools/swarm/install_flow_v2.py`; watchdog cron remains on build-1 | [hermes-flow-v2.md](../runbooks/hermes-flow-v2.md) | `python tests/static/test_hermes_flow_contract.py` |

## Notes

- **Secrets** live in SOPS / on the owning box (e.g. `~/.config/ai-search.env`, `ROUTER_KEY`,
  R2 creds). Never inline a key/token/URL here — reference by location only.
- **RU egress:** anything that reaches a public endpoint (ai-search keyed providers, cloud LLMs)
  goes through a VLESS proxy — see [llm-egress-vless.md](../runbooks/llm-egress-vless.md). The
  offload/local-models path is fully local (no egress).
- The offload/local-models Python honours `HTTP(S)_PROXY` but forces **no proxy** for the local
  backend URL (the pod exports the VLESS proxy; `NO_PROXY` CIDR is ignored by urllib) — see the
  `ProxyHandler({})` opener in `offload.py`/`route.py`.
