$ErrorActionPreference = "Stop"

$hosts = @(
  "192.168.0.201",
  "192.168.0.202"
)

foreach ($hostIp in $hosts) {
  Write-Host "== $hostIp =="
  $knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile="$knownHosts" -o ConnectTimeout=10 "uap@$hostIp" `
    "hostname; cat /etc/os-release | head -n 3; sudo -n true && echo sudo-ok; systemctl is-active qemu-guest-agent; sudo sshd -T | egrep 'passwordauthentication|permitrootlogin'"
}
