@echo off
REM Stop the Qwen-35B server to free the GPU (~13 GB VRAM). Hermes keeps working while it's down —
REM it auto-falls-back to ornith-9b on the always-on Mac. Bring the qwen brain back with start-qwen.bat.
taskkill /F /IM llama-server.exe 2>nul && echo Qwen-35B stopped, GPU freed. || echo Qwen-35B was not running.
echo Hermes is now on the ornith-9b fallback (Mac). Run start-qwen.bat to restore the qwen brain.
