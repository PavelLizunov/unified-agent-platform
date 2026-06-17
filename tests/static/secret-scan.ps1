$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "== secret scan =="
python (Join-Path $PSScriptRoot "secret_scan.py") $repoRoot
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
