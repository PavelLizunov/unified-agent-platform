> ⚠️ **NAMING COLLISION.** This file is about the **EXTERNAL** open-source project
> **`NousResearch/hermes-agent`** (https://github.com/NousResearch/hermes-agent), **NOT** our bespoke
> `hermes/hermes.py`. They share the name by coincidence (Codex named ours "Hermes" independently). This
> doc evaluates whether to **ADOPT** the NousResearch agent as our harness for the vibe-coding goal.
>
> **Source:** official docs site `hermes-agent.nousresearch.com/docs/` + the `NousResearch/hermes-agent`
> repo, read page-by-page via WebFetch on 2026-06-22. **Version evaluated: v0.17.0** (tag `v2026.6.19`).
> Every claim carries its source URL; unverifiable items are flagged.
>
> **DECISIVE FINDING (read first):** hermes-agent **REQUIRES native OpenAI function-calling** and has
> **NO prompt-based fallback**. Our `LiteLLM → subfleet → Claude-CLI` backend **drops `tools`/`tool_calls`**,
> so it **CANNOT be hermes-agent's brain** — the agent would connect and chat, but every tool (file edit,
> shell, web, memory, delegation, cron) silently goes dark. See **"Compatibility with my self-hosted setup"**
> at the bottom for the realistic integration paths.

---

# NousResearch Hermes Agent — Faithfully-Cited Reference

*Compiled 2026-06-22 from the official docs site `hermes-agent.nousresearch.com/docs/` and the `NousResearch/hermes-agent` GitHub repo. Every claim is followed by its source URL. Anything that could not be confirmed from primary sources is explicitly flagged.*

> **Version at time of writing: v0.17.0** — release tag `v2026.6.19`, "The Reach Release", released 2026-06-19 (prior: v0.16.0 = tag `v2026.6.5`, 2026-06-05). Source: https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.19 and https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5 . The docs site tracks repo `main`. License: MIT. Source: https://github.com/NousResearch/hermes-agent

---

## 0. What it is

Hermes Agent is "the self-improving AI agent built by Nous Research" with "a built-in learning loop — it creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations, and builds a deepening model of who you are across sessions." It runs in the terminal, across 20+ messaging platforms, and in IDEs, from a "$5 VPS, a GPU cluster, or serverless infrastructure." Sources: https://hermes-agent.nousresearch.com/docs/ and https://github.com/NousResearch/hermes-agent

Two entry points: the terminal UI (`hermes`), or the gateway process you talk to from Telegram/Discord/Slack/WhatsApp/Signal/Email/CLI. Source: https://hermes-agent.nousresearch.com/docs/

---

## 1. TOOL CALLING (the decisive question)

**Hermes REQUIRES native OpenAI-style function-calling from the model. There is NO built-in prompt-based / parsed tool protocol that makes it work with an arbitrary chat model.**

- The agent loop calls the model with the messages plus tool schemas and branches on a structured `tool_calls` field in the response: "If tool_calls: execute them, append results, loop back… If text response: persist session… return." Internal message format is OpenAI-shaped: `{"role":"assistant","content":"...","tool_calls":[...]}` and `{"role":"tool","tool_call_id":"...","content":"..."}`. Source: https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop

- The repo's `AGENTS.md` states it bluntly. The loop is `response = client.chat.completions.create(...)`; if `response.tool_calls` it runs them, else it returns. And: **"The model must support native function calling. If using a chat-only model that ignores tool schemas, the framework 'fail[s] silently' — the agent simply won't invoke tools. There is no graceful degradation."** Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/AGENTS.md

- The agent-loop internals page confirms there is **no prompt-based / parsed-tool fallback** documented; it presupposes native tool calling and only converts between API *modes* (`chat_completions`, `anthropic_messages`, `codex_responses`), not between native and prompt-parsed tooling. Source: https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop

- The providers doc makes the failure mode explicit for self-hosted servers: tool calling "requires explicit server-side configuration. Without proper setup, **the model will output tool calls as text**" rather than executing them. Sources: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/integrations/providers.md and https://hermes-agent.nousresearch.com/docs/integrations/providers

- It does NOT assume the literal "Hermes" prompt format at the application layer — internally it speaks the OpenAI function-calling schema. The string "hermes" appears only as the **server-side** tool-call *parser* name you give vLLM (`--tool-call-parser hermes`) so that a Hermes/Qwen-family model's text output is converted back into OpenAI `tool_calls` by the inference server. Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/integrations/providers.md

**`agent.tool_use_enforcement`** is NOT a prompt-based tool mode. It only *nudges* an already-FC-capable model to emit calls instead of describing them:
```yaml
agent:
  tool_use_enforcement: "auto"   # "auto" | true | false | ["model-substring", ...]
```
`"auto"` enables it for models matching `gpt`, `codex`, `gemini`, `gemma`, `grok`; it is **disabled for Claude** (which "already uses tools reliably"); `true` forces it on, `false` off, or pass a list of substrings. Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/configuration.md

**Bottom line:** Hermes cannot run usefully against an endpoint that drops `tools`/`tool_calls`. It will connect and chat, but every tool (file edit, shell, web, memory, delegation) silently goes dark. (See "Compatibility" for the fix.)

---

## 2. MODEL / ENDPOINT CONFIG

**Yes — you can point it at a custom OpenAI-compatible base URL + key.** "Hermes Agent works with any OpenAI-compatible API endpoint. If a server implements `/v1/chat/completions`, you can point Hermes at it." Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/integrations/providers.md

**Exact mechanisms:**

- Interactive: `hermes model` → "Custom endpoint". Source: https://hermes-agent.nousresearch.com/docs/integrations/providers
- `config.yaml` (single custom endpoint):
  ```yaml
  model:
    provider: custom
    base_url: "https://your-endpoint.example.com/v1"
    api_key: "your-key"
  ```
  "When `base_url` is set, the provider field is ignored and Hermes calls that endpoint directly." Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/configuration.md
- Environment variables: `OPENAI_BASE_URL=https://…/v1`, `OPENAI_API_KEY=…`. Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/configuration.md
- Multiple named custom providers (e.g. LiteLLM + local), then `/model custom:<name>:<model>`:
  ```yaml
  custom_providers:
    myendpoint:
      base_url: "https://api.example.com/v1"
      api_key: "${CUSTOM_API_KEY}"
  ```
  Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/configuration.md (also https://hermes-agent.nousresearch.com/docs/integrations/providers)

**Config file paths / precedence:** settings in `~/.hermes/config.yaml` (YAML), secrets in `~/.hermes/.env` (`key=value`), OAuth in `~/.hermes/auth.json`. `hermes config set` auto-routes API keys to `.env`, everything else to `config.yaml`. Precedence: CLI args > `config.yaml` > `.env` > built-in defaults. `${VAR}` substitution is supported inside `config.yaml`. Source: https://hermes-agent.nousresearch.com/docs/user-guide/configuration/

**Built-in / native providers (40+):** Nous Portal, OpenAI (+ Codex), Anthropic, OpenRouter, GitHub Copilot, xAI/Grok, Google Gemini (native generateContent, not OpenAI-compat), AWS Bedrock, Azure AI Foundry, DeepSeek, Qwen/DashScope, z.ai/GLM, Kimi/Moonshot, MiniMax, plus local: **Ollama, LM Studio, vLLM, llama.cpp, NVIDIA NIM, Hugging Face**. Source: https://hermes-agent.nousresearch.com/docs/integrations/providers

**Assumed model capabilities:** (a) **native tool/function calling** (§1); (b) **≥ 64,000 tokens of context** — models below this are "rejected at startup." Warning: "Ollama does not use your model's full context window by default," often 4,096 — you must raise it. Sources: https://hermes-agent.nousresearch.com/docs/getting-started/quickstart , https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/integrations/providers.md

**Self-hosted FC enablement flags** (so a local server emits real `tool_calls`): vLLM `--enable-auto-tool-choice --tool-call-parser hermes`; SGLang `--tool-call-parser qwen` (or appropriate); llama.cpp `--jinja`. Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/integrations/providers.md

---

## 3. MESSAGING / MULTI-DEVICE (drive from a phone)

The gateway is "a single background process that connects to all your configured platforms": Telegram, Discord, Slack, WhatsApp, Signal, Email, CLI. Source: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

**Phone-from-behind-NAT works — default Telegram is OUTBOUND long-polling, no inbound port needed:** "By default, the gateway uses outbound long polling… the gateway makes outbound requests to Telegram's servers to fetch new updates." This "requires no public IP, no inbound ports, and no NAT traversal." Webhook mode (inbound public HTTPS via `TELEGRAM_WEBHOOK_URL`) is **optional**, only recommended for cloud platforms that sleep-on-idle. Source: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram

- Known caveat for restricted networks: aggressive NAT idle-timeouts can silently kill a long poll ("connection reset" every few minutes); fix by shortening the poll: `hermes config set messaging.telegram.poll_timeout 30` (default 60). Source: https://lumadock.com/tutorials/hermes-telegram-gateway-setup (third-party; flagged as non-primary)

**Setup / auth (Telegram example):** BotFather `/newbot` → put `TELEGRAM_BOT_TOKEN` in `~/.hermes/.env` → add `TELEGRAM_ALLOWED_USERS=<ids>` → `hermes gateway` (or `hermes gateway run` foreground). Source: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram

**Authorization model (all platforms):** "by default, the gateway denies all users who are not in an allowlist or paired via DM." Unknown users DMing the bot get a one-time pairing code (e.g. `XKGH5N7P`), approved with `hermes pairing approve telegram XKGH5N7P`; codes expire after 1 hour. Quick all-platform wizard: `hermes gateway setup`. Source: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

> Per-platform polling-vs-webhook is documented in depth only for Telegram. For Discord/Slack/WhatsApp/Signal the messaging index implies persistent gateway connections but gives no per-platform table — **flagged as not fully confirmed.** Source: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

---

## 4. CODING (software-engineering tasks)

**Yes, natively.** The default CLI platform toolset `hermes-cli` bundles `file` (`read_file`, `write_file`, `patch`, `search_files`), `terminal` (`terminal`, `process` = shell execution), `web`, `browser`, `memory`, `skills`, `delegation`, `code_execution`, `cronjob`, etc. There is also a composite `debugging` toolset = file + terminal + web. Source: https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference

- Git: done through the `terminal` shell tool (no dedicated git toolset is listed). Source: https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference
- `execute_code` runs Python that can call Hermes tools programmatically, in a "sandboxed RPC environment." Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/overview
- Checkpoints: automatic working-dir snapshots before file changes, `/rollback` to revert. Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/overview
- `--worktree` runs a chat in an isolated git worktree for parallel work. Source: https://hermes-agent.nousresearch.com/docs/reference/cli-commands/

**It can invoke Claude Code as an external coding agent — via a bundled skill, run as a shell command (not as an internal subagent).** The "Claude Code" skill calls the CLI through the `terminal` tool in print mode, e.g. `terminal(command="claude -p 'Add error handling to all API calls in src/'", workdir="…", timeout=120)`. Prereqs: `npm install -g @anthropic-ai/claude-code`, auth via `claude` OAuth or `ANTHROPIC_API_KEY` (`claude auth login --console` for API-key billing), Claude Code v2.x+. Print mode (`-p`) "runs a one-shot task, returns the result, and exits. No PTY needed," returning JSON (session id, turns, cost USD, tokens) that Hermes reads back. Source: https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code (skill file: https://github.com/NousResearch/hermes-agent/blob/main/skills/autonomous-ai-agents/claude-code/SKILL.md)

---

## 5. DEPLOYMENT & DEPENDENCIES

**Install scripts:** Linux/macOS/WSL2/Termux: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`. Windows PowerShell: `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`. Desktop installer (macOS/Win/Linux) also exists. Source: https://hermes-agent.nousresearch.com/docs/getting-started/quickstart

**What the installer pulls (heaviness for restricted egress):** Python 3.11 (via the `uv` package manager), Node.js v22 (browser automation), ripgrep, ffmpeg, plus repo clone + venv; on Windows also Git Bash/MinGit. So it fetches from **PyPI (via uv), npm (Node 22), and GitHub** — non-trivial for a proxied/restricted network. Source: https://hermes-agent.nousresearch.com/docs/getting-started/installation . Install locations: per-user `~/.hermes/hermes-agent/` + `~/.local/bin/hermes`; root `/usr/local/lib/hermes-agent/`; Nix flake supported. Source: https://hermes-agent.nousresearch.com/docs/getting-started/installation

> The installation page does **not** document offline/air-gapped install — **flagged.** Source: https://hermes-agent.nousresearch.com/docs/getting-started/installation

**Docker (official image):** `nousresearch/hermes-agent:latest`. Gateway in a container:
```bash
docker run -d --name hermes --restart unless-stopped \
  -v ~/.hermes:/opt/data -p 8642:8642 \
  nousresearch/hermes-agent gateway run
```
State volume `/opt/data` ↔ host `~/.hermes/` (config, keys, sessions, skills, memories). Image: Debian 13.4, Python 3.13 (deps via `uv sync --frozen`), Node 22, s6-overlay v3 as PID 1, Playwright+Chromium, ffmpeg, git, ripgrep, docker-cli, openssh-client. Image size **not stated**. Source: https://hermes-agent.nousresearch.com/docs/user-guide/docker

**Kubernetes:** the official Docker page has **no** K8s/Helm mention (flagged). A **community** Helm chart exists (single-writer state-safety guardrails, CRD workflows) per third-party sources — **not official.** Sources: https://hermes-agent.nousresearch.com/docs/user-guide/docker ; https://ashkmb.com/blog/hermes-agent-eks-deployment/ (third-party, flagged)

**Terminal/execution backends:** local, docker, ssh, singularity, modal, daytona. Source: https://hermes-agent.nousresearch.com/docs/user-guide/configuration/

**Always-on external dependencies?** Core is self-hostable: sessions/memory are local **SQLite** (`~/.hermes/state.db`), no cloud required. The only hard external dependency is **an LLM endpoint** (yours or a provider). Optional cloud tools (web search via Firecrawl, image gen via FAL, TTS, cloud browser) route through Nous Portal but are optional. Telemetry: the repo's contribution rules forbid "outbound telemetry without opt-in gating." Sources: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory ; https://github.com/NousResearch/hermes-agent ; https://raw.githubusercontent.com/NousResearch/hermes-agent/main/AGENTS.md

---

## 6. MEMORY / SKILLS / SUBAGENTS / SCHEDULER

- **Memory (local, no cloud):** active files `MEMORY.md` + `USER.md` in `~/.hermes/memories/`; sessions in **SQLite `~/.hermes/state.db` with FTS5 full-text search**. `session_search` runs direct FTS5 queries (no LLM, ~20 ms). Optional external providers (Honcho, Mem0, …) exist but aren't required. Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- **Skills / learning loop:** skills are progressive-disclosure markdown (`SKILL.md`, YAML frontmatter, `description ≤60 chars`) under `~/.hermes/skills/`, conforming to the **agentskills.io** open standard. The agent autonomously creates/edits skills via `skill_manage` after complex tasks, gated by `skills.write_approval`. Hub install/browse/search; all hub skills security-scanned. Background **curator** (`hermes curator`). Sources: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills ; https://hermes-agent.nousresearch.com/docs/reference/cli-commands/
- **Subagents:** `delegate_task` (toolset `delegation`) spawns isolated child agents (own context/terminal/toolset), **3 concurrent by default (configurable)**; accepts a `tasks` array for batch parallel runs; v0.17 adds background subagents with watch-windows. Sources: https://hermes-agent.nousresearch.com/docs/user-guide/features/overview ; https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference ; https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.19
- **Scheduler:** built-in cron via the `cronjob` tool and `hermes cron` CLI (`list/create/pause/resume/run`, `--skill`), delivery to any messaging platform; v0.17 ships a pluggable CronScheduler. Sources: https://hermes-agent.nousresearch.com/docs/reference/cli-commands/ ; https://hermes-agent.nousresearch.com/docs/user-guide/features/overview ; https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.19

---

## 7. SECURITY

- **Execution sandboxing (3 backends):** *local* (host, full dangerous-command approval), *docker* (`--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 256`, size-capped tmpfs; "the container itself is the security boundary"), *ssh* (remote exec, keeps approval checks). Source: https://hermes-agent.nousresearch.com/docs/user-guide/security
- **Permission model (3 tiers):** Manual (default, always prompt), Smart (aux-LLM risk assessment auto-approves low-risk / auto-denies dangerous), Off (= `--yolo`). CLI choices: once / session / always / deny (default deny). Source: https://hermes-agent.nousresearch.com/docs/user-guide/security
- **Hardline blocklist (always, even YOLO):** `rm -rf /`, fork bombs, formatting mounted roots, piping untrusted URLs to a shell, +30 flagged categories. **Tirith** pre-exec scanner detects homograph spoofing, pipe-to-interpreter, terminal-injection. Source: https://hermes-agent.nousresearch.com/docs/user-guide/security
  - **UAP deployment note (2026-07-24):** the above describes UPSTREAM capability, not UAP's deployed state. Tirith is **INERT** in the deployed hermes-agent — `HERMES_DISABLE_LAZY_INSTALLS=1` disables lazy install, so the Tirith binary is not installed, and it does not scan the Codex brain path regardless (the brain's shell is the Codex subprocess, not hermes's terminal tool). The real exec path is the Codex brain (`danger-full-access`, `approval_policy=never`), which bypasses hermes's approval/scan/write-safe stack entirely; the pod is the sole boundary. See the `codex-config.toml` note in `clusters/prod/infra/hermes-agent-config.yaml` and `SECURITY-REMEDIATION-2026-07-24.md`.
- **Secrets:** `execute_code`/`terminal` strip env vars whose names contain `KEY`/`TOKEN`/`SECRET`/`PASSWORD`/`CREDENTIAL`/`PASSWD`/`AUTH` by default; opt-in passthrough via `terminal.env_passthrough` or skill `required_environment_variables`. MCP error messages redact `ghp_…`/`sk-…`/bearer tokens. API keys in `~/.hermes/.env`; pairing files `chmod 0600`. Source: https://hermes-agent.nousresearch.com/docs/user-guide/security
- **Network/egress:** SSRF protection always on — blocks RFC1918, loopback, link-local, CGNAT `100.64.0.0/10`, cloud metadata; fail-closed on DNS failure; redirects re-validated. `security.allow_private_urls: true` to reach LAN services (e.g. local Ollama); `security.website_blocklist` to restrict domains. Source: https://hermes-agent.nousresearch.com/docs/user-guide/security
- **Production checklist:** prefer `terminal.backend: docker`, avoid `GATEWAY_ALLOW_ALL_USERS=true`, DM pairing + allowlists, CPU/mem/disk limits + `terminal.cwd`, run non-root, watch `~/.hermes/logs/`. Source: https://hermes-agent.nousresearch.com/docs/user-guide/security

---

## 8. Exact doc/repo pages read (open to verify)

Official docs: https://hermes-agent.nousresearch.com/docs/ · /getting-started/quickstart · /getting-started/installation · /user-guide/configuration/ · /user-guide/features/overview · /user-guide/features/tools · /reference/toolsets-reference · /user-guide/features/memory · /user-guide/features/skills · /user-guide/security · /user-guide/messaging/ · /user-guide/messaging/telegram · /reference/cli-commands/ · /integrations/providers · /developer-guide/agent-loop · /developer-guide/adding-providers/ · /user-guide/docker · /user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code

GitHub (`main`): https://github.com/NousResearch/hermes-agent · /AGENTS.md · /website/docs/integrations/providers.md · /website/docs/user-guide/configuration.md · /releases/tag/v2026.6.19 · /releases/tag/v2026.6.5 · /blob/main/skills/autonomous-ai-agents/claude-code/SKILL.md

Third-party (flagged, NOT authoritative): https://lumadock.com/tutorials/hermes-telegram-gateway-setup ; https://ashkmb.com/blog/hermes-agent-eks-deployment/

---

## Compatibility with my self-hosted setup

**Does it fit the goal (multi-device vibe-coding, phone-driven, load spread, autonomous coding)?** Architecturally, **yes, very well** — *except* for one hard blocker at the model layer.

**What specifically BREAKS against a no-native-function-calling gateway:** Hermes is a tool-calling agent end to end. Its loop calls `chat.completions.create` with tool schemas and acts only on a structured `tool_calls` field; against a chat-only endpoint it **"fail[s] silently — the agent simply won't invoke tools. There is no graceful degradation."** Source: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/AGENTS.md . Concretely, our `LiteLLM → subfleet → Claude-CLI` backend (drops `tools`/`tool_calls`) lets Hermes connect and chat, but `read_file`/`write_file`/`patch`/`terminal`/`web_search`/`memory`/`delegate_task`/`cronjob` all do nothing. There is **no prompt-based tool mode** to fall back to; `tool_use_enforcement` only nudges models that *already* support FC and is even disabled for Claude. Sources: https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop ; https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/configuration.md

**Realistic integration paths (in order of fit):**

1. **Point Hermes at a function-calling-capable backend through the proxy — do NOT use the FC-less Claude-CLI path as Hermes's brain.** Hermes accepts any custom OpenAI-compatible `base_url`+`api_key` (incl. a `custom_providers` entry for our LiteLLM). The catch: LiteLLM must forward to a real FC model (Anthropic Messages or an OpenAI-compatible FC model) through our foreign egress. Our subfleet/Claude-CLI backend does NOT qualify.

2. **Run a local function-calling model and target it.** Hermes natively supports Ollama / vLLM / llama.cpp / LM Studio, but you MUST enable server-side tool parsing or "the model will output tool calls as text": vLLM `--enable-auto-tool-choice --tool-call-parser hermes`, llama.cpp `--jinja`; raise context to ≥64k. A Nous **Hermes**-series or Qwen model fits the `hermes` parser natively — the cleanest fully-self-hosted, no-foreign-egress option (but needs the hardware to serve it).

3. **Keep the FC-less Claude subscription for the *coding execution*, but let Hermes's brain be a different (FC) model.** Hermes's bundled "Claude Code" skill shells out to `claude -p` print mode. So Hermes's own model can be a local/foreign FC model (paths 1–2), while heavy code edits are delegated to the Claude CLI as a subprocess — exactly the "spread load across engines" pattern, reusing existing Claude auth. Source: https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code

4. **There is NO "prompt-based mode" to enable in Hermes.** If we cannot provide *any* FC-capable endpoint, Hermes is not usable as an agent. The only "Hermes format" parser lives in the inference server (vLLM), not the app.

**Fits our constraints well (confirmed):** phone driving via **outbound Telegram long-poll — no inbound port / NAT-friendly**; fully local SQLite/FTS5 memory, no mandatory cloud; official Docker image + community Helm; LAN-model access via `security.allow_private_urls`; autonomous coding with checkpoints/rollback + `--worktree`, plus subagents and cron.

**Restricted-egress caveat:** the installer fetches from PyPI (uv), npm (Node 22), GitHub; the Docker image bakes those in, so on a proxied network **prefer the prebuilt `nousresearch/hermes-agent` image** over `curl|bash`. Source: https://hermes-agent.nousresearch.com/docs/user-guide/docker
