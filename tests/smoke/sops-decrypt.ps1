$ErrorActionPreference = "Stop"

$knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$sshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$knownHosts",
  "-o", "ConnectTimeout=10"
)

$server = "uap@192.168.0.201"
$encryptedSecret = Resolve-Path ".\clusters\prod\infra\sops-smoke.sops.yaml"
$remoteSecret = "/tmp/uap-sops-smoke.sops.yaml"

Write-Host "== copy encrypted SOPS smoke secret =="
scp @sshOptions $encryptedSecret $server`:$remoteSecret
if ($LASTEXITCODE -ne 0) {
  throw "Cannot copy encrypted SOPS smoke secret"
}

try {
  Write-Host "== decrypt with node-local age key =="
  ssh @sshOptions $server "set -e; test -f /home/uap/.config/sops/age/keys.txt; SOPS_AGE_KEY_FILE=/home/uap/.config/sops/age/keys.txt sops -d $remoteSecret | grep -q not-a-real-secret; echo sops-decrypt-ok"
  if ($LASTEXITCODE -ne 0) {
    throw "SOPS decrypt smoke failed"
  }
}
finally {
  ssh @sshOptions $server "rm -f $remoteSecret"
}
