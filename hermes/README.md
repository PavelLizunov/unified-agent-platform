# Hermes — the agent orchestrator (design + POC)

Hermes is UAP's **agent/orchestration layer**: it turns the plain chat backend (LiteLLM → subfleet →
Claude) into a tool-using agent. It is the "agent" in unified-**agent**-platform.

## Why prompt-based ReAct (not native function-calling)

subfleet's bridge spawns the bundled `claude` CLI, which is a **monolithic agentic loop that executes
tools itself** and does NOT surface `tool_use` to the caller. So native OpenAI `tools`/`tool_calls`
through the bridge is infeasible (verified: the bridge drops `tools`/`tool_choice`; the CLI is frozen
at 2.1.90 because newer = 403). Decision: **prompt-based ReAct at the Hermes layer, zero subfleet
change.** Hermes owns the tool registry, the loop, and tool execution. See memory
`uap-subfleet-integration`.

## How it works

1. Hermes serializes its tool registry into the **system prompt** with a rigid grammar:
   to call a tool the model must emit ONLY a fenced block and nothing else:
   ````
   ```tool_call
   {"name":"calc","arguments":{"expression":"2*(3+4)"}}
   ```
   ````
2. Hermes calls LiteLLM (`smart-cloud` etc.) as a normal `chat.completions` request.
3. It parses the assistant text for a `tool_call` block.
   - none  → that text is the final answer (the model stopped naturally).
   - found → Hermes executes the tool out-of-band, appends the assistant turn + a `user` turn carrying
     a ```tool_result``` block, and re-calls. Loop until no tool_call or a max-steps guard.

This rides only on capabilities the bridge already has (faithful system-prompt + multi-turn + streamed
text), so it works against the live stack today.

## POC

`poc/react_poc.py` (stdlib only) is a working ReAct loop with a `calc` tool, run against the live
LiteLLM endpoint. Run:

```bash
export LITELLM_BASE="https://uap-home-1.tail9fd337.ts.net/v1"
export LITELLM_KEY="$(kubectl -n uap-system get secret litellm-keys -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d)"
python3 poc/react_poc.py "What is 48271 * 99173 + 9999999 - 12345? Then say if it is even or odd."
```

## Production TODO (not built yet)

- **Deployment**: Hermes as an in-cluster service (its own Deployment) calling LiteLLM by ClusterIP,
  exposed on the tailnet like LiteLLM.
- **Tool registry + sandbox**: real tools (HTTP, k8s read, retrieval) with a hardened executor — the
  POC's `calc` uses a charset-restricted `eval`, which is NOT production-safe.
- **Grammar robustness**: strict fenced-block extraction, JSON-repair/retry, unknown-tool handling.
- **Known limits**: an extra round-trip per tool hop (latency); tool_result arrives as ordinary user
  text → treat it as **untrusted** (prompt-injection surface); no real parallel tool calls; the full
  tool schema rides in every request's system prompt (token cost — keep it prompt-cache friendly).
