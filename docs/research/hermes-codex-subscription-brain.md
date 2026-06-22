# hermes-agent + a ChatGPT/Codex SUBSCRIPTION as the brain (research addendum)

> Companion to `nousresearch-hermes-agent.md`. Researched 2026-06-22 over official Hermes docs, repo
> issues, OpenAI Codex docs, and community sources. Every load-bearing claim has a URL; CONFIRMED vs
> UNCERTAIN is flagged. **This corrects an earlier over-generalization:** "a subscription can't be the
> brain" was proven only for OUR Claude/subfleet endpoint — it does NOT hold for Codex.

## Bottom line
A **ChatGPT/Codex subscription CAN be hermes-agent's brain — officially, no API key** — via the
**`codex_app_server` runtime**. This is genuinely different from the Claude subscription (which cannot, in
Hermes today). The mechanism is NOT "the subscription exposes a function-calling HTTP endpoint." It works
because Hermes **hands the whole agent turn to the local Codex CLI** — which holds the ChatGPT-sub OAuth
(`~/.codex/auth.json`) and runs the **native tool loop itself** — while Hermes "becomes the shell," and
registers **itself as an MCP server** so Codex can call back into Hermes's tools.

## The two Codex "brain" modes (distinct)
- **`codex_app_server`** (`model.openai_runtime: codex_app_server`): Hermes spawns the Codex CLI as a
  subprocess over **JSON-RPC/stdio**; **Codex owns the tool loop**; subscription OAuth, **no API key**.
  Official: "run OpenAI agent turns against your ChatGPT subscription (no API key required) using the same
  auth flow Codex CLI uses." Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/codex-app-server-runtime
  Announced by Nous: "power your Hermes Agent with codex as the runtime… with the flip of a switch."
  Source: https://x.com/NousResearch/status/2054958564951912714 ; co-founder Teknium: "GPT-5.5 is now
  accessible in Hermes Agent through the ChatGPT/Codex OAuth provider." Source: https://x.com/Teknium/status/2047419336537846193
- **`codex_responses`** (Hermes owns the loop, calls OpenAI's Responses API with native `tool_calls`):
  needs the `api.responses.write` scope → a plain ChatGPT-sub OAuth token **401s "Missing scopes"** on
  `api.openai.com`; on a subscription it works only via an **unofficial Codex-impersonating proxy**
  (self-flagged bannable) or with a **pay-per-token API key**. Sources:
  https://github.com/NousResearch/hermes-agent/issues/5718 ;
  https://github.com/openclaw/openclaw/issues/38706 ;
  https://hermes-agent.nousresearch.com/docs/developer-guide/adding-providers/

## Why Codex works but Claude doesn't (the asymmetry)
- The **Codex CLI is a drivable agent app-server** (JSON-RPC/stdio) Hermes can wrap → inherits native
  tool-calling without an FC HTTP API.
- The **Claude CLI has no equivalent runtime in Hermes** — Anthropic is only a plain `anthropic_messages`
  provider (needs an API key) or the `claude -p` coding *skill*. An open feature request
  (https://github.com/NousResearch/hermes-agent/issues/25267) asks for a "Codex-style" Claude-subscription
  OAuth provider, explicitly noting Claude-subscribed users "effectively pay twice."
- Our **verified Claude proof still stands** (subfleet endpoint with a tools request → `finish_reason=stop`,
  `tool_calls=null`); it just doesn't generalize to Codex. The provider id for Codex is `openai-codex`
  (distinct from pay-per-token `openai-api`). Source: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md

## Brain vs coding-subprocess (BOTH exist for Codex)
- **Brain:** `openai-codex` provider + `codex_app_server` runtime = the subscription IS the brain.
- **Coding skill:** `skills/autonomous-ai-agents/codex/SKILL.md` runs `codex exec "…"` — a coding
  subprocess, the sibling of the `claude -p` Claude Code skill. Distinct from the brain. Source:
  https://github.com/NousResearch/hermes-agent/blob/main/skills/autonomous-ai-agents/codex/SKILL.md

## What this unlocks for us (architecture)
- **Brain = Codex/ChatGPT subscription** (official `codex_app_server`, native FC, no API key) — the cheapest
  brain that satisfies hermes-agent's hard FC requirement.
- **Coding = multi-engine skills:** Claude (`claude -p`, reuses our subfleet creds + egress) **and** Codex
  (`codex exec`) → split load across BOTH subscriptions = "don't hit limits."
- **Redundancy = a local FC model** (GPU + Mac) as the fallback brain → the owner's "two points of failure."
- **Phone = Telegram** gateway (outbound long-poll, NAT/RU-friendly).

## Caveats (honest)
- Codex CLI must reach OpenAI (`chatgpt.com/backend-api`) → from RU needs our egress proxy (same as Claude).
- Subscription-for-automation is a gray area (rate limits, possible ToS friction). The `codex_app_server`
  path runs the **real Codex CLI**, the lowest-risk subscription route; the impersonation-proxy
  (`codex_responses` on a sub token) is explicitly bannable. Same category as our existing Claude/subfleet usage.
- CONFIRMED via official docs + Nous/Teknium X posts + GitHub issues (#5718, #25267, #33075). Organic
  user testimony on brain-vs-subprocess is sparse (flagged). OpenAI documents the **API-key** path for
  "SDK integration / automation": https://developers.openai.com/codex/auth

## Key sources
- https://hermes-agent.nousresearch.com/docs/user-guide/features/codex-app-server-runtime
- https://hermes-agent.nousresearch.com/docs/integrations/providers
- https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop
- https://github.com/NousResearch/hermes-agent/issues/25267 (no Claude-sub OAuth provider yet)
- https://github.com/NousResearch/hermes-agent/issues/5718 (codex_responses api_mode)
- https://github.com/NousResearch/hermes-agent/issues/33075 (real user: openai-codex/gpt-5.5 as brain)
- https://github.com/openclaw/openclaw/issues/38706 (sub OAuth 401 "Missing scopes" on api.openai.com)
- https://developers.openai.com/codex/auth ; https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- https://x.com/NousResearch/status/2054958564951912714 ; https://x.com/Teknium/status/2047419336537846193
