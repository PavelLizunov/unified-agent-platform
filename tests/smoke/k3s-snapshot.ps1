$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost

Write-Host "== k3s etcd snapshots =="
Invoke-UapSsh -Target $server -Command "sudo k3s etcd-snapshot list | grep uap-local-"
