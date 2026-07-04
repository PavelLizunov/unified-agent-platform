# serve-llm.ps1 - start the local offload LLM (llama.cpp) with the eval-validated config. ASCII only (PS 5.1).
# Bind localhost + tailnet so Claude Code (local) and hermes-agent (tailnet) both reach it.
# Install as logon task:  schtasks /create /tn offload-llm /sc onlogon /rl highest /tr "powershell -ExecutionPolicy Bypass -File C:\path\to\serve-llm.ps1"
# Run now: schtasks /run /tn offload-llm   |   Stop: Get-Process llama-server | Stop-Process -Force
$ErrorActionPreference = "SilentlyContinue"
$model = "C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf"
$exe   = "C:\Users\x3d_mutant\llama.cpp\llama-server.exe"
$log   = "$env:LOCALAPPDATA\offload-llm.log"
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$a = @("-m", $model, "--host", "0.0.0.0", "--port", "8080",
       "-ngl", "999", "--n-cpu-moe", "20", "-c", "131072",
       "--jinja", "--no-mmap", "-fa", "on",
       "--rope-scaling", "yarn", "--yarn-orig-ctx", "32768",
       "-ctk", "q4_0", "-ctv", "q4_0", "--no-webui")
Start-Process -FilePath $exe -ArgumentList $a -WindowStyle Hidden -RedirectStandardError $log
Write-Output "offload-llm starting on :8080 (128k q4 yarn). log=$log"
# Note: bind 0.0.0.0 exposes on all interfaces. If desired, scope to Tailscale + loopback with a firewall rule:
#   New-NetFirewallRule -DisplayName "offload-llm tailnet" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow -InterfaceAlias "Tailscale"
