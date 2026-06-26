# hermes-agent in k3s with the Codex brain (Track A2)

> Deploy the external **NousResearch hermes-agent** gateway as a Flux-managed k3s workload, with its
> brain = the **Codex / ChatGPT-Plus subscription** (`codex_app_server` runtime) reached through the
> in-cluster `singbox-egress`. This is **Phase A2** of [docs/next-steps.md](../docs/next-steps.md).
>
> **Status: manifests authored + recipe proven in the real image (2026-06-24); first Flux deploy pending.**
> Why each setting is what it is was established by running the real `nousresearch/hermes-agent:latest`
> (v0.17.0) image in-cluster until `hermes chat -q` drove the Codex brain to execute a tool end-to-end.

## What gets deployed

| Object | File | Purpose |
|---|---|---|
| `Secret codex-auth` (SOPS) | `clusters/prod/infra/codex-auth.sops.yaml` | the Codex CLI `auth.json` (owner's ChatGPT-Plus OAuth) — the seed |
| `ConfigMap hermes-agent-config` | `clusters/prod/infra/hermes-agent-config.yaml` | soft `config.yaml` + codex `config.toml` + **managed brain overlay** (`managed-config`) + managed-env proxy/allowlist |
| `PVC hermes-agent-data` + `Deployment hermes-agent` | `clusters/prod/infra/hermes-agent.yaml` | state on `local-path`; gateway + bootstrap initContainer |

Image: official `nousresearch/hermes-agent:latest` (Docker Hub — reachable from RU, verified). No custom build.

## The proven recipe (the 4 non-obvious knobs)

1. **Credentials live in hermes's OWN store** `$HERMES_HOME/auth.json` (=`/opt/data/auth.json`), **not**
   `~/.codex/auth.json` — hermes deliberately does not auto-import the Codex CLI file (single-use refresh
   tokens). The `bootstrap` initContainer converts the seed into hermes's format with hermes's own functions:
   `_import_codex_cli_tokens()` → `_save_codex_tokens()`. It seeds **only if `/opt/data/auth.json` is absent**,
   so hermes's own refreshed token survives pod restarts.
2. **`model.openai_runtime: codex_app_server`** — hand each turn to the **codex CLI subprocess**. The default
   `codex_responses` mode does **not** work in-cluster: hermes's Python `httpx` cannot reach `chatgpt.com`
   through the singbox proxy ("Connection error"). The codex CLI (Rust/reqwest) goes through fine.
3. **codex `config.toml`: `sandbox_mode = "danger-full-access"`, `approval_policy = "never"`** — codex's
   bubblewrap sandbox cannot initialise in the restricted container (no user namespaces) → file writes fail
   with "sandbox permission error". The **pod itself is the security boundary**, so codex's own sandbox is off.
4. **Runtime env:** runs as **uid 10000 (hermes)** — the image's s6 `/init` starts as root and drops services
   to 10000, so the pod starts as root and `fsGroup: 10000` + an initContainer `chown` make `/opt/data`
   writable. `CODEX_HOME=/opt/data/.codex`, `HTTPS_PROXY/HTTP_PROXY=http://singbox-egress.uap-system.svc:12080`,
   `NO_PROXY` excludes cluster + tailnet ranges. codex is `npm i -g`'d into `/opt/data/.local` (already on the
   image PATH).

## Create / rotate the `codex-auth` SOPS secret

The seed is the Codex CLI `auth.json` produced by `codex login` (owner's own ChatGPT Plus). Encrypt it where
`sops` + the repo live (uap-ops-1); never commit the plaintext.

```bash
# on uap-ops-1, in the repo clone, with the plaintext auth.json at /tmp/ca.json (mode 600):
kubectl create secret generic codex-auth -n uap-system \
  --from-file=auth.json=/tmp/ca.json --dry-run=client -o yaml \
  > clusters/prod/infra/codex-auth.sops.yaml
sops -e -i clusters/prod/infra/codex-auth.sops.yaml   # .sops.yaml rule encrypts data/stringData
shred -u /tmp/ca.json
grep -q 'ENC\[' clusters/prod/infra/codex-auth.sops.yaml && echo encrypted-ok
```

## Deploy + verify

1. Land the manifests via PR (see the `uap-commit-push` skill); Flux reconciles `clusters/prod`.
2. Verify (see `uap-flux-deploy`):
   ```bash
   kubectl -n uap-system get pod -l app=hermes-agent          # Running, initContainer completed
   kubectl -n uap-system logs deploy/hermes-agent --all-containers | tail
   ```
3. **CLI round-trip (the A2 "Done"):** exec a one-shot that must invoke a tool against the Codex brain:
   ```bash
   kubectl -n uap-system exec deploy/hermes-agent -- \
     env HOME=/opt/data hermes chat -q \
     "Create a file /opt/data/a2-proof.txt containing exactly BRAIN-OK, then reply done." --max-turns 6 --yolo
   kubectl -n uap-system exec deploy/hermes-agent -- cat /opt/data/a2-proof.txt   # -> BRAIN-OK
   ```
   `BRAIN-OK` means hermes drove the Codex brain through the egress and executed a tool. **Done.**

## Telegram (A3) + the managed-scope proxy

Phone control via Telegram (outbound long-poll — no inbound port). Two non-obvious facts drove the wiring:

- **`api.telegram.org` is blocked direct from the cluster** — reachable only through `singbox-egress` (verified:
  httpx→proxy = 302, direct = timeout). So Telegram MUST use the egress proxy.
- **hermes's per-profile `os.environ` is isolated** (multiplex mode): the Telegram adapter (`resolve_proxy_url`,
  reads `os.environ`) and `TELEGRAM_ALLOWED_USERS` (read via `os.getenv`) do **not** see `/opt/data/.env` (that only
  feeds hermes *config*, where the bot token is read as `self.config.token`). The egress proxy + allowlist therefore
  go in hermes's **managed scope** — `/etc/hermes/.env` (mounted from the `managed-env` ConfigMap key) — which hermes
  loads **last with `override=True` into `os.environ`**, authoritative for every profile **and subprocess**. The same
  mechanism is what gives the **gateway-driven Codex brain** the proxy, since codex is spawned with `os.environ.copy()`.

Layout:
- `Secret hermes-agent-telegram` (SOPS) → `TELEGRAM_BOT_TOKEN` → initContainer writes `/opt/data/.env` (hermes config).
- ConfigMap `managed-env` → `/etc/hermes/.env`: `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` + `TELEGRAM_ALLOWED_USERS`.

Rotate the bot token: re-create `hermes-agent-telegram.sops.yaml` (same flow as `codex-auth`, key `token`), then
roll the pod. Verified end-to-end 2026-06-24: a phone message → Codex brain (gpt-5.5) → reply.

## Config ownership: GitOps owns the brain, the dashboard owns the rest (v5 hybrid)

The owner edits soft config from the web dashboard; GitOps owns only the critical brain. This works because
hermes has a **managed config overlay** that deep-merges `/etc/hermes/config.yaml` **per-leaf** over the user/PVC
`~/.hermes/config.yaml` (= `/opt/data/config.yaml`), and **managed wins per-leaf** over user config *and* env. A
dashboard/CLI write to a managed key is refused **loudly** ("managed by your administrator") instead of silently
reverting on the next restart.

| Tier | Where | Owner |
|---|---|---|
| Brain (`model.provider`/`openai_runtime`/`model`) | ConfigMap `managed-config` → `/etc/hermes/config.yaml` (RO) | **GitOps** (dashboard refused) |
| Egress proxy + `TELEGRAM_ALLOWED_USERS` | ConfigMap `managed-env` → `/etc/hermes/.env` (RO) | **GitOps** (authz boundary) |
| Telegram bot token | `/opt/data/.env`, the `TELEGRAM_BOT_TOKEN=` line replaced-in-place each boot from the SOPS secret | **GitOps** (rotate by rolling) |
| Soft config (`display.*`, `agent.*`, platform toggles), other platform tokens (Discord/MCP), `/sethome` chat-IDs | `/opt/data/{config.yaml,.env}` | **dashboard** (persists across restarts) |

The initContainer **seeds `/opt/data/config.yaml` + `/opt/data/.codex/config.toml` only if absent** (so dashboard
edits survive a roll) and **replaces only the `TELEGRAM_BOT_TOKEN=` line** in `/opt/data/.env` each boot (so token
rotation still works while dashboard-written lines are preserved). A **fail-closed guard** aborts the boot (CrashLoop)
if the managed brain overlay is missing/malformed — because the managed loader is fail-OPEN and the brain has **no PVC
fallback on a fresh volume**.

**Operational caveats of seed-if-absent (existing PVC):**
- To push a NEW `config.yaml` default or a changed codex `config.toml` (e.g. `sandbox_mode`) onto an EXISTING PVC, the
  ConfigMap change alone is **not** enough — delete the PVC file first, then roll:
  `kubectl -n uap-system exec deploy/hermes-agent -- rm /opt/data/.codex/config.toml` (or `/opt/data/config.yaml`).
  The **brain is exempt** (it is the managed overlay, refreshed every boot).
- The stale inline `model:` block left in an existing PVC `config.yaml` is harmless (the managed overlay wins
  per-leaf); drop it once via exec+edit if you want `hermes config` to show the brain purely as managed-sourced.

Verify after rollout:
```bash
kubectl -n uap-system exec deploy/hermes-agent -- env HOME=/opt/data hermes config | grep -i managed   # brain leaves shown as managed
```
plus the CLI round-trip above (brain still drives a tool), and confirm a dashboard-added Discord token survives a roll.

## Coding workers — `claude -p` + `codex exec` (A4/A5)

Two coding engines, both installed on the PVC (`/opt/data/.local/bin`) and reaching their providers through
`singbox-egress-ha`:

- **`claude -p` (Claude Max OAuth)** — token in env `CLAUDE_CODE_OAUTH_TOKEN` from the SOPS secret
  `hermes-agent-claude`. Run headless + isolated:
  `claude -p "<task>" -w <name> --permission-mode acceptEdits --output-format json` — `-w` runs in an isolated git
  worktree (`.claude/worktrees/<name>`, own branch). Deny-first `/opt/data/.claude/settings.json` blocks accidental
  reads of the in-pod auth stores + repo `*.sops.yaml` (defense-in-depth; the pod is the real boundary, Bash is open).
- **`codex exec "<task>"` (ChatGPT/Codex)** — same Codex auth as the brain; edits autonomously (sandbox
  `danger-full-access`, approval `never`).

Both verified in-cluster (2026-06-26): each edits files end-to-end through the egress.

### Re-issue the Claude Max token (server-side device-flow, no owner install needed)

The token is a **portable** 1-year `setup-token` (used via `CLAUDE_CODE_OAUTH_TOKEN`, NOT IP-pinned):
1. In the pod, run `claude setup-token` under a PTY with stdin from a held-open FIFO (no tmux available — use
   `script -qfc "claude setup-token" /tmp/out` with stdin `<&9` where `exec 9<>/tmp/fifo`); capture the printed
   `https://claude.com/cai/oauth/authorize?...` URL.
2. Owner opens the URL (logged into Claude Max), authorizes, copies the `code#state`.
3. Write `code#state` to the FIFO, then a `\r` (the trailing newline alone does NOT submit).
4. The token prints — the TUI letter-spaces the prefix hyphens, so reconstruct `sk-ant-oat01-` + body. SOPS-encrypt
   it into `hermes-agent-claude` (key `oauth-token`), `shred` the plaintext, roll the pod.

## Caveats / follow-ups

- **Shared refresh-token lineage:** the seed shares the Codex CLI's single-use refresh token. If the owner's
  **desktop** Codex CLI / VS Code refreshes with the same ChatGPT account, hermes's in-cluster token can break.
  Hermes's own device-login (an independent session) is cleaner but is interactive and its httpx device-poll hit
  the same proxy issue — deferred. Re-seed (rotate the secret) if the brain starts 401-ing.
- **Gateway-stays-up:** A2 has no messaging platform yet (Telegram = A3). Confirm `gateway run` stays Running;
  if it exits without a platform, the round-trip above (via `exec`) still proves the brain.
- **Hardening (later):** bake codex into a pinned GHCR image instead of `npm i -g` at boot; run fully non-root;
  set a real permission policy for autonomous (Telegram-driven) runs.
- **Desktop is not the host:** the brain is the always-on Codex cloud subscription, not the RTX — this workload
  is independent of the GPU desktop (that's the opportunistic fallback brain, Track A1 / A5).
