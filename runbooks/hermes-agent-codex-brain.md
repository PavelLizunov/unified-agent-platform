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
| `ConfigMap hermes-agent-config` | `clusters/prod/infra/hermes-agent-config.yaml` | `config.yaml` + codex `config.toml` |
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
