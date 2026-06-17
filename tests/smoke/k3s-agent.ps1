$ErrorActionPreference = "Stop"

$knownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$sshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$knownHosts",
  "-o", "ConnectTimeout=10"
)

$server = "uap@192.168.0.201"

Write-Host "== k3s two-node readiness =="
$nodes = ssh @sshOptions $server "sudo k3s kubectl get nodes --no-headers"
if ($LASTEXITCODE -ne 0) {
  throw "Cannot read k3s nodes"
}
$nodesText = $nodes -join "`n"

if ($nodesText -notmatch "(?m)^uap-home-1\s+Ready\s+control-plane,etcd") {
  throw "uap-home-1 is not Ready as control-plane/etcd"
}

if ($nodesText -notmatch "(?m)^uap-home-2\s+Ready\s+<none>") {
  throw "uap-home-2 is not Ready as an agent node"
}

Write-Host "== schedule pod on uap-home-2 =="
$manifest = @'
apiVersion: v1
kind: Namespace
metadata:
  name: uap-smoke
---
apiVersion: v1
kind: Pod
metadata:
  name: pause-on-uap-home-2
  namespace: uap-smoke
  labels:
    app.kubernetes.io/name: uap-smoke-agent
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: uap-home-2
  tolerations:
    - operator: Exists
  containers:
    - name: pause
      image: registry.k8s.io/pause:3.10
      imagePullPolicy: IfNotPresent
'@

try {
  $manifest | ssh @sshOptions $server "sudo k3s kubectl apply -f -"
  if ($LASTEXITCODE -ne 0) {
    throw "Cannot apply uap-home-2 smoke pod"
  }

  ssh @sshOptions $server "sudo k3s kubectl -n uap-smoke wait --for=condition=Ready pod/pause-on-uap-home-2 --timeout=180s"
  if ($LASTEXITCODE -ne 0) {
    throw "uap-home-2 smoke pod did not become Ready"
  }

  $pod = ssh @sshOptions $server "sudo k3s kubectl -n uap-smoke get pod pause-on-uap-home-2 -o jsonpath='{.spec.nodeName} {.status.phase}'"
  if ($LASTEXITCODE -ne 0) {
    throw "Cannot read uap-home-2 smoke pod status"
  }

  if ($pod -ne "uap-home-2 Running") {
    throw "Expected pod on uap-home-2 Running, got: $pod"
  }

  Write-Host $pod
}
finally {
  ssh @sshOptions $server "sudo k3s kubectl delete pod -n uap-smoke pause-on-uap-home-2 --ignore-not-found >/dev/null"
  ssh @sshOptions $server "sudo k3s kubectl delete namespace uap-smoke --ignore-not-found --wait=true >/dev/null"
}
