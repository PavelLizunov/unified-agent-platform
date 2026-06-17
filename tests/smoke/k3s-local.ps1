$ErrorActionPreference = "Stop"

$knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$sshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$knownHosts",
  "-o", "ConnectTimeout=10"
)

Write-Host "== k3s node =="
ssh @sshOptions "uap@192.168.0.201" `
  "sudo k3s --version; sudo k3s kubectl get nodes -o wide; sudo k3s kubectl get pods -A -o wide"

Write-Host "== tailnet API from uap-home-2 =="
ssh @sshOptions "uap@192.168.0.202" `
  "timeout 5 bash -lc 'cat < /dev/null > /dev/tcp/100.106.223.120/6443' && echo api-port-open"

Write-Host "== smoke deployment =="
ssh @sshOptions "uap@192.168.0.201" `
  "sudo k3s kubectl create deployment uap-smoke --image=registry.k8s.io/pause:3.10 --replicas=1; sudo k3s kubectl rollout status deployment/uap-smoke --timeout=120s; sudo k3s kubectl delete deployment uap-smoke"
