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

## Deployed: sing-box HA egress for hermes-agent (urltest failover, 2026-06-25)

The live egress is **sing-box** (not xray). Two SEPARATE Services keep the IP-pin and the failover
concerns apart:

- **`singbox-egress`** (`subfleet-egress.yaml`) — a SINGLE fixed VLESS+REALITY exit, consumed by
  **subfleet** (`subfleet.yaml`). subfleet's OAuth token is IP-pinned to one exit, so this Service
  must NOT rotate exits (see the warning in `clusters/prod/infra/subfleet-egress.yaml`; the
  `clusters/staging-stage3/` copy is archived).
- **`singbox-egress-ha`** (`singbox-egress-ha.yaml`) — VLESS+REALITY with a **`urltest`** outbound
  that AUTO-FAILS-OVER across the owner's subscription servers (probe every 30s, route the fastest
  live one, migrate in-flight connections off a dead one). Consumed by **hermes-agent** (Codex
  brain + Telegram), which is NOT IP-pinned. `route.final` = the urltest group; there is **no
  `direct` outbound**, so traffic can never exit clear from the RU origin IP.

### Regenerate the HA server list (when servers rotate / a server dies)

Servers come from the owner's VPN subscription (a base64 list of `vless://` URIs). Regenerate the
sing-box config + Secret with `infra/sops/gen-singbox-failover.py` (on uap-ops-1: has curl + sing-box
+ sops). `SUB_URL` = the owner's subscription endpoint:

```bash
curl -sL "$SUB_URL" -o /tmp/sub.dat
# SNI pre-flight gate: fetch the CURRENTLY-DEPLOYED config and diff the fresh servers against it
# BEFORE regenerating. A changed REALITY server_name (the 2026-07-09 subfleet bricker) or a pool
# add/remove FAILS CLOSED (exit 3) so `set -e` stops this chain before sops/PR. The report is
# host-masked; SNIs are shown (that IS the signal). Servers are matched by (host,port), not name.
kubectl get secret singbox-egress-ha-config -n uap-system \
  -o jsonpath='{.data.config\.json}' | base64 -d > /tmp/deployed.json
python3 infra/sops/gen-singbox-failover.py /tmp/sub.dat /tmp/config.json \
  --against /tmp/deployed.json          # a legitimate change? re-run adding --allow-sni-drift to confirm
sing-box check -c /tmp/config.json                                         # must validate
kubectl create secret generic singbox-egress-ha-config -n uap-system \
  --from-file=config.json=/tmp/config.json --dry-run=client -o yaml \
  > clusters/prod/infra/singbox-egress-ha-config.sops.yaml
sops -e -i clusters/prod/infra/singbox-egress-ha-config.sops.yaml
# DECRYPT-VERIFY (the 2026-07-09 corrupted-transport guard): prove the encrypted file actually
# decrypts (sops verifies its MAC) BEFORE it reaches a PR. A transport/hand-copy-corrupted secret
# otherwise surfaces only as Flux "no identity matched" AFTER merge. The age private key lives
# ONLY on uap-home-1, so pipe the file there (the file never leaves the checkout):
ssh uap@100.106.223.120 'sops -d --input-type yaml --output-type yaml /dev/stdin >/dev/null' \
  < clusters/prod/infra/singbox-egress-ha-config.sops.yaml && echo DECRYPT-VERIFY-OK
shred -u /tmp/sub.dat /tmp/config.json /tmp/deployed.json
# BUMP singbox-egress-ha/config-rev in singbox-egress-ha.yaml so Flux ROLLS the pod (sing-box reads
# its config only at startup; a Secret change alone does NOT restart it).
# commit via a PR (uap-commit-push); Flux applies the secret + rolls singbox-egress-ha onto the new config.
```

The generator fails loudly if a server is missing REALITY params and emits NO plaintext/`direct`
outbound. A dead server in the pool is harmless — urltest excludes it within ~30s (it re-joins
automatically if it recovers).

The `--against` gate is the pre-flight that would have made the 2026-07-09 SNI drift
(`microsoft.com` → `yahoo.com`) visible *before* it bricked subfleet, instead of after. It also
catches pool changes: e.g. a first run after the subscription added a US VLESS server reports
`pool +added [United States VLESS @ 130.*.*.*]` and stops for review — confirm with
`--allow-sni-drift`. Without `--against` the generator keeps its original 2-arg behaviour (no gate).
Regression test: `python tests/static/test_gen_singbox_failover.py` (also in CI `static-checks`).

### Verify

```bash
# real-target reachability through the HA proxy (from a debug pod or ops-1 with a local sing-box):
curl -x http://singbox-egress-ha.uap-system.svc:12080 -sS -o /dev/null -w '%{http_code}\n' \
  https://api.telegram.org    # expect 302 (reached Telegram) — NOT a connection reset
# the brain round-trip is the real proof: see runbooks/hermes-agent-codex-brain.md (CLI round-trip).
```

> subfleet note: `singbox-egress` (subfleet's fixed exit) is **LIVE**. Its DE exit was rotated to a
> live ninitux server (#103/#104) and subfleet served a real `chat.completions` (`claude-opus-4-8`)
> through it on 2026-07-09 — it is NOT pointing at a dead German exit. The one genuinely-open caveat:
> changing that exit's IP invalidates subfleet's IP/geo-pinned OAuth credential, so any repoint MUST
> re-seed + re-validate the DE-authorized credential from the new exit IP (owner-gated; full procedure
> in `runbooks/subfleet-integration.md`). Still do **NOT** fold subfleet onto the rotating
> `singbox-egress-ha` urltest — the pin needs ONE stable exit, and there is no generator for the
> pinned single-exit config (it is hand-maintained SOPS).

## Do Not

- Do not commit the filled-in xray/sing-box config, VLESS UUID, REALITY keys, or VPS address — SOPS/age only.
- Do not tunnel the whole node; only the LLM domains. k3s/etcd/Flux stay off the proxy.
- Do not put the egress proxy in the etcd/Flux critical path.
- Do not rely on OpenRouter to bypass the block — it does not.
