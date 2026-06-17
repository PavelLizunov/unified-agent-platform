# k3s Server Node Runbook

## Scope

Use this runbook only when adding a new Linux server node that should participate in embedded etcd.

Do not use this to turn `uap-home-2` into a second server by itself. A 2-member etcd cluster does not provide
HA, because losing either member loses quorum. Add the next server only when the third independent failure domain
is ready.

## Preconditions

- Existing server: `uap-home-1`, `100.106.223.120`.
- New server has Debian 12 or newer.
- New server has a stable tailnet IP.
- Tailscale is online before k3s starts.
- TCP `6443` from the new server to an existing server works over tailnet.
- TCP `2379-2380` between all server nodes works over tailnet.
- The new node is in an independent failure domain if it is meant to improve HA.

## Config Template

Replace placeholders before use:

```yaml
server: https://100.106.223.120:6443
token-file: /etc/rancher/k3s/token
node-name: <node-name>
node-ip: <tailnet-ip>
advertise-address: <tailnet-ip>
flannel-iface: tailscale0
tls-san:
  - <tailnet-ip>
  - <node-name>.tail9fd337.ts.net
disable:
  - traefik
  - servicelb
secrets-encryption: true
write-kubeconfig-mode: "0644"
etcd-snapshot-retention: 7
```

Copy the server token from `/var/lib/rancher/k3s/server/node-token` on an existing server into
`/etc/rancher/k3s/token` on the new server.

Do not print, commit, or save the token in this repository.

## Install

Install the same k3s version as the existing server:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION='v1.35.5+k3s1' INSTALL_K3S_EXEC='server --config /etc/rancher/k3s/config.yaml' sh -
sudo systemctl enable --now k3s
```

## Verify

```powershell
ssh uap@192.168.0.201 "sudo k3s kubectl get nodes -o wide"
ssh uap@192.168.0.201 "sudo k3s kubectl -n kube-system get pods -o wide"
ssh uap@192.168.0.201 "sudo k3s etcd-snapshot save --name post-server-join-$(date -u +%Y%m%dT%H%M%SZ)"
```

Expected:

- All server nodes are `Ready`.
- etcd pods/members are healthy.
- A fresh etcd snapshot can be created after the join.

After three server nodes exist, add an API endpoint strategy before depending on HA operationally:

- Tailscale DNS name or stable LB address for clients.
- Health-checked TCP `6443` balancer if clients should survive the loss of the first server address.
