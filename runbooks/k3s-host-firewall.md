# k3s Host Firewall

The tracked systemd unit blocks the k3s API (`6443/tcp`), kubelet (`10250/tcp`), and flannel VXLAN
(`8472/udp`) only when they arrive on the current LAN interface, `eth0`. Tailscale and pod-overlay traffic are
unchanged. The unit uses the host's existing `iptables-nft` backend and does not install another firewall manager.

## Supervised install on `uap-home-1`

Keep a working tailnet SSH session open. Copy the unit to `/tmp`, then arm a five-minute rollback before enabling it:

```bash
sudo systemd-run --unit=uap-firewall-rollback --on-active=5m \
  /bin/systemctl disable --now uap-k3s-lan-firewall.service
sudo install -m 0644 /tmp/uap-k3s-lan-firewall.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uap-k3s-lan-firewall.service
```

Verify from another node that LAN connections to `192.168.0.201:6443` and `:10250` fail while tailnet connections
to `100.106.223.120` succeed. Then verify both Kubernetes nodes, metrics, and workloads:

```bash
sudo k3s kubectl get nodes
sudo k3s kubectl top nodes
sudo k3s kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
sudo iptables -nvL UAP-LAN-INPUT
```

After all checks pass, cancel the rollback timer:

```bash
sudo systemctl stop uap-firewall-rollback.timer
sudo systemctl reset-failed uap-firewall-rollback.service
```

## Manual rollback

```bash
sudo systemctl disable --now uap-k3s-lan-firewall.service
```

This removes only the `UAP-LAN-INPUT` jump and chain. It does not alter Kubernetes or Tailscale-managed rules.
