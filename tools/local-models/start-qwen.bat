@echo off
REM Start Qwen-AgentWorld-35B (llama.cpp) on the desktop RTX 5060 Ti, bound to the tailnet so the
REM ops-1 router can reach it. Run this when you sit down to work; close the window to stop.
cd /d C:\Users\x3d_mutant\llama.cpp
start "qwen-35b-server" llama-server.exe -m C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf --host 0.0.0.0 --port 8080 --no-mmap -ngl 999 --n-cpu-moe 16 -c 65536 --jinja -fa on
echo Qwen-35B starting on http://0.0.0.0:8080 (loads ~30-60s). Router: http://100.82.241.121:8090/v1
