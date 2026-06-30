param(
  [string]$HostName = "192.168.0.203",
  [string]$User = "uap",
  [string]$Namespace = "uap-system",
  [string]$Pvc = "hermes-agent-data",
  [switch]$Require
)

# Live-smoke (NOT CI): the hermes-agent-data PV is dynamically provisioned and its reclaimPolicy was
# patched to Retain by hand (see runbooks/hermes-agent-dr.md). That is LIVE state, not declarative, so
# a re-created PVC can silently regress to Delete. This check fails (under -Require) if the live PV
# bound to the PVC is not Retain. Read-only: it only runs kubectl get against the cluster via ops-1.

$ErrorActionPreference = "Stop"

$target = "${User}@${HostName}"

$remoteCommand = @'
set -u
export KUBECONFIG="$HOME/.kube/config"
command -v kubectl >/dev/null || { echo "kubectl missing on ops host"; exit 2; }
pv=$(kubectl -n __NS__ get pvc __PVC__ -o jsonpath='{.spec.volumeName}' 2>/dev/null || true)
if [ -z "$pv" ]; then echo "pvc __PVC__ not bound or cluster unreachable"; exit 2; fi
policy=$(kubectl get pv "$pv" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}' 2>/dev/null || true)
echo "pvc=__PVC__ pv=$pv reclaimPolicy=${policy:-<none>}"
if [ "$policy" != "Retain" ]; then
  echo "DRIFT: reclaimPolicy is '${policy:-<none>}', expected Retain (re-patch per runbooks/hermes-agent-dr.md)"
  exit 3
fi
echo "pv-reclaim-ok"
'@

$remoteCommand = $remoteCommand.Replace("__NS__", $Namespace)
$remoteCommand = $remoteCommand.Replace("__PVC__", $Pvc)

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

$output | Write-Host

if ($exitCode -eq 0) {
  exit 0
}

# exit 3 = cluster reachable AND the PV is NOT Retain: a CONFIRMED DR regression (the exact thing this
# guard exists to catch), not a "could not verify". Fail it ALWAYS, even without -Require.
if ($exitCode -eq 3) {
  throw "PV reclaim DRIFT for ${Namespace}/${Pvc}: reclaimPolicy is not Retain -- DR at risk; re-patch per runbooks/hermes-agent-dr.md."
}

# Otherwise (exit 2: cluster unreachable / PVC unbound) it is a genuine could-not-verify: skip unless
# -Require makes the opt-in ops gate authoritative.
if ($Require) {
  throw "PV reclaim check could not run for ${Namespace}/${Pvc} (exit ${exitCode}): cluster unreachable or PVC unbound."
}

Write-Host "pv-reclaim-not-verified"
exit 0
