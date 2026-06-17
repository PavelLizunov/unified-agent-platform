$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost
$encryptedSecret = Resolve-Path ".\clusters\prod\infra\sops-smoke.sops.yaml"
$remoteSecret = "/tmp/uap-sops-smoke.sops.yaml"

Write-Host "== copy encrypted SOPS smoke secret =="
Invoke-UapScp -Source $encryptedSecret -Destination "$server`:$remoteSecret"

try {
  Write-Host "== decrypt with node-local age key =="
  Invoke-UapSsh -Target $server -Command "set -e; test -f $script:UapSopsAgeKeyFile; SOPS_AGE_KEY_FILE=$script:UapSopsAgeKeyFile sops -d $remoteSecret | grep -q not-a-real-secret; echo sops-decrypt-ok"
}
finally {
  ssh @script:UapSshOptions $server "rm -f $remoteSecret"
}
