param(
  [string]$EnvironmentPath = ".\infra\tofu\environments\local-proxmox",
  [switch]$RunPlan
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$envPath = Resolve-Path (Join-Path $repoRoot $EnvironmentPath)
$tofu = Get-Command tofu -ErrorAction SilentlyContinue
$terraform = Get-Command terraform -ErrorAction SilentlyContinue

if ($tofu) {
  $cli = "tofu"
}
elseif ($terraform) {
  $cli = "terraform"
}
else {
  Write-Host "== tofu/terraform skipped: CLI not installed =="
  exit 0
}

Write-Host "== $cli fmt =="
& $cli fmt -check -recursive (Join-Path $repoRoot "infra\tofu")
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Push-Location $envPath
try {
  Write-Host "== $cli init -backend=false =="
  & $cli init -backend=false
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  Write-Host "== $cli validate =="
  & $cli validate
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  if ($RunPlan) {
    Write-Host "== $cli plan =="
    & $cli plan -out=tfplan
    if ($LASTEXITCODE -ne 0) {
      exit $LASTEXITCODE
    }
  }
  else {
    Write-Host "== $cli plan skipped: pass -RunPlan after local credentials are configured =="
  }
}
finally {
  Pop-Location
}
