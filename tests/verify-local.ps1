param(
  [switch]$SkipSmoke,
  [switch]$SkipStatic,
  [switch]$IncludeTofuPlan,
  [switch]$IncludeAnsibleIdempotency,
  [switch]$IncludeReadiness,
  [switch]$IncludeOps,
  [string]$GitUrl = "",
  [string]$Inventory = ".\infra\ansible\inventories\local.yml"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )

  & $Command
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}

try {
  Write-Host "== git whitespace check =="
  Invoke-Checked { git diff --check }

  if (-not $SkipStatic) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\static\secret-scan.ps1 }
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\static\validate-iac.ps1 }
  }

  if ($IncludeTofuPlan) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\tofu\validate-plan.ps1 }
  }

  if ($IncludeAnsibleIdempotency) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\ansible\idempotency-check.ps1 -Inventory $Inventory -ConfirmRun }
  }

  if ($IncludeReadiness) {
    if ([string]::IsNullOrWhiteSpace($GitUrl)) {
      Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 }
    }
    else {
      Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 -GitUrl $GitUrl }
    }
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\s3\check-s3-env.ps1 }
  }

  if ($IncludeOps) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\ops\check-ops-node.ps1 }
  }

  if (-not $SkipSmoke) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\smoke\run-all.ps1 }
  }

  Write-Host "verify-local-ok"
}
finally {
  Pop-Location
}
