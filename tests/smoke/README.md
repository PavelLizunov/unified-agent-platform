# Smoke Tests

The smoke tests default to the current local topology:

- server: `uap@100.106.223.120`
- agent: `uap@100.94.228.67`

The defaults use tailnet IPs. LAN IPs can be used by overriding the variables below.

Override them with environment variables to test any compatible servers:

```powershell
$env:UAP_SSH_USER = "uap"
$env:UAP_K3S_SERVER_HOST = "100.x.y.z"
$env:UAP_K3S_SERVER_NAME = "uap-server-1"
$env:UAP_K3S_SERVER_TAILNET_IP = "100.x.y.z"
$env:UAP_K3S_AGENT_HOST = "100.x.y.a"
$env:UAP_K3S_AGENT_NAME = "uap-agent-1"
$env:UAP_SSH_HOSTS = "100.x.y.z,100.x.y.a"
```

Run all:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\run-all.ps1
```
