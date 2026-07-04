# Overnight tuner launcher. Restarts the harness if the process itself dies.
# Stop condition: DONE marker written by tune.py, or max restarts.
# Results are append-only + fsync'd, so a restart resumes with zero data loss.
$ErrorActionPreference = "SilentlyContinue"
$dir    = "C:\Users\X3D_MU~1\AppData\Local\Temp\claude\C--Users-x3d-mutant-reserch-unified-agent-platform\f2728c9f-a27f-4265-862c-7d20a6e5f660\scratchpad\overnight"
$py     = "C:\Users\x3d_mutant\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$done   = Join-Path $dir "DONE"
$wraplog= Join-Path $dir "wrapper.log"
$maxRestarts = 40

Remove-Item $done -ErrorAction SilentlyContinue
"$(Get-Date -Format o)  wrapper start" | Out-File $wraplog -Append -Encoding utf8

for ($i=0; $i -lt $maxRestarts; $i++) {
    if (Test-Path $done) { "$(Get-Date -Format o)  DONE marker present -> stop" | Out-File $wraplog -Append -Encoding utf8; break }
    # kill any stray server from a hard-killed previous run
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    "$(Get-Date -Format o)  launch attempt $i" | Out-File $wraplog -Append -Encoding utf8
    & $py (Join-Path $dir "tune.py")
    $rc = $LASTEXITCODE
    "$(Get-Date -Format o)  harness exited rc=$rc" | Out-File $wraplog -Append -Encoding utf8
    if (Test-Path $done) { "$(Get-Date -Format o)  completed cleanly" | Out-File $wraplog -Append -Encoding utf8; break }
    Start-Sleep -Seconds 5   # brief backoff before resume
}
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
"$(Get-Date -Format o)  wrapper end" | Out-File $wraplog -Append -Encoding utf8
