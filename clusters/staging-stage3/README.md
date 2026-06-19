# Stage 3 scaffolding — REVIEW ONLY (do NOT apply yet)

LiteLLM model gateway + an **in-cluster egress** (the `singbox-egress` Service that
`runbooks/llm-egress-vless.md` referenced but did not exist — REVIEW-CODEX.md #6). Like the Stage 2 scaffolding,
these manifests are **outside the Flux path** (`./clusters/prod`) and carry **no `kustomization.yaml`**, so nothing
deploys by accident.

## Two scopes

- **Stage 3-LITE (felt impact — does NOT need Stage 1 HA or Stage 2 Postgres):** single LiteLLM replica, keys from a
  SOPS Secret, egress via the in-cluster sing-box. Promotable as soon as the **egress config Secret** and the
  **API-key Secret** exist (both owner inputs — see `BACKLOG.md`). This is the fastest path to a live Claude endpoint
  reachable from every device over tailnet.
- **Stage 3-FULL:** `replicas: 2`, virtual-keys + spend accounting in the Stage 2 Postgres
  (`ghcr.io/berriai/litellm-database` image + `DATABASE_URL`). Gated on Stage 2.

## Apply gate

- LITE: needs (a) `singbox-egress-config` SOPS Secret (the working VLESS client config, bound to `0.0.0.0`, not
  `127.0.0.1`), and (b) `litellm-keys` SOPS Secret (Anthropic + OpenRouter keys + master key). No Stage 1/2 dependency.
- FULL: additionally needs Stage 2 Postgres green and the HA decision recorded.

## Egress

In-cluster `sing-box` reuses the **proven** ops-1 config (3 foreign VLESS+REALITY nodes, `urltest` auto-select) but
binds the mixed proxy on `0.0.0.0:12080` so the cluster Service is reachable. LiteLLM sends `HTTPS_PROXY`/`HTTP_PROXY`
to `http://singbox-egress.uap-system.svc:12080`; `NO_PROXY` keeps cluster + tailnet traffic (Ollama) off the tunnel.
This replaces the localhost-only ops-1 proxy as the cluster egress and removes that Stage-3 blocker.

## Model groups (agent picks the name; LiteLLM maps it — ADR-006)

| Group | Backend | Note |
|---|---|---|
| `smart-cloud` | `anthropic/claude-opus-4-8` | via egress |
| `cloud-fallback` | `openrouter/...` | via egress |
| `cheap-local` | `ollama/...` on owner Mac/Win over tailnet | overflow / egress-down fallback |

Fallback chain: `smart-cloud -> cloud-fallback -> cheap-local`.

## Validate before apply

| Component | Pinned | Validate |
|---|---|---|
| LiteLLM | `ghcr.io/berriai/litellm:v1.89.0` | current stable; use `litellm-database` for Stage 3-FULL |
| sing-box | `ghcr.io/sagernet/sing-box:v1.13.13` | current stable |
| Anthropic prompt caching | — | confirm `cache_control` + reasoning-effort survive the `anthropic/` translation path; if not, route native Claude clients to LiteLLM's `/anthropic` passthrough (REVIEW-CODEX.md) |
| `cheap-local` api_base + model | placeholder | set the owner Ollama tailnet IP + model tag |
| `cloud-fallback` model slug | placeholder | set a valid OpenRouter model id |

## Promote

Move the reviewed manifests into `clusters/prod/` (egress to `infra`, LiteLLM to `apps`), wire the two SOPS Secrets,
add to `kustomization.yaml`, commit, let Flux reconcile. Smoke: `curl` the LiteLLM `/v1/models`, then a chat
completion to `smart-cloud` and confirm it egresses (exit-country check) and falls back when a key is unset.
