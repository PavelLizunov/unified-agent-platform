$ErrorActionPreference = "Stop"

$knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$sshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$knownHosts",
  "-o", "ConnectTimeout=10"
)

Write-Host "== flux deployments =="
ssh @sshOptions "uap@192.168.0.201" `
  "sudo k3s kubectl -n flux-system get deploy source-controller kustomize-controller helm-controller notification-controller; sudo k3s kubectl -n flux-system wait pod --for=condition=Ready --all --timeout=120s"

Write-Host "== sops age secret =="
ssh @sshOptions "uap@192.168.0.201" `
  "sudo k3s kubectl -n flux-system get secret sops-age -o name"
