# Local LLM offload — save paid Claude/Codex tokens on big verifiable reads

Route token-heavy, **quote-verifiable** reads (big logs/docs/corpora) to the free local model so the big
input never enters a paid model's context. Design + measured rationale: `docs/model-eval/qwen-agentworld/`
(V2_REPORT.md, BFCL_RESULTS.md). Validated 2026-07-04 (quote-gate catches fabrication + injection; 3/3 live runs correct).

## Pieces
- `tools/offload/offload.py` — the CLI (stdlib only; extract + mechanical quote-verify + exit-code contract).
- `tools/offload/test_offload.py` — self-check of the quote-gate (no server needed): `python tools/offload/test_offload.py`.
- `tools/offload/serve-llm.ps1` — starts the llama.cpp server with the eval-validated config (128k, q4 KV, YaRN).
- `.claude/skills/uap-offload/SKILL.md` — the routing rule Claude Code reads to use it unprompted.

## Start / stop / health (workstation, GPU host)
```powershell
# start (or install as logon task):
powershell -ExecutionPolicy Bypass -File tools\offload\serve-llm.ps1
schtasks /create /tn offload-llm /sc onlogon /rl highest /tr "powershell -ExecutionPolicy Bypass -File C:\Users\x3d_mutant\reserch\unified-agent-platform\tools\offload\serve-llm.ps1"
schtasks /run /tn offload-llm          # start now
python tools\offload\offload.py health # -> "up" (exit 0) / "down" (exit 4)
Get-Process llama-server | Stop-Process -Force   # stop (free ~13-15 GB VRAM)
```

## Use
```bash
python tools/offload/offload.py extract -q "what caused the FATAL errors?" -q "what is max_connections?" big.log
```
Trust only `verified` claims. Exit 0 = all verified; 3 = some UNVERIFIED / no output (read those yourself,
retry at most once); 4 = down (read directly or start server); 5 = size (<40 KB read directly, >420 KB split).

## Notes / gotchas
- **Not always-on:** the desktop GPU host isn't always up, and has no sshd (can't be remote-started). Off = exit 4;
  callers fall back to reading directly — **never silent** (silent fallback ships the big input to paid anyway).
- **Proxy immunity:** `offload.py` disables proxies (`ProxyHandler({})`) — the hermes pod exports `HTTP_PROXY`
  (VLESS egress) and Python ignores the `NO_PROXY` CIDR, so without this the pod->desktop tailnet call dies.
- **hermes-agent path (deferred):** ConfigMap the same `offload.py` into the pod, `OFFLOAD_URL=http://100.114.172.40:8080/v1`.
- **Latency:** ~36 s thinking floor + ~68 s/128k prefill → a 100k-token job ~2.5-4 min. Prefer `run_in_background`.
- **Only `extract` (quote-verified) is trustworthy.** No `summarize`/synthesis verb — the model reasons-over-context
  at only ~60% @128k and that output can't be quote-verified. For big-corpus synthesis: map (local extract per 32k
  chunk) then reduce on paid over the few-KB of verified claims.
- **BFCL polluted the local hermes venv** with torch/transformers (from the eval). If the local hermes-agent is
  sensitive, move BFCL to its own venv; `offload.py` itself is stdlib-only and needs no such deps.
