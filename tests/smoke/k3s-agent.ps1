$ErrorActionPreference = "Stop"
. "$PSScriptRoot\uap-smoke-config.ps1"

$server = Get-UapSshTarget -HostName $script:UapK3sServerHost
$podName = "pause-on-$($script:UapK3sAgentName)"
$serverNameRegex = [regex]::Escape($script:UapK3sServerName)
$agentNameRegex = [regex]::Escape($script:UapK3sAgentName)

Write-Host "== k3s two-node readiness =="
$nodes = ssh @script:UapSshOptions $server "sudo k3s kubectl get nodes --no-headers"
if ($LASTEXITCODE -ne 0) {
  throw "Cannot read k3s nodes"
}
$nodesText = $nodes -join "`n"

if ($nodesText -notmatch "(?m)^$serverNameRegex\s+Ready\s+control-plane,etcd") {
  throw "$script:UapK3sServerName is not Ready as control-plane/etcd"
}

if ($nodesText -notmatch "(?m)^$agentNameRegex\s+Ready\s+<none>") {
  throw "$script:UapK3sAgentName is not Ready as an agent node"
}

Write-Host "== schedule pod on $script:UapK3sAgentName =="
$manifest = @"
apiVersion: v1
kind: Namespace
metadata:
  name: uap-smoke
---
apiVersion: v1
kind: Pod
metadata:
  name: $podName
  namespace: uap-smoke
  labels:
    app.kubernetes.io/name: uap-smoke-agent
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: $($script:UapK3sAgentName)
  tolerations:
    - operator: Exists
  containers:
    - name: pause
      image: registry.k8s.io/pause:3.10
      imagePullPolicy: IfNotPresent
"@

try {
  $manifest | ssh @script:UapSshOptions $server "sudo k3s kubectl apply -f -"
  if ($LASTEXITCODE -ne 0) {
    throw "Cannot apply $script:UapK3sAgentName smoke pod"
  }

  ssh @script:UapSshOptions $server "sudo k3s kubectl -n uap-smoke wait --for=condition=Ready pod/$podName --timeout=180s"
  if ($LASTEXITCODE -ne 0) {
    throw "$script:UapK3sAgentName smoke pod did not become Ready"
  }

  $pod = ssh @script:UapSshOptions $server "sudo k3s kubectl -n uap-smoke get pod $podName -o jsonpath='{.spec.nodeName} {.status.phase}'"
  if ($LASTEXITCODE -ne 0) {
    throw "Cannot read $script:UapK3sAgentName smoke pod status"
  }

  if ($pod -ne "$script:UapK3sAgentName Running") {
    throw "Expected pod on $script:UapK3sAgentName Running, got: $pod"
  }

  Write-Host $pod
}
finally {
  ssh @script:UapSshOptions $server "sudo k3s kubectl delete pod -n uap-smoke $podName --ignore-not-found >/dev/null"
  ssh @script:UapSshOptions $server "sudo k3s kubectl delete namespace uap-smoke --ignore-not-found --wait=true >/dev/null"
}
