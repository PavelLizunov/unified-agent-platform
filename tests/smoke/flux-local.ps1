$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost

Write-Host "== flux deployments =="
Invoke-UapSsh -Target $server -Command "sudo k3s kubectl -n flux-system get deploy source-controller kustomize-controller helm-controller notification-controller; sudo k3s kubectl -n flux-system wait pod --for=condition=Ready --all --timeout=120s"

Write-Host "== sops age secret =="
Invoke-UapSsh -Target $server -Command "sudo k3s kubectl -n flux-system get secret sops-age -o name"
