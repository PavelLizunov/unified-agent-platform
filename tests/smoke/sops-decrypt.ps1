$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost
$encryptedSecret = Resolve-Path ".\clusters\prod\infra\sops-smoke.sops.yaml"
$remoteSecret = "/tmp/uap-sops-smoke.sops.yaml"
$ownerSecret = Resolve-Path ".\clusters\prod\infra\hermes-agent-owner.sops.yaml"
$ownerVerifier = Resolve-Path ".\tools\hermes-mission\verify_owner_secret.py"
$remoteOwnerSecret = "/tmp/uap-hermes-agent-owner.sops.yaml"
$remoteOwnerVerifier = "/tmp/uap-verify-owner-secret.py"

Write-Host "== copy encrypted SOPS smoke secret =="
Invoke-UapScp -Source $encryptedSecret -Destination "$server`:$remoteSecret"
Invoke-UapScp -Source $ownerSecret -Destination "$server`:$remoteOwnerSecret"
Invoke-UapScp -Source $ownerVerifier -Destination "$server`:$remoteOwnerVerifier"

try {
  Write-Host "== decrypt with node-local age key =="
  Invoke-UapSsh -Target $server -Command "set -e; test -f $script:UapSopsAgeKeyFile; SOPS_AGE_KEY_FILE=$script:UapSopsAgeKeyFile sops -d $remoteSecret | grep -q not-a-real-secret; echo sops-decrypt-ok"
  Write-Host "== validate decrypted owner Secret =="
  Invoke-UapSsh -Target $server -Command "set -e; SOPS_AGE_KEY_FILE=$script:UapSopsAgeKeyFile sops -d --output-type json $remoteOwnerSecret | python3 $remoteOwnerVerifier; SOPS_AGE_KEY_FILE=$script:UapSopsAgeKeyFile sops -d $remoteOwnerSecret | sudo k3s kubectl apply --dry-run=client -f - >/dev/null; echo sops-owner-secret-kubernetes-ok"
}
finally {
  ssh @script:UapSshOptions $server "rm -f $remoteSecret $remoteOwnerSecret $remoteOwnerVerifier"
}
