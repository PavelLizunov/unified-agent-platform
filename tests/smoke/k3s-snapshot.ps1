$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost

Write-Host "== k3s etcd snapshots =="
# k3s 1.35 reports server-only config keys as warnings for this subcommand.
# Keep the command/grep exit status authoritative without making stderr fatal to Windows PowerShell.
Invoke-UapSsh -Target $server -Command "sudo k3s etcd-snapshot list 2>/dev/null | grep uap-local-"
