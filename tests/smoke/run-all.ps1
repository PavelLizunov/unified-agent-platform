$ErrorActionPreference = "Stop"

$smokeDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$scripts = @(
  "ssh-baseline.ps1",
  "k3s-local.ps1",
  "k3s-agent.ps1",
  "flux-local.ps1",
  "k3s-snapshot.ps1",
  "sops-decrypt.ps1"
)

foreach ($script in $scripts) {
  Write-Host "## $script"
  & (Join-Path $smokeDir $script)
}
