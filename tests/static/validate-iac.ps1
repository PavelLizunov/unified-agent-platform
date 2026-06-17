$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "== static IaC checks =="
python (Join-Path $PSScriptRoot "validate_iac.py") $repoRoot
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$tofu = Get-Command tofu -ErrorAction SilentlyContinue
$terraform = Get-Command terraform -ErrorAction SilentlyContinue

if ($tofu) {
  Write-Host "== tofu fmt =="
  tofu fmt -check -recursive (Join-Path $repoRoot "infra\tofu")
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
elseif ($terraform) {
  Write-Host "== terraform fmt =="
  terraform fmt -check -recursive (Join-Path $repoRoot "infra\tofu")
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
else {
  Write-Host "== tofu/terraform skipped: CLI not installed =="
}

$ansiblePlaybook = Get-Command ansible-playbook -ErrorAction SilentlyContinue
$ansibleInventory = Get-Command ansible-inventory -ErrorAction SilentlyContinue

if ($ansibleInventory) {
  Write-Host "== ansible inventory graph =="
  ansible-inventory -i (Join-Path $repoRoot "infra\ansible\inventories\local.yml") --graph
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
else {
  Write-Host "== ansible-inventory skipped: CLI not installed =="
}

if ($ansiblePlaybook) {
  Write-Host "== ansible syntax check =="
  ansible-playbook -i (Join-Path $repoRoot "infra\ansible\inventories\local.yml") --syntax-check (Join-Path $repoRoot "infra\ansible\playbooks\site.yml")
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
else {
  Write-Host "== ansible-playbook skipped: CLI not installed =="
}
