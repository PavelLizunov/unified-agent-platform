# Stage 3 scaffolding — REVIEW ONLY (do NOT apply yet)

LiteLLM model gateway + an **in-cluster egress** (the `singbox-egress` Service that
`runbooks/llm-egress-vless.md` referenced but did not exist — REVIEW-CODEX.md #6). Like the Stage 2 scaffolding,
these manifests are **outside the Flux path** (`./clusters/prod`) and carry **no `kustomization.yaml`**, so nothing
deploys by accident.

## Two scopes

- **Stage 3-LITE (felt impact — does NOT need Stage 1 HA or Stage 2 Postgres):** single LiteLLM replica, backends +
  keys from a SOPS Secret. Promotable as soon as the **backend Secret** (subscription-endpoint URLs/keys) exists —
  plus the in-cluster egress Secret ONLY if a backend is remote + RU-blocked (see Backends + egress). This is the
  fastest path to a live OpenAI-compatible endpoint reachable from every device over tailnet.
- **Stage 3-FULL:** `replicas: 2`, virtual-keys + spend accounting in the Stage 2 Postgres
  (`ghcr.io/berriai/litellm-database` image + `DATABASE_URL`). Gated on Stage 2.

## Apply gate

- LITE: needs (a) `singbox-egress-config` SOPS Secret (the working VLESS client config, bound to `0.0.0.0`, not
  `127.0.0.1`), and (b) `litellm-keys` SOPS Secret (Anthropic + OpenRouter keys + master key). No Stage 1/2 dependency.
- FULL: additionally needs Stage 2 Postgres green and the HA decision recorded.

## Backends + egress

The cloud groups are **OpenAI-compatible endpoints backed by a Claude Code / Codex subscription session** (NOT raw
Anthropic/OpenAI API keys). Each is an `openai/<model>` provider with a custom `api_base`; the endpoint itself handles
the upstream auth + egress. So egress is conditional:

- **Backend on tailnet/LAN** (reachable from the homelab): LiteLLM calls it **directly** — `NO_PROXY` (incl.
  `100.64.0.0/10`) keeps it off any tunnel; the in-cluster `singbox-egress` is **not needed** for that backend.
- **Backend remote + RU-blocked:** point LiteLLM's `HTTPS_PROXY` at `singbox-egress.uap-system.svc:12080` (the
  in-cluster sing-box reusing the proven VLESS config, bound `0.0.0.0`) and remove that host from `NO_PROXY`.
- `cheap-local` (Ollama on the owner's Mac/Win over tailnet) is always direct.

So `singbox-egress.yaml` is **optional** — keep it only if a subscription endpoint is remote and blocked from RU.

## Model groups (agent picks the name; LiteLLM maps it — ADR-006)

| Group | Backend | Note |
|---|---|---|
| `smart-cloud` | `openai/<model>` -> Claude Code session endpoint | subscription auth; interactive rate-limits |
| `cloud-fallback` | `openai/<model>` -> Codex session endpoint | subscription auth |
| `cheap-local` | `ollama/...` on owner Mac/Win over tailnet | overflow / used when sessions rate-limit or expire |

Fallback chain: `smart-cloud -> cloud-fallback -> cheap-local`.

## Validate before apply

| Component | Pinned | Validate |
|---|---|---|
| LiteLLM | `ghcr.io/berriai/litellm:v1.89.0` | current stable; use `litellm-database` for Stage 3-FULL |
| sing-box | `ghcr.io/sagernet/sing-box:v1.13.13` | current stable |
| Prompt caching / reasoning | — | features depend on what the subscription proxy returns in OpenAI format, not native Anthropic; confirm `cache_control`/effort behaviour against the actual endpoint |
| Backend URL/auth/model | placeholders | set the Claude/Codex endpoint URL, api_key, and the model name each exposes |
| `cheap-local` api_base + model | placeholder | set the owner Ollama tailnet IP + model tag |
| subscription reliability | — | sessions can rate-limit / expire; rely on the fallback chain + `num_retries` |

## Promote

Move the reviewed manifests into `clusters/prod/` (egress to `infra`, LiteLLM to `apps`), wire the two SOPS Secrets,
add to `kustomization.yaml`, commit, let Flux reconcile. Smoke: `curl` the LiteLLM `/v1/models`, then a chat
completion to `smart-cloud` and confirm it egresses (exit-country check) and falls back when a key is unset.
