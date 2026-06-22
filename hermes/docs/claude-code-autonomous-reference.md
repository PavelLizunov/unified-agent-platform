# Claude Code — autonomous / headless reference (ground-truth for the Hermes coding worker)

> **Source:** the OFFICIAL Claude Code documentation at **https://code.claude.com/docs** (exact pages
> listed in §9 below). **Fetched:** June 2026, via the `claude-code-guide` research agent, page by page
> with WebFetch. **Purpose:** the verified basis for building Hermes's autonomous coding capability (run
> Claude Code unattended in a sandboxed workspace: idea → edit → test → deploy → report). This is a
> curated reference WITH citations — every fact lists the URL it came from; verify against the live page.
> This file is the thing we sync on.

---

# AUTONOMOUS CODING WORKER — Comprehensive Official Reference

## 1. HEADLESS / NON-INTERACTIVE MODE

### Entry Point: `claude -p` (Print Flag)
**URL:** https://code.claude.com/docs/en/cli-reference · **URL:** https://code.claude.com/docs/en/headless

`-p` / `--print` runs Claude Code non-interactively — the primary way to invoke it from scripts/CI/automation.
```bash
claude -p "Your task description here"
```
Exit codes are not explicitly documented; standard shell convention (0 = success, non-zero = failure). With `--output-format json`, parse the response for error detail.

### Output Formats — `--output-format` (text | json | stream-json)
**URL:** https://code.claude.com/docs/en/cli-reference · **URL:** https://code.claude.com/docs/en/headless
```bash
claude -p "query" --output-format text          # default, plain text
claude -p "query" --output-format json           # structured: .result, .session_id, .total_cost_usd, metadata
claude -p "query" --output-format stream-json     # newline-delimited JSON events
```
Extract the result: `claude -p "..." --output-format json | jq -r '.result'`
Stream tokens: `--output-format stream-json --verbose --include-partial-messages` then filter `.event.delta.text`.

### Input / piping
**URL:** https://code.claude.com/docs/en/cli-reference
`--input-format text|stream-json`; `--include-partial-messages` (needs `--print` + `--output-format stream-json`).
Piped stdin is capped at **10MB** (v2.1.128). `cat build-error.txt | claude -p 'explain this error'`.

### Bare mode (faster, deterministic) — `--bare`
**URL:** https://code.claude.com/docs/en/headless
Skips hooks/skills/plugins/MCP/auto-memory/CLAUDE.md discovery; KEEPS Bash + file read + file edit. Good for CI determinism. Pass context explicitly via `--append-system-prompt`, `--settings`, `--mcp-config`.

### Structured outputs — `--json-schema`
**URL:** https://code.claude.com/docs/en/headless
```bash
claude -p "Extract function names from auth.py" --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}},"required":["functions"]}'
```
Response includes `.structured_output` validated against the schema.

---

## 2. CLAUDE AGENT SDK (programmatic)
**URL:** https://code.claude.com/docs/en/agent-sdk/overview

- **TypeScript:** `npm install @anthropic-ai/claude-agent-sdk`
- **Python:** `pip install claude-agent-sdk` (Python 3.10+)

Main entrypoint `query()` (async iterator over messages):
```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
async def main():
    async for message in query(prompt="Find and fix the bug in auth.py",
                               options=ClaudeAgentOptions(allowed_tools=["Read","Edit","Bash"])):
        print(message)
asyncio.run(main())
```
`ClaudeAgentOptions`: `allowed_tools`, `permission_mode`, `hooks`, `agents`, `mcp_servers`, `resume`, `setting_sources`.
Capture `session_id` from the init `SystemMessage`; resume later via `resume=session_id`. Final answer is the `ResultMessage` (`.result`).

---

## 3. TOOLS & PERMISSIONS (autonomous runs)
**URL:** https://code.claude.com/docs/en/agent-sdk/overview · **URL:** https://code.claude.com/docs/en/permissions · **URL:** https://code.claude.com/docs/en/cli-reference

Built-in tools: **Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, Monitor, AskUserQuestion** (last is interactive only).

`--permission-mode` (and SDK `permission_mode`) values:
- `default` — prompts on first use of each tool. **Not for unattended.**
- `acceptEdits` — auto-approves file edits + common fs commands (mkdir/touch/mv/cp); other shell + network still prompt.
- `plan` — read-only exploration, no source edits.
- `auto` — auto-approves with background safety checks (research preview; may block unsafe calls).
- `dontAsk` — denies tools unless pre-approved via `--allowedTools` / `permissions.allow`.
- `bypassPermissions` — **DANGER**: skips prompts except explicit `ask` rules + root/home deletions. Only in isolated containers/VMs. (`--dangerously-skip-permissions` = same.)

Allowlists/denylists: `--allowedTools "Bash,Read,Edit"` / `--disallowedTools "WebSearch,WebFetch"`.
Scoped rules: `Bash(npm run *)`, `Read(/src/**)`, `Edit(/src/**)`, `WebFetch(domain:*.example.com)`.
**Deny-first precedence:** deny rules beat ask beat allow — a deny blocks even a more-specific allow.
`--permission-prompt-tool <mcp_tool>` routes approvals to an MCP tool for unattended decisions.

### Sandboxing
**URL:** https://code.claude.com/docs/en/sandboxing
OS-level Bash isolation (filesystem + network boundaries); on Windows via WSL 2. With `autoAllowBashIfSandboxed: true` (default), sandboxed Bash runs without prompting. Defense-in-depth with permission rules.

---

## 4. WORKSPACE / CONTEXT
**URL:** https://code.claude.com/docs/en/memory · **URL:** https://code.claude.com/docs/en/cli-reference · **URL:** https://code.claude.com/docs/en/mcp

Discovers the project via `.git/`, walking up for CLAUDE.md, loading `.claude/`.
CLAUDE.md load order (broad→specific): managed policy → `~/.claude/CLAUDE.md` → `./CLAUDE.md` (or `./.claude/CLAUDE.md`) → `./CLAUDE.local.md`. Supports `@path` imports + path-scoped rules in `.claude/rules/`.
`--add-dir ../apps ../lib` grants extra dirs. `--mcp-config ./mcp.json` (+ `--strict-mcp-config`) loads MCP servers (stdio/http).

---

## 5. SESSIONS
**URL:** https://code.claude.com/docs/en/sessions · **URL:** https://code.claude.com/docs/en/cli-reference

`--continue`/`-c` (most recent), `--resume <name|uuid>`, `--session-id <uuid>`, `-n <name>`. SDK: `resume=session_id`.
`--no-session-persistence` (print mode) or `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`. Transcripts: `~/.claude/projects/<project>/<session-id>.jsonl`; default cleanup 30 days.

---

## 6. AUTH in headless / CI
**URL:** https://code.claude.com/docs/en/headless · **URL:** https://code.claude.com/docs/en/env-vars

- `ANTHROPIC_API_KEY=sk-...` — recommended for CI/containers; in `-p` mode always used when present.
- `ANTHROPIC_AUTH_TOKEN` — custom `Authorization: Bearer <value>`.
- Third-party: `CLAUDE_CODE_USE_BEDROCK=1` / `CLAUDE_CODE_USE_VERTEX=1` (+`ANTHROPIC_VERTEX_PROJECT_ID`) / `CLAUDE_CODE_USE_FOUNDRY=1`.
- (Subscription/OAuth: `claude setup-token` issues a long-lived token; that page did not fetch cleanly — verify separately. This matters for us: our workers auth via the SUBSCRIPTION through subfleet's DE egress, not an API key.)

---

## 7. KEY FLAGS for an autonomous coding worker
**URL:** https://code.claude.com/docs/en/cli-reference

| Flag | Purpose |
|---|---|
| `-p`, `--print` | headless, exit after response |
| `--output-format json` / `stream-json` | structured result / streamed events |
| `--allowedTools "Read,Edit,Write,Bash"` | pre-approve the coding tools |
| `--permission-mode acceptEdits` (or `bypassPermissions` in a sandbox) | unattended approval |
| `--dangerously-skip-permissions` | skip all prompts (= bypassPermissions; sandbox only) |
| `--add-dir <dirs>` | extra workspace access |
| `--mcp-config ./mcp.json` (+ `--strict-mcp-config`) | external tools |
| `--max-turns N` | cap agentic turns (safety) |
| `--max-budget-usd X` | spend cap (safety) |
| `--effort low\|medium\|high\|xhigh\|max` | reasoning effort |
| `--continue` / `--resume <id>` / `--session-id` | persistence |
| `--model <id>` | model override |
| `--append-system-prompt[-file]` / `--system-prompt[-file]` | inject instructions |

→ **Worker recipe (draft):** `ANTHROPIC_*` auth → `claude -p "<task>" --output-format json --allowedTools "Read,Write,Edit,Bash" --permission-mode bypassPermissions --max-turns N --max-budget-usd X` inside an ISOLATED sandbox container with the repo as the workdir; parse `.result`; the worker self-runs tests via Bash before reporting done.

---

## 8. NOT documented (gaps to verify ourselves)
- Explicit exit-code taxonomy (assume 0/non-zero).
- Full formal JSON response schema (only examples shown).
- `claude setup-token` / OAuth-headless page did not fetch cleanly — **important for us** (subscription auth in the worker). Verify directly.
- Complete error taxonomy.

---

## 9. OFFICIAL SOURCE URLS (open these to verify)
1. CLI reference — https://code.claude.com/docs/en/cli-reference
2. Headless / non-interactive — https://code.claude.com/docs/en/headless
3. Permissions — https://code.claude.com/docs/en/permissions
4. Sessions — https://code.claude.com/docs/en/sessions
5. Memory (CLAUDE.md) — https://code.claude.com/docs/en/memory
6. MCP — https://code.claude.com/docs/en/mcp
7. Advanced setup — https://code.claude.com/docs/en/setup
8. Agent SDK overview — https://code.claude.com/docs/en/agent-sdk/overview
9. Agent SDK quickstart — https://code.claude.com/docs/en/agent-sdk/quickstart
10. Environment variables — https://code.claude.com/docs/en/env-vars
11. Sandboxing — https://code.claude.com/docs/en/sandboxing
