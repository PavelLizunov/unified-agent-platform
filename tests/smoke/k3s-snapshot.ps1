$ErrorActionPreference = "Stop"

$knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$sshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$knownHosts",
  "-o", "ConnectTimeout=10"
)

Write-Host "== k3s etcd snapshots =="
ssh @sshOptions "uap@192.168.0.201" `
  "sudo k3s etcd-snapshot list | grep uap-local-"
