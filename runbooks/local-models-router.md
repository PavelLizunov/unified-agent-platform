# Local-models router — Qwen-35B + Ornith-9B in parallel, one endpoint

A fully-local LLM setup for when the paid Claude/Codex limits are exhausted. Two models run **in parallel
on two boxes**, each for its strength, behind one OpenAI-compatible endpoint on `uap-ops-1`.

| Model name | Backend | Host | Strength (soak-measured) |
|---|---|---|---|
| `qwen-35b` | llama.cpp `:8080` | desktop RTX 5060 Ti (`100.114.172.40`) | general / reasoning / **FC / retrieval** (V3: agentic 100%, FC 100%) |
| `ornith-9b` | mlx_lm.server `:8080` | Mac mini M4 (`100.116.97.112`) | **coding** (soak: 20/20 incl gcd), injection, FC-calls |

## Endpoint (use whichever your device can reach)

- **tailnet:** `http://100.82.241.121:8090/v1`
- **LAN:** `http://192.168.0.203:8090/v1`

OpenAI-compatible. Pick the model by name (`"model": "qwen-35b"` or `"ornith-9b"`). Native `tool_calls`
(function-calling) pass through untouched. No API key by default (tailnet/LAN-private); set `ROUTER_KEY`
in the systemd unit to require `Authorization: Bearer <key>`.

```bash
curl http://100.82.241.121:8090/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"ornith-9b","messages":[{"role":"user","content":"write a Rust gcd fn"}]}'
```

## The three pieces

**1. Router (ops-1)** — `tools/local-models/route.py`, a ~60-line stdlib reverse proxy. Runs as a
**systemd service** (`local-model-router`, boot-persistent). Routes by model name and rewrites the model id
to each backend's expected value (mlx_lm.server needs its exact repo id; llama.cpp ignores it).
```bash
ssh uap@100.82.241.121 'systemctl status local-model-router; journalctl -u local-model-router -n20'
sudo systemctl restart local-model-router          # after editing route.py / changing URLs
```

**2. Qwen-35B (desktop, NOT always-on)** — start it when you sit down to work:
double-click `tools/local-models/start-qwen.bat`, or:
```
C:\Users\x3d_mutant\llama.cpp\llama-server.exe -m C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf --host 0.0.0.0 --port 8080 --no-mmap -ngl 999 --n-cpu-moe 16 -c 65536 --jinja -fa on
```
Loads ~30-60s (18 GB GGUF, ~65 tok/s, 12.8 GB VRAM). When the desktop is off, `qwen-35b` calls error;
`ornith-9b` keeps working. (Making the desktop an always-on Linux box is a possible later step.)

**3. Ornith-9B (mac, always-on)** — served by `mlx_lm.server` in a `while true` auto-restart loop; restart
via ops-1 over tailnet:
```bash
ssh uap@100.82.241.121 'ssh slovn@100.116.97.112 "pgrep -f mlx_lm.server || nohup bash -c \"while true; do ~/mlxenv/bin/mlx_lm.server --model mlx-community/Ornith-1.0-9B-4bit --host 0.0.0.0 --port 8080 --prefill-step-size 512 --prompt-cache-size 1 --prompt-concurrency 1 --prompt-cache-bytes 3000000000 >> ~/mlxserver.log 2>&1; sleep 2; done\" >/dev/null 2>&1 &"'
```
The `--prompt-cache-size 1` + `--prompt-concurrency 1` flags are REQUIRED — without them mlx_lm.server
accumulates KV cache and OOM-crashes the 16 GB mac on big contexts (see `docs/model-eval/ornith-mac/`).

## Why this topology

The in-cluster LiteLLM **cannot** be used as the gateway: cluster pods don't route to tailnet `100.x` IPs
(pod-network gap), and `mlx_lm.server`/`llama.cpp` live on personal hardware outside GitOps. `uap-ops-1` is
always-on, on the tailnet, and reaches both boxes (verified 200/200) — so the router lives there. The
Windows desktop also can't host the router reliably (Windows↔mac tailnet rips long connections).

## Troubleshooting

- `qwen-35b` 502/error → desktop off or llama.cpp not started (run `start-qwen.bat`); check `curl http://100.114.172.40:8080/v1/models`.
- `ornith-9b` 502 or 401 → mac server down or wrong model id; check `curl http://100.116.97.112:8080/v1/models` (via ops-1).
- router down → `sudo systemctl restart local-model-router` on ops-1.
- FC missing → confirm you hit the router (not a raw backend) and the backend advertises tools; both pass `tool_calls` through.
