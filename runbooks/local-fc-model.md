# Local Function-Calling Brain on the RTX (Track A1)

> Stand up and verify a **local, native-function-calling** model on the RTX 5060 Ti so it can serve as
> hermes-agent's brain with **no cloud egress**. This is **Phase A1** of [docs/next-steps.md](../docs/next-steps.md).
> The decisive constraint (from [docs/research/nousresearch-hermes-agent.md](../docs/research/nousresearch-hermes-agent.md)):
> hermes-agent **requires a native OpenAI `tool_calls` field** and has **no prompt-based fallback** — a chat-only
> endpoint (our subfleet/Claude path) "fails silently". The brain must therefore emit **structured `tool_calls`**
> at **>= 64k context** (hermes-agent rejects smaller at startup).
>
> **Status: PROVEN 2026-06-23** via **Ollama + `gpt-oss:20b`** on `desktop-m922ij2`. Last reviewed: 2026-06-23.

## Host & hardware

| Fact | Value |
|---|---|
| Host | `desktop-m922ij2` (Windows 11), tailnet `100.114.172.40` |
| GPU | NVIDIA RTX 5060 Ti **16 GB**, Blackwell (sm_120), driver 610.62 / CUDA 13.3 |
| Always-on? | **No** — so this brain is **opportunistic**; the durable brain is Codex (Phase A5) |
| Server | Ollama **0.16.1** (already installed; native Windows, bundles its own CUDA runtime) |

## The proven stack (Ollama, native Windows)

Chosen over a fresh Hermes/Qwen pull because `gpt-oss:20b` is **already on disk** (no model download over the
RU-restricted network), is **FC-native** (agentic-tuned, 128k-capable), fits 16 GB, and matches hermes-agent's
`tool_use_enforcement: "auto"` (the `gpt` substring). The `--tool-call-parser hermes` (vLLM) / `--jinja` (llama.cpp)
flags are the *equivalents* for Hermes/Qwen GGUFs — see Alternatives.

### 1. Start the server with >= 64k context

```powershell
$env:OLLAMA_CONTEXT_LENGTH = 65536      # hermes-agent floor; Ollama default is far lower
$env:OLLAMA_KEEP_ALIVE     = "30m"      # keep the brain warm between turns (or -1 = forever)
Start-Process -WindowStyle Hidden -FilePath ollama -ArgumentList 'serve'
# readiness:
(Invoke-RestMethod http://127.0.0.1:11434/api/version).version
```

> The Ollama Windows app normally autostarts a server on login; if so, it must be started **with**
> `OLLAMA_CONTEXT_LENGTH` set (a system env var, or launched as above) or it will serve the small default
> context and hermes-agent will reject the model.

### 2. Model

```powershell
ollama list                 # gpt-oss:20b (~13 GB) already pulled
# (to fetch fresh, if ever wiped:)  ollama pull gpt-oss:20b
```

### 3. Prove function-calling (the A1 "Done" gate)

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\local-fc-toolcall.ps1 -StartOllama
```

Expected tail:

```
positive ok: get_weather({"city":"Paris"})  finish_reason=tool_calls
negative ok: finish_reason=stop
loaded: context_length=65536  vram=14.7GB  gpu=100%
local-fc-toolcall-ok
```

What it asserts (the full hermes-agent loop shape):
- **positive** — a tool prompt yields a **structured** `tool_calls` object (name + JSON args), `finish_reason=tool_calls`;
- **round-trip** (verified manually 2026-06-23) — feeding the tool result back yields a correct final answer, `finish_reason=stop`;
- **negative** — a bare greeting yields **no** tool call (genuine FC discrimination, not spurious calls);
- **context** — the loaded model serves `context_length=65536` (>= 64k).

## VRAM & context budget (16 GB card)

| Item | Cost |
|---|---|
| `gpt-oss:20b` weights (MXFP4) + 64k KV cache | **~14.7 GB VRAM, 100% GPU** (measured via `/api/ps`) |
| Headroom | ~1.5 GB — tight but stable; do not also run a second large model |

If a future model + 64k KV overflows 16 GB: quantize the KV cache, drop to a 7-8B FC model, or lower context
(but not below 64k, or hermes-agent rejects it).

## Wiring hermes-agent to this brain (Phase A2 — not yet done)

A1 proves the **endpoint emits what hermes-agent needs**. Running hermes-agent against it is A2. When you do:

1. **Bind Ollama to the tailnet**, not just loopback, so the always-on Linux node can reach it:
   `OLLAMA_HOST=0.0.0.0:11434` (or the tailnet IP). The desktop has no inbound sshd, but Ollama's port is fine over tailnet.
2. In `~/.hermes/config.yaml` point the brain at it:
   ```yaml
   model:
     provider: custom
     base_url: "http://100.114.172.40:11434/v1"   # desktop-m922ij2 over tailnet
     model: "gpt-oss:20b"
   agent:
     tool_use_enforcement: "auto"                  # matches "gpt"
   ```
3. hermes-agent's SSRF guard **blocks CGNAT `100.64.0.0/10`** (tailnet) by default — set
   `security.allow_private_urls: true` or it will refuse the LAN/tailnet model. (Source: research doc / Hermes security page.)
4. Because the desktop is **not always-on**, treat this as the **fallback** brain; primary is Codex `codex_app_server` (A5).

## Alternatives (documented, not the proven path)

- **llama.cpp `--jinja`** — already on this box (`C:\Users\x3d_mutant\suflyor-local-ai\llama-new\b9626\`, plus a
  `llama-server.exe`). `--jinja` makes the server apply the model's chat template, which parses a Hermes/Qwen GGUF's
  output back into OpenAI `tool_calls`. Use with a clean **Qwen2.5/Qwen3 or Hermes** GGUF (the on-disk
  `Qwopus3.5-9B-coder` merge has an unverified tool template). Command shape:
  `llama-server -m <qwen>.gguf --jinja -c 65536 --host 0.0.0.0 --port 8080`. Needs a recent CUDA build for Blackwell sm_120 (b9626 qualifies).
- **vLLM in WSL2** — the canonical server for `--enable-auto-tool-choice --tool-call-parser hermes`, best for a
  dedicated FC server. **Heaviest path here:** WSL2 is **not installed** (needs `wsl --install` + reboot + a CUDA 12.8/13
  cu128 PyTorch + an AWQ/GPTQ model to fit 16 GB). Defer unless this box becomes a dedicated model server.

## Caveats (honest)

- **Opportunistic only** — the desktop is not 24/7; do not make this the sole brain. Codex is the durable one.
- **A1 != A2** — this proves the endpoint contract; it does **not** yet prove hermes-agent starts and runs against it.
- **gpt-oss is a reasoning model** — it emits a hidden reasoning channel; Ollama parses tool calls out correctly, but
  it is chosen here for *FC proof + fallback*, not as the best agentic planner (that is Codex/GPT-5.5).
- If the Ollama server is started by the autostart app **without** `OLLAMA_CONTEXT_LENGTH`, the served context drops
  to the default and hermes-agent will reject the model — always verify with `/api/ps` (`context_length`).
