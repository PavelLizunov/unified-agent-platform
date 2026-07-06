# One-click toggle for the local Qwen-35B brain (llama.cpp) on this desktop.
# Running -> stop it (free the GPU). Stopped -> start it. Hermes falls back to Ornith (Mac) while it is off.
# ASCII-only on purpose (Windows PowerShell 5.1 mangles non-ASCII in .ps1). Wired to a desktop shortcut.
$model  = "C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf"
$exeDir = "C:\Users\x3d_mutant\llama.cpp"
$sh = New-Object -ComObject WScript.Shell
$p  = Get-Process llama-server -ErrorAction SilentlyContinue
if ($p) {
    $p | Stop-Process -Force
    $sh.Popup("GPU freed (about 13 GB). Hermes falls back to Ornith on the Mac. Click me again to turn Qwen back on.", 4, "Qwen brain is now OFF", 64) | Out-Null
} else {
    Start-Process -FilePath (Join-Path $exeDir "llama-server.exe") -WorkingDirectory $exeDir -WindowStyle Minimized -ArgumentList @(
        "-m", $model, "--host", "0.0.0.0", "--port", "8080",
        "--no-mmap", "-ngl", "999", "--n-cpu-moe", "16", "-c", "65536", "--jinja", "-fa", "on")
    $sh.Popup("Loading (about 40-60s). Then Hermes uses qwen-35b again. Click me again to turn it off.", 4, "Qwen brain is now ON", 64) | Out-Null
}
