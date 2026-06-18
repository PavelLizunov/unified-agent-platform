# Garage Object Store (ADR-019)

## Scope

S3-compatible object storage for artifacts, checkpoints, k3s etcd-snapshot target, Restate async snapshots
(ADR-020), and backups. MinIO community edition was archived in Feb 2026 (no further security patches), so the
platform uses **Garage** instead. SeaweedFS is the alternative if Apache-2.0 / different load profile is needed.

Start single-node + offsite backup. Distributed mode / erasure coding is a separate step once disk layout is
known (EC starts at 2 drives; 4/node is the production recommendation, not the floor). Garage has no S3 Object
Lock — WORM retention, if ever required, is a separate decision.

## Deploy (single-node start)

Namespace `uap-system` already exists. The RPC secret goes in a Secret (env), not the ConfigMap.

### 1. Config (ConfigMap) + RPC secret (SOPS)

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: garage-config, namespace: uap-system }
data:
  garage.toml: |
    metadata_dir = "/var/lib/garage/meta"
    data_dir     = "/var/lib/garage/data"
    db_engine    = "lmdb"
    replication_factor = 1            # single-node start; raise with more nodes
    rpc_bind_addr   = "[::]:3901"
    rpc_public_addr = "127.0.0.1:3901"
    [s3_api]
    s3_region    = "garage"
    api_bind_addr = "[::]:3900"
    root_domain  = ".s3.uap.local"
    [s3_web]
    bind_addr   = "[::]:3902"
    root_domain = ".web.uap.local"
```

```bash
# generate and store the RPC secret (never commit plaintext)
openssl rand -hex 32 | kubectl -n uap-system create secret generic garage-rpc \
  --from-file=rpc_secret=/dev/stdin --dry-run=client -o yaml \
  > clusters/prod/apps/garage/garage-rpc.sops.yaml
sops --encrypt --in-place clusters/prod/apps/garage/garage-rpc.sops.yaml
```

### 2. StatefulSet + Service

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: garage, namespace: uap-system }
spec:
  serviceName: garage
  replicas: 1
  selector: { matchLabels: { app: garage } }
  template:
    metadata: { labels: { app: garage } }
    spec:
      containers:
        - name: garage
          image: dxflrs/garage:v2.1.0     # pin a real released tag
          env:
            - name: GARAGE_RPC_SECRET
              valueFrom: { secretKeyRef: { name: garage-rpc, key: rpc_secret } }
          ports:
            - { name: s3,  containerPort: 3900 }
            - { name: rpc, containerPort: 3901 }
            - { name: web, containerPort: 3902 }
          volumeMounts:
            - { name: config, mountPath: /etc/garage.toml, subPath: garage.toml }
            - { name: meta,   mountPath: /var/lib/garage/meta }
            - { name: data,   mountPath: /var/lib/garage/data }
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits:   { cpu: "1",  memory: 1Gi }
      volumes:
        - name: config
          configMap: { name: garage-config }
  volumeClaimTemplates:
    - metadata: { name: meta }
      spec: { accessModes: [ReadWriteOnce], resources: { requests: { storage: 5Gi } } }
    - metadata: { name: data }
      spec: { accessModes: [ReadWriteOnce], resources: { requests: { storage: 50Gi } } }
---
apiVersion: v1
kind: Service
metadata: { name: garage, namespace: uap-system }
spec:
  selector: { app: garage }
  ports:
    - { name: s3,  port: 3900, targetPort: 3900 }
    - { name: web, port: 3902, targetPort: 3902 }
```

### 3. Initialize layout, bucket, and key

```bash
G="kubectl -n uap-system exec sts/garage -- /garage"
$G status
NODE=$($G node id -q | cut -d@ -f1)
$G layout assign -z dc1 -c 50G "$NODE"
$G layout apply --version 1
$G bucket create uap
$G key create uap-app
$G bucket allow --read --write uap --key uap-app
# capture the Access Key ID + Secret Access Key from the key-create output ->
# store as a SOPS-encrypted k8s Secret; never print into chat/logs/git
```

## Consumers

- **k3s etcd snapshots:** point `etcd-s3` at `http://garage.uap-system.svc:3900`, region `garage`. Reuse the
  templates in `infra/k3s/examples/k3s-etcd-snapshot-s3-config.example.yaml` and
  `infra/sops/templates/k3s-etcd-snapshot-s3-config.plaintext.template.yaml` (set `etcd-s3-region: garage`).
- **Restate:** configure the snapshot destination to the same bucket (Restate writes async RocksDB snapshots to
  S3; it does NOT use Postgres — ADR-020).
- **Artifacts / checkpoints:** agents use the `uap-app` key.

## Backup

- Replicate the `uap` bucket offsite (e.g. `rclone sync` to Cloudflare R2) — see `runbooks/offsite-backups.md`.
- Test restore of an object and a full bucket, not only creation.

## Do Not

- Do not use the archived MinIO community image — no security patches after Feb 2026.
- Do not commit the RPC secret, S3 access/secret keys, or any bucket credentials — SOPS/age only.
- Do not assume Object Lock / WORM — Garage does not provide it.
- Do not enable distributed mode / erasure coding until disk layout and node count are settled.
