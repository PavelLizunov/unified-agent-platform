# LiteLLM tailnet exposure (host `tailscale serve` on uap-home-1)

LiteLLM (`:4000`, ns `uap-system`) is reached from tailnet devices (laptop/phone) at:

```
https://uap-home-1.tail9fd337.ts.net/        ->  litellm ClusterIP :4000
```

Auth: `Authorization: Bearer <LITELLM_MASTER_KEY>` (from the `litellm-keys` SOPS Secret).
Get it: `kubectl -n uap-system get secret litellm-keys -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d`

## Why host-serve, not an in-pod sidecar

An in-cluster tailscale node (sidecar) was tried and is **unreachable**: it registers + reaches a
DERP relay but stays `offline` with no peer data-path. Root cause: the k3s cluster network itself runs
over Tailscale (ADR-021, flannel `--iface` = the tailscale interface), so a pod-level tailscale node's
WireGuard traffic conflicts with the node-level tailscale and never gets a stable path. So exposure is
done at the NODE level, reusing uap-home-1's already-working (kernel-mode) tailscale.

## Setup / reproduce

On `uap-home-1` (the k3s server reaches ClusterIPs via kube-proxy):

```bash
CIP=$(sudo k3s kubectl -n uap-system get svc litellm -o jsonpath='{.spec.clusterIP}')
sudo tailscale serve --bg --https=443 http://$CIP:4000
sudo tailscale serve status          # shows the https URL + proxy target
```

The serve config persists in tailscaled state across reboots. Tailnet-wide **HTTPS Certificates** must
be enabled (admin console -> DNS) — they are. The cert for `uap-home-1.tail9fd337.ts.net` provisions on
the first HTTPS request (~5-10s).

If the litellm Service ClusterIP changes (Service recreated), re-run the two commands with the new IP.

## Reset

```bash
sudo tailscale serve reset            # removes the serve config on uap-home-1
```

## Smoke

```bash
F=uap-home-1.tail9fd337.ts.net
MK=$(kubectl -n uap-system get secret litellm-keys -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d)
curl -s -o /dev/null -w '%{http_code}\n' https://$F/health/liveliness     # 200
curl -s -H "Authorization: Bearer $MK" -H 'Content-Type: application/json' \
  -d '{"model":"smart-cloud","messages":[{"role":"user","content":"say hi"}]}' \
  https://$F/v1/chat/completions
```

## Future: dedicated `litellm.<tailnet>` name

Would need the Tailscale Kubernetes Operator (a controller) — and it may hit the same cluster-network
conflict. Revisit only if the node-name URL is insufficient. Host-serve is the supported path today.
