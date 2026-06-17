$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost
$agent = Get-UapSshTarget -HostName $script:UapK3sAgentHost

Write-Host "== k3s node =="
Invoke-UapSsh -Target $server -Command "sudo k3s --version; sudo k3s kubectl get nodes -o wide; sudo k3s kubectl get pods -A -o wide"

if (-not [string]::IsNullOrWhiteSpace($script:UapK3sAgentHost)) {
  Write-Host "== tailnet API from $script:UapK3sAgentName =="
  Invoke-UapSsh -Target $agent -Command "timeout 5 bash -lc 'cat < /dev/null > /dev/tcp/$script:UapK3sServerTailnetIp/6443' && echo api-port-open"
}

Write-Host "== smoke deployment =="
Invoke-UapSsh -Target $server -Command "set -e; sudo k3s kubectl delete deployment uap-smoke --ignore-not-found >/dev/null; trap 'sudo k3s kubectl delete deployment uap-smoke --ignore-not-found >/dev/null' EXIT; sudo k3s kubectl create deployment uap-smoke --image=registry.k8s.io/pause:3.10 --replicas=1; sudo k3s kubectl rollout status deployment/uap-smoke --timeout=120s"
