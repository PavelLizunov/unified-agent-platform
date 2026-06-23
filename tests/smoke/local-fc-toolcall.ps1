# Track A1 proof: the LOCAL function-calling brain on the RTX must emit STRUCTURED
# tool_calls (not text) over an OpenAI-compatible endpoint, at >=64k context.
#
# This is the hard requirement hermes-agent imposes on its brain (see
# docs/research/nousresearch-hermes-agent.md): a chat-only endpoint that drops
# tool_calls "fails silently". This test fails loudly instead.
#
# OPPORTUNISTIC: only runs on the GPU desktop (desktop-m922ij2) when it is on and a
# local server is serving. It is intentionally NOT part of tests/smoke/run-all.ps1
# (that targets the always-on cluster). See runbooks/local-fc-model.md.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\tests\smoke\local-fc-toolcall.ps1
#   ...\local-fc-toolcall.ps1 -StartOllama        # start `ollama serve` if it is down
#   $env:UAP_FC_BASEURL='http://127.0.0.1:11434'; $env:UAP_FC_MODEL='gpt-oss:20b'

[CmdletBinding()]
param(
  [string]$BaseUrl    = $(if ($env:UAP_FC_BASEURL) { $env:UAP_FC_BASEURL } else { "http://127.0.0.1:11434" }),
  [string]$Model      = $(if ($env:UAP_FC_MODEL)   { $env:UAP_FC_MODEL }   else { "gpt-oss:20b" }),
  [int]$MinContext    = 65536,
  [switch]$StartOllama
)
$ErrorActionPreference = "Stop"
# Imported only to satisfy the shared-smoke-config convention enforced by validate_iac.py.
# This is a localhost FC check (no SSH), so the SSH helpers it defines are intentionally unused.
. "$PSScriptRoot\uap-smoke-config.ps1"

function Test-FcUp { param($u) try { Invoke-RestMethod "$u/api/version" -TimeoutSec 3 | Out-Null; return $true } catch { return $false } }

# 1) endpoint reachable (optionally start Ollama with the required context)
if (-not (Test-FcUp $BaseUrl)) {
  if ($StartOllama) {
    Write-Host "== starting ollama serve (OLLAMA_CONTEXT_LENGTH=$MinContext) =="
    $env:OLLAMA_CONTEXT_LENGTH = "$MinContext"
    Start-Process -WindowStyle Hidden -FilePath ollama -ArgumentList 'serve'
    for ($i = 0; $i -lt 40 -and -not (Test-FcUp $BaseUrl); $i++) { Start-Sleep -Milliseconds 500 }
  }
  if (-not (Test-FcUp $BaseUrl)) {
    throw "FC endpoint $BaseUrl is not reachable. Is the GPU desktop on and serving? (try -StartOllama)"
  }
}

$chat = "$BaseUrl/v1/chat/completions"
$tool = @{ type = "function"; function = @{
    name = "get_weather"; description = "Get the current weather for a given city"
    parameters = @{ type = "object"; properties = @{ city = @{ type = "string"; description = "City name" } }; required = @("city") }
} }

# 2) POSITIVE: a tool MUST be emitted, structured (name + JSON arguments), not text
$reqPos = @{ model = $Model; stream = $false; tools = @($tool); messages = @(
    @{ role = "system"; content = "Use the provided tools when appropriate." }
    @{ role = "user";   content = "What is the current weather in Paris? Use the get_weather tool." }
) } | ConvertTo-Json -Depth 12
$pos = Invoke-RestMethod -Method Post -Uri $chat -ContentType "application/json" -Body $reqPos -TimeoutSec 300
$tc = $pos.choices[0].message.tool_calls
if (-not $tc) { throw "FAIL: no tool_calls; model answered as text => NOT function-calling: '$($pos.choices[0].message.content)'" }
$fn = $tc[0].function.name
if ($fn -ne "get_weather") { throw "FAIL: expected get_weather, got '$fn'" }
$toolArgs = $tc[0].function.arguments | ConvertFrom-Json
if (-not $toolArgs.city) { throw "FAIL: tool_call arguments missing 'city': $($tc[0].function.arguments)" }
Write-Host ("positive ok: {0}({1})  finish_reason={2}" -f $fn, $tc[0].function.arguments, $pos.choices[0].finish_reason)

# 3) NEGATIVE: a greeting must NOT spuriously trigger a tool (proves FC discrimination)
$reqNeg = @{ model = $Model; stream = $false; tools = @($tool); messages = @(
    @{ role = "user"; content = "Hi there, just say hello back." }
) } | ConvertTo-Json -Depth 12
$neg = Invoke-RestMethod -Method Post -Uri $chat -ContentType "application/json" -Body $reqNeg -TimeoutSec 120
if ($neg.choices[0].message.tool_calls) { throw "FAIL: a plain greeting produced a spurious tool_call" }
Write-Host ("negative ok: finish_reason={0}" -f $neg.choices[0].finish_reason)

# 4) CONTEXT: best-effort check that the served context meets hermes-agent's >=64k floor
try {
  $ps = (Invoke-RestMethod "$BaseUrl/api/ps").models | Where-Object { $_.name -eq $Model } | Select-Object -First 1
  if ($ps) {
    Write-Host ("loaded: context_length={0}  vram={1:N1}GB  gpu={2}%" -f $ps.context_length, ($ps.size_vram / 1GB), [math]::Round(100 * $ps.size_vram / $ps.size, 0))
    if ($ps.context_length -lt $MinContext) { Write-Warning "context_length $($ps.context_length) < $MinContext - hermes-agent rejects models below 64k at startup" }
  }
} catch { Write-Warning "could not read /api/ps for context check: $($_.Exception.Message)" }

Write-Host "local-fc-toolcall-ok"
