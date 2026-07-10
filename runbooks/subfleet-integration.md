# subfleet Integration (model backend for LiteLLM)

> **Status (2026-07): LIVE + healthy on v0.3.1.** bridge + token-service pods `1/1 Running`; served
> `claude-opus-4-8` on 2026-07-09 through the pinned `singbox-egress` (DE exit rotated to a live
> ninitux server in #103/#104). Deployed by Flux from `clusters/prod/infra/subfleet.yaml` — **images
> are pulled from GHCR**, no local build. Sections below marked "one-time seed" are historical setup
> notes; the live invariants are the **Caveats** and the **Pinned-egress repoint + re-pin** section.

subfleet (`reserch/subfleet`, Rust `bridge` + `token-service`) is UAP's model backend: an
OpenAI-compatible gateway over a Claude Code (and, after subfleet Phase C, Codex) **subscription**.
LiteLLM points at the subfleet **bridge**; subfleet handles the RU egress and OAuth refresh.

See also the promoted manifests in `clusters/prod/infra/` (`subfleet.yaml`, `subfleet-egress.yaml`,
`litellm.yaml`) and memory `uap-subfleet-integration`. The old `clusters/staging-stage3/` scaffolding
is **archived** (see its README). This runbook is the deploy path for the **Claude** path (Codex is
additive — same bridge, just more model groups, once subfleet `#2/#3` land).

## Contract (from subfleet's integration delta)

- Bridge: `http://<release>-bridge.<ns>.svc:18902/v1`, auth `Bearer <BRIDGE_SECRET>`.
- Models advertised: `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5`
  (LiteLLM uses `openai/<id>`; prod pins `claude-opus-4-8`, the `openai/opus` alias auto-tracks latest).
- Optional, back-compatible: request field `reasoning_effort` (`low|medium|high`) enables Claude
  extended thinking; `BRIDGE_MAX_CONCURRENT` env → `429 + Retry-After` backpressure;
  `UNSUPPORTED_PARAMS_MODE` (leave `ignore`/`warn` — do NOT `enforce` while LiteLLM forwards
  `temperature`/`max_tokens`).

## Owner inputs (one-time)

1. A **Claude Code subscription** seeded via interactive `claude /login` (NOT `setup-token` — see Step 1).
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
  --entrypoint /usr/local/bin/claude ghcr.io/pavellizunov/subfleet-bridge:v0.3.1
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

## Step 3 — images (GHCR pull, NOT local build/import)

**Prod pulls the two images from GHCR** — no more `docker compose build` + `k3s ctr images import`.
The images are published as:

- `ghcr.io/pavellizunov/subfleet-bridge:v0.3.1` (debian + bundled claude CLI)
- `ghcr.io/pavellizunov/subfleet-token:v0.3.1` (musl/scratch)

Nodes pull them with the `ghcr-pull` imagePullSecret (`clusters/prod/infra/ghcr-pull.sops.yaml`),
which the HelmRelease passes via `values.imagePullSecrets`. Pin the tag (never `latest`); the live
pin is `v0.3.1` in `clusters/prod/infra/subfleet.yaml`. To ship a new subfleet version, publish the
GHCR tag from the subfleet repo, then bump both `image.bridge.tag` / `image.tokenService.tag` **and**
the `GitRepository` `ref.tag` in that manifest via a PR.

## Step 4 — deploy subfleet via Flux

This is **already live** in `clusters/prod/infra/subfleet.yaml`: a `GitRepository` (`ref.tag: v0.3.1`,
chart `deploy/helm/claude2api`, pulled with the `subfleet-git-auth` deploy key) + a `HelmRelease`
referencing the SOPS Secret in existing-secret mode. Key values already set there:
`tokenService.replicas: 1` + `store.backend: file` (single-writer invariant); bridge
`BRIDGE_MAX_CONCURRENT=6` + `UNSUPPORTED_PARAMS_MODE=warn`; egress — both `tokenService.proxyUrl` and
`bridge.cliProxy` point at the **same** exit (`http://singbox-egress.uap-system.svc:12080`). Egress-IP
pin: keep both on one exit that matches the exit the credential was authorized through. To change the
version, edit that manifest (see Step 3) via a PR and let Flux reconcile.

## Step 5 — wire LiteLLM

Already promoted to `clusters/prod/infra/litellm.yaml`: it points the cloud groups at the bridge
`api_base` with `api_key: os.environ/SUBFLEET_KEY` and forwards `reasoning_effort`. `SUBFLEET_KEY`
(= `BRIDGE_SECRET`) and `LITELLM_MASTER_KEY` come from `litellm-keys.sops.yaml`. (Note: the LIVE
hermes-agent brain no longer routes through this LiteLLM — it uses the ops-1 local-models-router at
`http://100.82.241.121:8090/v1`, model `qwen-35b`; subfleet/LiteLLM is retained for the owner's other
subscription consumers. See memory `uap-local-models-router`.)

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

## Pinned-egress repoint + re-pin (owner-gated)

subfleet's exit is a **single fixed** VLESS+REALITY server, NOT the rotating `singbox-egress-ha`
urltest pool — the OAuth credential is geo/IP-pinned, so the exit must stay stable. When the pinned
exit dies (or its REALITY `server_name`/IP changes — the 2026-07-09 bricker), repoint by hand:

- **There is NO generator for this config.** `infra/sops/gen-singbox-failover.py` only builds the HA
  urltest pool (`singbox-egress-ha-config.sops.yaml`). The pinned single-exit config
  (`clusters/prod/infra/singbox-egress-config.sops.yaml`) is **hand-maintained SOPS** — decrypt, edit
  the one outbound to the live DE server, re-encrypt.
- **Because the exit IP changes, you MUST re-seed the credential** (Step 1) through the NEW exit so
  the DE-authorized OAuth pin stays plausible, then re-encrypt `subfleet-secrets.sops.yaml`. Reusing
  the old credential from a new-IP exit is exactly the RU-origin anomaly the pin guards against.

```bash
# 1. edit the pinned exit (SOPS; age key lives on uap-home-1). Point the single outbound at a LIVE
#    DE (ninitux) server — host/port/uuid/reality server_name+public_key+short_id:
sops clusters/prod/infra/singbox-egress-config.sops.yaml
# 2. re-seed a DE-authorized credential through the NEW exit (Step 1: /login --import), then
#    re-encrypt the Secret that carries credentials.json:
sops clusters/prod/infra/subfleet-secrets.sops.yaml
# 3. PR both (uap-commit-push); Flux applies the Secrets. sing-box reads its config only at startup
#    and subfleet-egress.yaml has NO config-rev annotation, so ROLL the egress pod after reconcile,
#    then roll subfleet's bridge + token-service deployments so they re-egress + re-read the credential
#    (use the actual deploy names from `kubectl -n uap-system get deploy`):
kubectl -n uap-system rollout restart deploy/singbox-egress
# 4. verify the exit country, then a real completion:
kubectl -n uap-system exec deploy/singbox-egress -- \
  sh -c 'wget -qO- -e use_proxy=yes -e https_proxy=http://127.0.0.1:12080 https://ifconfig.co/country'
#   expect DE. Then a live chat.completions through the bridge:
curl -H "Authorization: Bearer $BRIDGE_SECRET" http://<bridge>:18902/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"claude-opus-4-8","messages":[{"role":"user","content":"ping"}]}'   # expect 200 + reply
```

## Caveats

- **Static token today (refresh dormant):** the live token-service loaded a static long-lived
  credential (expires ~2036, ~10y) and its refresh loop is not firing, so the single-writer rule is
  currently DORMANT. `replicas:1` is kept as a defensive guard; it becomes load-bearing again the
  moment a re-seed installs a short-lived `/login` access+refresh pair.
- **Single-writer:** never run two token-service refreshers per credential (`replicas:1 + Recreate`,
  or a lease backend). Two refreshers burn the rotating `refresh_token`.
- **Egress-IP pinning:** `setup-token` IP == token-service `PROXY_URL` exit == bridge `CLI_HTTPS_PROXY`
  exit. Mismatch ⇒ `403`.
- **Concurrency ceiling:** one subscription is shared; size `BRIDGE_MAX_CONCURRENT` + LiteLLM rpm to
  the subscription tier.
- **ToS:** subscription-session reuse via the bundled CLI is the compliant pattern; the direct refresh
  is the gray edge. Private self-host = owner's risk. subfleet is AGPL-3.0.
