$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

foreach ($hostIp in $script:UapSmokeHosts) {
  Write-Host "== $hostIp =="
  $target = Get-UapSshTarget -HostName $hostIp
  Invoke-UapSsh -Target $target -Command "hostname; cat /etc/os-release | head -n 3; sudo -n true && echo sudo-ok; systemctl is-active qemu-guest-agent; sudo sshd -T | egrep 'passwordauthentication|permitrootlogin'"
}
