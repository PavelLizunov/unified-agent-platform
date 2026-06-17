# k3s Agent Join Runbook

## Scope

Use this runbook for Linux worker nodes that should run workloads but must not participate in embedded etcd.
This is the correct role for local overflow nodes and any future non-quorum worker.

Current example:

- Agent node: `uap-home-2`
- Server API: `https://100.106.223.120:6443`
- Agent tailnet IP: `100.94.228.67`
- Config template: `infra/k3s/uap-home-2.agent.config.yaml`
- Ansible template: `infra/ansible/templates/k3s-agent.config.yaml.j2`
- Local inventory group: `infra/ansible/inventories/local.yml` → `k3s_agents`

## Preconditions

- Debian 12 or newer.
- Tailscale is installed and authenticated.
- SSH password auth is disabled.
- User `uap` has passwordless sudo.
- TCP `6443` from the agent to the server works over tailnet.

Verify API reachability from the agent:

```powershell
ssh uap@192.168.0.202 "timeout 5 bash -lc 'cat < /dev/null > /dev/tcp/100.106.223.120/6443' && echo api-port-open"
```

## Install

Preferred repeatable path:

```powershell
ansible-playbook -i .\infra\ansible\inventories\local.yml .\infra\ansible\playbooks\31-k3s-agent.yml
```

Manual fallback:

Get the server version:

```powershell
ssh uap@192.168.0.201 "sudo k3s --version | head -n 1"
```

Create `/etc/rancher/k3s/config.yaml` on the agent:

```yaml
server: https://100.106.223.120:6443
token-file: /etc/rancher/k3s/token
node-name: uap-home-2
node-ip: 100.94.228.67
flannel-iface: tailscale0
```

Copy the node token from the server into `/etc/rancher/k3s/token` on the agent.

Do not print, commit, or save the token in this repository.

Install the same k3s version as the server:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION='v1.35.5+k3s1' INSTALL_K3S_EXEC='agent --config /etc/rancher/k3s/config.yaml' sh -
sudo systemctl enable --now k3s-agent
```

If GitHub downloads are slow, copy `/usr/local/bin/k3s` from an existing node first and run the installer with:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_DOWNLOAD=true INSTALL_K3S_EXEC='agent --config /etc/rancher/k3s/config.yaml' sh -
```

## Verify

```powershell
ssh uap@192.168.0.201 "sudo k3s kubectl get nodes -o wide"
powershell -ExecutionPolicy Bypass -File .\tests\smoke\k3s-agent.ps1
```

Expected:

- `uap-home-1` is `Ready` with `control-plane,etcd`.
- `uap-home-2` is `Ready` with role `<none>`.
- The smoke pod schedules on `uap-home-2` and reaches `Running`.
