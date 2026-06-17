param(
  [string]$Inventory = ".\infra\ansible\inventories\local.yml",
  [string]$Playbook = ".\infra\ansible\playbooks\site.yml",
  [switch]$ConfirmRun
)

$ErrorActionPreference = "Stop"

if (-not $ConfirmRun) {
  Write-Host "This check runs Ansible against real hosts. Re-run with -ConfirmRun to proceed."
  exit 0
}

$ansiblePlaybook = Get-Command ansible-playbook -ErrorAction SilentlyContinue
if (-not $ansiblePlaybook) {
  Write-Host "== ansible idempotency skipped: ansible-playbook not installed =="
  exit 0
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$inventoryPath = Resolve-Path (Join-Path $repoRoot $Inventory)
$playbookPath = Resolve-Path (Join-Path $repoRoot $Playbook)
$secondRunLog = Join-Path $env:TEMP "uap-ansible-idempotency-second-run.log"

Push-Location $repoRoot
try {
  Write-Host "== ansible idempotency first run =="
  ansible-playbook -i $inventoryPath $playbookPath
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  Write-Host "== ansible idempotency second run =="
  ansible-playbook -i $inventoryPath $playbookPath | Tee-Object -FilePath $secondRunLog
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  $changedMatches = Select-String -Path $secondRunLog -Pattern "changed=(\d+)"
  $changedTotal = 0
  foreach ($match in $changedMatches) {
    $changedTotal += [int]$match.Matches[0].Groups[1].Value
  }

  if ($changedTotal -ne 0) {
    throw "Ansible second run changed $changedTotal tasks; expected 0 for idempotency."
  }

  Write-Host "ansible-idempotency-ok"
}
finally {
  Pop-Location
}
