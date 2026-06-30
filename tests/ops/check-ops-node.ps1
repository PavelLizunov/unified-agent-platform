param(
  [string]$HostName = "192.168.0.203",
  [string]$User = "uap",
  [switch]$Require
)

$ErrorActionPreference = "Stop"

$target = "${User}@${HostName}"

$remoteCommand = @'
set -u
echo "hostname=$(hostname)"
for c in git ansible-playbook tofu kubectl flux sops age gh tailscale jq; do
  command -v "$c" >/dev/null || { echo "missing: $c"; exit 10; }
done
echo "ops-tools-ok"
'@

# Send the script base64-encoded: piping a string to a native command's stdin under PS 5.1 can prepend
# a UTF-8 BOM that lands on the first line ("set: command not found"). base64 transport is BOM-proof
# and ASCII-clean; ops-1 (Debian) has coreutils base64. Strip CR too: if git ever checks this file out
# as CRLF (core.autocrlf on Windows), the here-string bakes in "`r", which corrupts the remote bash
# parse ("set: -<CR>: invalid option") even though the file looks fine in an editor.
$remoteCommand = $remoteCommand -replace "`r", ""
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($remoteCommand))

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
  $output = ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new $target "echo $b64 | base64 -d | bash" 2>&1
  $exitCode = $LASTEXITCODE
}
finally {
  $ErrorActionPreference = $previousErrorActionPreference
}

if ($exitCode -eq 0) {
  $output | Write-Host
  Write-Host "ops-node-ok"
  exit 0
}

if ($Require) {
  $output | Write-Host
  throw "Ops node is not ready: $target"
}

Write-Host "ops-node-missing"
Write-Host "uap-ops-1 is not reachable or tools are not installed yet."
exit 0
