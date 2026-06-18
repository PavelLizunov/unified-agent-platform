# LLM Egress from Russia (ADR-018)

## Scope

The homelab is in Russia. `api.anthropic.com`, `api.openai.com`, and `openrouter.ai` are not reachable directly
(network blocks + provider geo-restrictions). OpenRouter does not bypass this. This runbook defines how the cloud
LLM groups (`smart-cloud`, `cloud-fallback`) reach their backends.

Keep the two network planes separate: **Tailscale** is the internal mesh (device <-> cluster), **VLESS** is the
LLM egress. Tunnel only LLM traffic, never the whole node — k3s/etcd/Flux stay on direct/Tailscale.

## Two options

### Plan A — LiteLLM on a non-RU node (preferred once a foreign VPS exists)

Pin LiteLLM pods to a non-RU k3s node; it reaches Anthropic/OpenRouter directly. Agents reach LiteLLM over the
tailnet. No censorship tooling in the API path.

```yaml
# In the LiteLLM Deployment spec. The foreign egress node must be adequately sized —
# NOT the thin 1 GB etcd-only VPS profile (see BUILD-PLAN Stage 2 placement).
spec:
  replicas: 2
  template:
    spec:
      nodeSelector:
        uap.region: non-ru        # label the foreign node: kubectl label node <vps> uap.region=non-ru
      topologySpreadConstraints:  # spread the 2 replicas across nodes
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector: { matchLabels: { app: litellm } }
```

This is the target state. Until a foreign node exists (Stage 0P is all-local), use Plan B.

### Plan B — VLESS egress gateway in the RU cluster (use now)

```
LiteLLM (RU) -> xray-egress (SOCKS5/HTTP, 2 replicas) -> VLESS+REALITY tunnel -> VLESS server abroad -> Claude API
```

Prerequisite: a cheap non-RU VPS running an Xray VLESS+REALITY **server** (UUID, REALITY key pair, short id, a
borrowed SNI of a real reachable TLS site). Keep >=2 servers in different ASNs/countries for redundancy.

## Plan B manifests

Namespace `uap-system` already exists. The xray config carries the UUID and REALITY public key, so it lives in a
**SOPS-encrypted Secret**, not a ConfigMap.

### 1. Egress config (encrypt with SOPS before committing)

`infra/sops/templates/xray-egress.plaintext.template.json` (placeholders only — never commit real values):

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    { "tag": "http",  "listen": "0.0.0.0", "port": 8118, "protocol": "http" },
    { "tag": "socks", "listen": "0.0.0.0", "port": 1080, "protocol": "socks", "settings": { "udp": true } }
  ],
  "outbounds": [
    {
      "tag": "vless-a",
      "protocol": "vless",
      "settings": { "vnext": [ {
        "address": "REPLACE_WITH_VPS_HOST_A",
        "port": 443,
        "users": [ { "id": "REPLACE_WITH_VLESS_UUID_A", "encryption": "none", "flow": "xtls-rprx-vision" } ]
      } ] },
      "streamSettings": { "network": "tcp", "security": "reality", "realitySettings": {
        "serverName": "REPLACE_WITH_SNI_DOMAIN_A", "fingerprint": "chrome",
        "publicKey": "REPLACE_WITH_REALITY_PUBLIC_KEY_A", "shortId": "REPLACE_WITH_SHORT_ID_A" } }
    },
    {
      "tag": "vless-b",
      "protocol": "vless",
      "settings": { "vnext": [ {
        "address": "REPLACE_WITH_VPS_HOST_B",
        "port": 443,
        "users": [ { "id": "REPLACE_WITH_VLESS_UUID_B", "encryption": "none", "flow": "xtls-rprx-vision" } ]
      } ] },
      "streamSettings": { "network": "tcp", "security": "reality", "realitySettings": {
        "serverName": "REPLACE_WITH_SNI_DOMAIN_B", "fingerprint": "chrome",
        "publicKey": "REPLACE_WITH_REALITY_PUBLIC_KEY_B", "shortId": "REPLACE_WITH_SHORT_ID_B" } }
    },
    { "tag": "direct", "protocol": "freedom" }
  ],
  "observatory": {
    "subjectSelector": ["vless-"],
    "probeURL": "https://www.cloudflare.com/cdn-cgi/trace",
    "probeInterval": "30s"
  },
  "routing": {
    "balancers": [
      { "tag": "llm-egress", "selector": ["vless-"], "strategy": { "type": "leastPing" } }
    ],
    "rules": [
      { "type": "field",
        "domain": ["api.anthropic.com", "openrouter.ai", "api.openai.com"],
        "balancerTag": "llm-egress" }
    ]
  }
}
```

Only the LLM domains route through the tunnel; everything else goes `direct`.

Encrypt and store the Secret:

```bash
# build the Secret manifest from the filled-in (non-committed) config, then encrypt with the cluster age recipient
mkdir -p clusters/prod/apps/llm-egress
kubectl -n uap-system create secret generic xray-egress-config \
  --from-file=config.json=./xray-egress.config.json \
  --dry-run=client -o yaml > clusters/prod/apps/llm-egress/xray-egress-config.sops.yaml
sops --encrypt --in-place clusters/prod/apps/llm-egress/xray-egress-config.sops.yaml
# the filled-in xray-egress.config.json is gitignored; only the .sops.yaml is committed
```

### 2. Deployment + Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: xray-egress, namespace: uap-system }
spec:
  replicas: 2
  selector: { matchLabels: { app: xray-egress } }
  template:
    metadata: { labels: { app: xray-egress } }
    spec:
      affinity:                                   # keep the 2 replicas on different nodes
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                topologyKey: kubernetes.io/hostname
                labelSelector: { matchLabels: { app: xray-egress } }
      containers:
        - name: xray
          image: ghcr.io/xtls/xray-core:25.6.8   # pin a real released tag
          args: ["run", "-c", "/etc/xray/config.json"]
          ports:
            - { name: http,  containerPort: 8118 }
            - { name: socks, containerPort: 1080 }
          volumeMounts:
            - { name: config, mountPath: /etc/xray, readOnly: true }
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 500m, memory: 256Mi }
      volumes:
        - name: config
          secret: { secretName: xray-egress-config }
---
apiVersion: v1
kind: Service
metadata: { name: xray-egress, namespace: uap-system }
spec:
  selector: { app: xray-egress }
  ports:
    - { name: http,  port: 8118, targetPort: 8118 }
    - { name: socks, port: 1080, targetPort: 1080 }
```

### 3. Point LiteLLM at the proxy

```yaml
# LiteLLM Deployment env. NO_PROXY MUST include the cluster + the tailnet Ollama,
# so cheap-local and in-cluster traffic do NOT go through the tunnel.
env:
  - { name: HTTPS_PROXY, value: "http://xray-egress.uap-system.svc:8118" }
  - { name: HTTP_PROXY,  value: "http://xray-egress.uap-system.svc:8118" }
  - { name: NO_PROXY,    value: "localhost,127.0.0.1,.svc,.cluster.local,100.64.0.0/10" }
```

For Claude, keep the native `anthropic/` provider (`anthropic/claude-opus-4-8`) — a translation path, not a
passthrough — and verify that prompt caching and adaptive thinking actually survive it; do not force a bare
OpenAI schema (see BUILD-PLAN Stage 3).

## Verification

```bash
# from a LiteLLM pod (or a debug pod), confirm the tunnel reaches Anthropic
kubectl -n uap-system run egress-test --rm -it --image=curlimages/curl --restart=Never -- \
  -x http://xray-egress.uap-system.svc:8118 -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/models
# expect a 401 (reached the API, no key) — NOT a timeout/connection error
```

## Health and fallback

- The config above balances over >=2 VLESS servers (`leastPing` + observatory health probes) — run them in
  different ASNs/countries so one server (or one Secret) is not a single point of failure. Alert on tunnel failure.
- The Deployment uses `podAntiAffinity` so the 2 xray replicas land on different nodes.
- Egress is a SPOF for Plane B. If the foreign channel is fully down, the `smart-cloud -> cloud-fallback`
  chain also fails — the ultimate fallback is `cheap-local` (Ollama in RU): degradation, not outage.
- Related: Tailscale's own control plane may be throttled in RU (RISKS #16) — keep a Headscale migration plan.

## Do Not

- Do not commit the filled-in xray config, VLESS UUID, REALITY keys, or VPS address — SOPS/age only.
- Do not tunnel the whole node; only the LLM domains. k3s/etcd/Flux stay off the proxy.
- Do not put the egress proxy in the etcd/Flux critical path.
- Do not rely on OpenRouter to bypass the block — it does not.
