# subfleet Integration (model backend for LiteLLM)

subfleet (`reserch/subfleet`, Rust `bridge` + `token-service`) is UAP's model backend: an
OpenAI-compatible gateway over a Claude Code (and, after subfleet Phase C, Codex) **subscription**.
LiteLLM points at the subfleet **bridge**; subfleet handles the RU egress and OAuth refresh.

See also the contract record in `clusters/staging-stage3/` and memory `uap-subfleet-integration`.
This runbook is the deploy path for the **Claude** path (Codex is additive — same bridge, just more
model groups, once subfleet `#2/#3` land).

## Contract (from subfleet's integration delta)

- Bridge: `http://<release>-bridge.<ns>.svc:18902/v1`, auth `Bearer <BRIDGE_SECRET>`.
- Models advertised: `claude-opus-4-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5`
  (LiteLLM uses `openai/<id>`).
- Optional, back-compatible: request field `reasoning_effort` (`low|medium|high`) enables Claude
  extended thinking; `BRIDGE_MAX_CONCURRENT` env → `429 + Retry-After` backpressure;
  `UNSUPPORTED_PARAMS_MODE` (leave `ignore`/`warn` — do NOT `enforce` while LiteLLM forwards
  `temperature`/`max_tokens`).

## Owner inputs (one-time)

1. A **Claude Code subscription** logged in via `claude setup-token` (below).
2. The non-RU egress already exists (UAP VLESS/sing-box) — subfleet routes its upstream through it.

## Step 1 — seed Claude credentials (server-side, DE-egress)

Seed a FRESH `/login` credential authorized through the **same German (DE) VLESS exit** the cluster
will use. Verified subtleties (see the 2026 research notes below):

- **Use interactive `claude` `/login`, NOT `claude setup-token`.** `setup-token` prints a 1-year
  `sk-ant-oat01-` bearer token to the terminal and writes **nothing** to `.credentials.json` (no
  `refresh_token`). subfleet's token-service needs the **access + refresh** pair that only `/login`
  writes to `~/.claude/.credentials.json`. (`login.sh`'s auto-`setup-token` branch is wrong — use
  `--import`.) The 1-year `setup-token` is only usable as an optional `CLAUDE_CODE_OAUTH_TOKEN`
  bridge-env fallback (no refresh), never in the token-service refresh loop.
- **Do NOT reuse your existing `~/.claude/.credentials.json`** from normal Claude Code use — it was
  authorized from another location. Use a CLEAN environment so the credential is DE-authorized.
- **There is no hard server-side IP lock** (Mitiga research; CC issue #21765 — the copy-to-remote
  failure is a missing-refresh 401, not an IP 403). The real `403 Request not allowed` is **client
  gating** — the token is only honored from the bundled CLI, which subfleet spawns. **Still pin all
  egress to one DE exit** for geolocation/behavioral plausibility (a sudden RU-origin request on a
  DE-authorized subscription is exactly what anomaly detection flags) — but understand the mechanism
  is anti-anomaly + client-identity, not a documented IP binding.

Run it **server-side**, through the DE exit, in a clean container with the same bundled `claude`
(operator first stands up a DE-pinned proxy on the host, e.g. `127.0.0.1:12081`, and verifies
`curl -x http://127.0.0.1:12081 https://ifconfig.co/country` prints `DE` BEFORE authorizing):

```bash
mkdir -p ~/claude-seed
podman run -it --rm --network=host --userns=keep-id \
  -e HTTPS_PROXY=http://127.0.0.1:12081 -e HTTP_PROXY=http://127.0.0.1:12081 \
  -e ALL_PROXY=socks5://127.0.0.1:12081 \
  -v ~/claude-seed:/home/bridge/.claude:U \
  --entrypoint /usr/local/bin/claude ghcr.io/<owner>/subfleet-bridge:v0.2.0
# in the REPL run /login -> open the printed URL in ANY browser -> authorize ->
# paste the returned code back. Writes ~/claude-seed/.credentials.json (access+refresh).
```

Then normalize + capture for SOPS (explicit `--import`, NOT the auto branch):

```bash
cd reserch/subfleet
./scripts/login.sh claude --import ~/claude-seed/.credentials.json --stdout > /tmp/credentials.json
```

`/tmp/credentials.json` = the only real secret here (`{access_token, refresh_token, expires_at,
last_refresh}`). Never commit it; SOPS-encrypt it (Step 2) and shred the plaintext.

> Research refs: Anthropic auth docs (setup-token prints a 1-yr token, saves nothing; headless
> paste-code login); Mitiga (no IP binding); CC issues #21765/#42904/#28091 (token shape, ~24h
> access token, Feb-2026 third-party block). Keep the bundled CLI current so its client fingerprint
> stays accepted.

## Step 2 — SOPS-encrypt the subfleet Secret

Create a SOPS-encrypted Secret (in `clusters/prod/infra`) holding:
`BRIDGE_SECRET` (`openssl rand -hex 24`), `ADMIN_TOKEN` (`openssl rand -hex 24`), and the seeded
`credentials.json`. The same `BRIDGE_SECRET` value goes to LiteLLM as `SUBFLEET_KEY`.

## Step 3 — build + import images (registry-less k3s)

The chart has no registry integration; build the two images and import into each node's containerd.

```bash
cd reserch/subfleet
docker compose build          # builds *-bridge (debian+bundled claude CLI) and *-token (musl/scratch)
docker save subfleet-bridge:<tag> | gzip > /tmp/sf-bridge.tgz
docker save subfleet-token:<tag>  | gzip > /tmp/sf-token.tgz
# copy to each k3s node, then on each:
sudo k3s ctr images import /tmp/sf-bridge.tgz
sudo k3s ctr images import /tmp/sf-token.tgz
```

Pin the Helm `image.*.tag` to that tag (never `latest`).

## Step 4 — deploy subfleet via Flux

Add a `HelmRelease` (chart `subfleet/deploy/helm/claude2api`, sourced via a `GitRepository` to subfleet
or a vendored copy) under `clusters/prod/infra`, referencing the SOPS Secret (existing-secret mode).
Key values: `token-service` `replicas:1 + Recreate` (single-writer invariant); bridge `extraEnv`
`BRIDGE_MAX_CONCURRENT=<cap>`; egress — set token-service `PROXY_URL` **and** bridge `CLI_HTTPS_PROXY`
to the **same** exit (the in-cluster `singbox-egress` Service or the ops-1 sing-box). Egress-IP-pin:
keep both pointing at one exit (and matching the `setup-token` IP).

## Step 5 — wire LiteLLM

Promote `clusters/staging-stage3/litellm.yaml`: it already points all cloud groups at the bridge
`api_base` with `api_key: os.environ/SUBFLEET_KEY` and forwards `reasoning_effort`. Fill `SUBFLEET_KEY`
(= `BRIDGE_SECRET`) and `LITELLM_MASTER_KEY` from SOPS; set the real bridge Service DNS + Ollama IP.

## Step 6 — smoke tests

```bash
# in-cluster (or port-forward):
curl http://<bridge>:18902/health                       # 200
curl -H "Authorization: Bearer $BRIDGE_SECRET" http://<bridge>:18902/v1/models   # 4 claude models
# a real completion via LiteLLM:
curl http://<litellm>:4000/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"smart-cloud","messages":[{"role":"user","content":"say hi"}]}'
```

Verify also:
- **Extended thinking** — send `smart-cloud` (forwards `reasoning_effort: high`). subfleet noted the
  *pinned* bundled CLI couldn't be verified to honor thinking on a real image (host CLI dropped the
  flag); **confirm a high-reasoning reply actually thinks** before relying on it. Budget-0 path is safe.
- **Egress** — through the foreign exit (no `403`); check exit country.
- **Backpressure** — burst > `BRIDGE_MAX_CONCURRENT` ⇒ `429`; LiteLLM retries.
- **Fallback** — kill the subscription path ⇒ requests fall to `cheap-local` (Ollama).

## Caveats

- **Single-writer:** never run two token-service refreshers per credential (`replicas:1 + Recreate`,
  or a lease backend). Two refreshers burn the rotating `refresh_token`.
- **Egress-IP pinning:** `setup-token` IP == token-service `PROXY_URL` exit == bridge `CLI_HTTPS_PROXY`
  exit. Mismatch ⇒ `403`.
- **Concurrency ceiling:** one subscription is shared; size `BRIDGE_MAX_CONCURRENT` + LiteLLM rpm to
  the subscription tier.
- **ToS:** subscription-session reuse via the bundled CLI is the compliant pattern; the direct refresh
  is the gray edge. Private self-host = owner's risk. subfleet is AGPL-3.0.
