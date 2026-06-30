param(
  [string]$HostName = "192.168.0.203",
  [string]$User = "uap",
  [string]$ServerHostName = "100.106.223.120",
  [string]$AgentHostName = "100.94.228.67",
  [switch]$Require
)

$ErrorActionPreference = "Stop"

$target = "${User}@${HostName}"

$remoteCommand = @'
set -eu

echo "ops-host=$(hostname)"

command -v kubectl >/dev/null
command -v ssh >/dev/null
test -s "$HOME/.kube/config"
test "$(stat -c "%a" "$HOME/.kube/config")" = "600"

export KUBECONFIG="$HOME/.kube/config"
kubectl get nodes -o name | grep -q '^node/uap-home-1$'
kubectl get nodes -o name | grep -q '^node/uap-home-2$'
kubectl -n flux-system get deploy source-controller kustomize-controller helm-controller notification-controller >/dev/null

ssh -n -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new __USER__@__SERVER_HOST__ hostname >/dev/null
ssh -n -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new __USER__@__AGENT_HOST__ hostname >/dev/null

echo "ops-deploy-path-ok"
'@

$remoteCommand = $remoteCommand.Replace("__USER__", $User)
$remoteCommand = $remoteCommand.Replace("__SERVER_HOST__", $ServerHostName)
$remoteCommand = $remoteCommand.Replace("__AGENT_HOST__", $AgentHostName)

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
  exit 0
}

if ($Require) {
  $output | Write-Host
  throw "Ops deploy path is not ready: $target"
}

Write-Host "ops-deploy-path-missing"
Write-Host "uap-ops-1 cannot manage the cluster yet."
exit 0
