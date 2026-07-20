# Local-models router — local LLMs plus bounded Mac STT

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

## Voice STT route

Hermes safe-decodes accepted Telegram voice/audio to mono 16 kHz signed-16 PCM and sequentially posts 20-second
chunks of at most 640,000 bytes to `http://192.168.0.203:8090/v1/audio/transcriptions`. The ops router forwards only that exact path to the tailnet-only
Mac worker at `http://100.116.97.112:8091/v1/audio/transcriptions`. The response is normalized untrusted owner text;
it does not select a project/model or execute instructions. The normal voice-note ceiling is gone; a 15-minute,
8 MiB and 16,384-character emergency boundary remains. If the Mac or route is unavailable within eight seconds,
a recording that fits one chunk uses the checksum-pinned in-pod RNNT CPU model. Longer recordings fail before
opening `MissionStore` rather than tying up the pod CPU.

Pinned Mac artifacts:

| Artifact | Identity |
|---|---|
| CTC model | HF commit `075dff81f843cf23d22b4ce943ffdc4dd8650cd7`; 182,497,888 bytes; SHA-256 `35581e11e048eef785657cff07e5fced794bba6d9c75143257f6452c8aeea655` |
| Python wrapper | `transcribe_cpp-0.1.3-py3-none-any.whl`; SHA-256 `736f366beb8093eebd1a2ea694de48b6f87a34c6e5eb332384ba96fe3f4fceb3` |
| Metal native runtime | `transcribe-native-0.1.3-macos-arm64-metal.tar.gz`; SHA-256 `5cd8791846dec8a4e1c269cbe836b7c7d294e7d6c295209a1348e3bc5aae08c3` |

The runtime lives in `/Users/slovn/.uap-stt`; the checked-in launchd unit is
`tools/local-models/com.uap.local-stt.plist`. It binds the stable tailnet IP, verifies the model hash before load,
serializes inference, caps the accept queue at two and limits the process to 64 file descriptors. It never writes
audio or transcripts to disk or logs.

Health and restart checks:

```bash
# From ops-1
curl -fsS --max-time 3 http://100.116.97.112:8091/healthz
systemctl status local-model-router --no-pager

# On the Mac user session
launchctl print gui/501/com.uap.local-stt
launchctl kickstart -k gui/501/com.uap.local-stt
```

To update the worker, first run both offline selfchecks, copy `mac_stt_server.py` atomically into
`/Users/slovn/.uap-stt/`, validate/copy the plist into `~/Library/LaunchAgents/`, then kickstart launchd. Update the
ops router the same way: copy `route.py` as a temporary sibling, run `python3 route.py.new --selfcheck`, atomically
rename it and restart `local-model-router`. Do not place sample audio in the repository, journal or evidence; use an
explicit `/tmp` path and delete it immediately after the canary.

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
