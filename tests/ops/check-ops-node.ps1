param(
  [string]$HostName = "192.168.0.203",
  [string]$User = "uap",
  [switch]$Require
)

$ErrorActionPreference = "Stop"

$target = "${User}@${HostName}"
$checkCommand = "hostname; for c in git ansible-playbook tofu kubectl flux sops age gh tailscale jq; do command -v `$c >/dev/null || exit 10; done; echo ops-tools-ok"

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
  $output = ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new $target $checkCommand 2>&1
  $exitCode = $LASTEXITCODE
}
finally {
  $ErrorActionPreference = $previousErrorActionPreference
}

if ($exitCode -eq 0) {
  $output | Write-Host
  Write-Host "ops-node-ok"
  exit 0
}

if ($Require) {
  $output | Write-Host
  throw "Ops node is not ready: $target"
}

Write-Host "ops-node-missing"
Write-Host "uap-ops-1 is not reachable or tools are not installed yet."
exit 0
