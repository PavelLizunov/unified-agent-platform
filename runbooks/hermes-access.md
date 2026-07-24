# Talking to Hermes from any device

Hermes-agent runs as a single pod in k3s (ns `uap-system`, node `uap-home-2`). It has **three** access
surfaces — all live, pick by what you're doing:

| You want... | Use | Platform |
|---|---|---|
| A coding REPL, "like Claude Code" | `hermes` terminal (SSH -> pod CLI) | Win / Mac / Linux |
| Sessions / config / GUI | Web dashboard, or Hermes Desktop app | Win / Mac / browser |
| A quick poke from the phone | Telegram bot | anywhere |

The Hermes **CLI is pod-local** (runs against the pod's own state). There is no remote-CLI protocol — the
only remote surfaces are the dashboard (HTTP/WebSocket) and Telegram. The terminal REPL below is just SSH
into the pod, wrapped in a one-word command.

## Reachability (which IP)

Everything is on the tailnet, but **from the Windows box use LAN IPs** — Windows -> tailnet flakes
(CLAUDE.md). Mac/Linux/phone off-LAN use tailnet.

| Host | LAN | Tailnet |
|---|---|---|
| ops-1 (SSH jump for the REPL) | `192.168.0.203` | `100.82.241.121` |
| uap-home-2 (dashboard node) | `192.168.0.202` | `100.94.228.67` |
| uap-home-1 (dashboard node too) | `192.168.0.201` | `100.106.223.120` |

The dashboard NodePort `:30911` answers on **any** node IP.

## 1. Terminal REPL (`hermes`)

The wrapper `~/bin/hermes-chat` on ops-1 does `kubectl exec` into the pod and runs `hermes chat`, passing
args through. So `hermes` = REPL, `hermes -c` = continue last session, `hermes -q '...'` = one-shot.

**Windows** — `$PROFILE` (`C:\Users\<you>\Documents\WindowsPowerShell\profile.ps1`), ASCII-only for PS 5.1:
```powershell
function hermes {
    # single-quote each arg for the remote bash so quotes/spaces survive PS -> ssh -> bash
    $rc = ($args | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
    ssh -t uap@192.168.0.203 "~/bin/hermes-chat $rc"
}
```

**Mac / Linux** — `~/.zshrc` or `~/.bashrc`:
```bash
hermes() { ssh -t uap@100.82.241.121 "~/bin/hermes-chat $*"; }
```

**SSH keepalive + instant reconnect** (Mac/Linux `~/.ssh/config`; ControlMaster is unsupported on Windows
OpenSSH, omit those two lines there):
```
Host 100.82.241.121 192.168.0.203
  User uap
  ServerAliveInterval 30
  ServerAliveCountMax 4
  ControlMaster auto
  ControlPath ~/.ssh/cm-%r@%h-%p
  ControlPersist 10m
```
Dropped connection? Just re-run `hermes` — `hermes -c` resumes the last session (state lives in the pod's
SQLite). For a REPL that survives the drop server-side, wrap in tmux (already on ops-1):
`ssh -t uap@100.82.241.121 "tmux new -A -s hermes '~/bin/hermes-chat'"` (note: tmux variant can't pass
`-q` args — keep a second alias for one-shots).

## 2. Web dashboard / Hermes Desktop app

Dashboard: `http://<node-ip>:30911`, basic auth (user `pavel`, password in the `hermes-agent-dashboard`
SOPS Secret).

> **Dashboard root (`/`):** v0.19 is **expected to serve `/`** — upstream fixed the password-provider
> OAuth auto-redirect path that made `/` 500 in v0.18. **Verify both `/` and `/login` work live after
> the upgrade** (smoke step in `docs/hermes-v019-upgrade.md`). Going to **`/login` directly** (e.g.
> bookmark `http://192.168.0.202:30911/login`) is only the **v0.18 rollback fallback**: on v0.18 the
> root `/` auto-redirects to a login route that 500s (BasicAuthProvider vs an OAuth-redirect code path).
> The REPL and Telegram are unaffected either way.

**Hermes Desktop app** (best GUI, Win + Mac) — install from
[hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/), then Settings -> Gateway ->
**Remote gateway** -> URL `http://192.168.0.202:30911`, sign in `pavel`. The app posts credentials
directly and does NOT depend on the browser root-redirect path, so the v0.18-only `/login` fallback does
not apply to it. The desktop app and the browser (`/` and `/login`) are separate surfaces — confirm both
in the post-upgrade smoke. Install pull blocked from RU? Route through the VLESS proxy `192.168.0.202:30880`.
"Install as app" in Chrome/Edge on the dashboard gives an app icon without installing anything.

## 3. Telegram

The bot is already wired (token in the `hermes-agent-telegram` Secret, allowlist in the managed `.env`).
Best for ideas/status from the phone. It's a chat, not a coding terminal.

## See also

- `runbooks/hermes-agent-codex-brain.md` — the brain (Codex) + auth.
- `runbooks/hermes-agent-dr.md` — pinned runtime + DR.
