param(
  [switch]$SkipSmoke,
  [switch]$SkipStatic,
  [switch]$IncludeTofuPlan,
  [switch]$IncludeAnsibleIdempotency,
  [switch]$IncludeReadiness,
  [switch]$IncludeOps,
  [switch]$Require,
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

  # -Require makes the opt-in ops/readiness checks AUTHORITATIVE: a missing dependency fails the gate
  # instead of silently exiting 0 (false-green). Without -Require they stay advisory (skip-friendly),
  # e.g. for a workstation where S3 creds live on ops-1 (s3-env-missing is then non-fatal, by design).
  # Pass the bare -Require flag only when set (a `-Require:$Require` value form breaks through -File).
  $reqArgs = @()
  if ($Require) { $reqArgs = @('-Require') }

  if ($IncludeReadiness) {
    if ([string]::IsNullOrWhiteSpace($GitUrl)) {
      Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 @reqArgs }
    }
    else {
      Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 -GitUrl $GitUrl @reqArgs }
    }
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\s3\check-s3-env.ps1 @reqArgs }
  }

  if ($IncludeOps) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\ops\check-ops-node.ps1 @reqArgs }
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\ops\check-ops-deploy-path.ps1 @reqArgs }
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\ops\check-pv-reclaim.ps1 @reqArgs }
  }

  if (-not $SkipSmoke) {
    Invoke-Checked { powershell -ExecutionPolicy Bypass -File .\tests\smoke\run-all.ps1 }
  }

  Write-Host "verify-local-ok"
}
finally {
  Pop-Location
}
