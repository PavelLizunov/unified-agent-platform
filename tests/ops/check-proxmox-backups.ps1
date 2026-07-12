param(
  [string]$OpsHost = "192.168.0.203",
  [string]$OpsUser = "uap",
  [string]$PveHost = "192.168.0.169",
  [int]$MaxAgeHours = 36,
  [switch]$Require
)

$ErrorActionPreference = "Stop"

if ($MaxAgeHours -lt 1) {
  throw "MaxAgeHours must be positive"
}

$inner = @"
set -euo pipefail
pvesm status --storage backup-pve2 | awk 'NR == 2 && `$3 == "active" { ok=1 } END { exit !ok }'
job=`$(pvesh get /cluster/backup/uap-critical-daily --output-format json)
printf '%s' "`$job" | grep -Eq '"enabled":[[:space:]]*1'
printf '%s' "`$job" | grep -Eq '"storage":[[:space:]]*"backup-pve2"'
printf '%s' "`$job" | grep -Eq '"vmid":[[:space:]]*"102,201,202,203"'
test -n "`$(find /mnt/pve/backup-pve2/dump -maxdepth 1 -type f -name 'vzdump-qemu-203-*.vma.zst' -mmin -$($MaxAgeHours * 60) -size +0c -print -quit)"
echo proxmox-backup-ok
"@

$inner = $inner -replace "`r", ""
$innerB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($inner))
$target = "${OpsUser}@${OpsHost}"
$throughOps = "echo $innerB64 | base64 -d | ssh -T -i ~/.ssh/uap_proxmox_admin -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes root@$PveHost bash -s"

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
  $output = ssh -T -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new $target $throughOps 2>&1
  $exitCode = $LASTEXITCODE
}
finally {
  $ErrorActionPreference = $previous
}

$output | Write-Host
if ($exitCode -eq 0 -and ($output -match "proxmox-backup-ok")) {
  exit 0
}

if ($Require) {
  throw "Proxmox backup verification failed through $target"
}

Write-Host "proxmox-backup-missing"
exit 0
