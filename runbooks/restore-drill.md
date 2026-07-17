# k3s Restore Drill

## Scope

This runbook verifies that k3s embedded etcd snapshots can actually restore a cluster.

Do not run restore commands on `uap-home-1` or any live server unless you are intentionally recovering from a real
incident. The normal drill target is a disposable VM.

## Why This Exists

Listing snapshots proves that backup creation works. It does not prove recoverability.

K3s snapshots are encrypted with bootstrap data protected by the server token. Back up the snapshot and the server
token together, but never commit or print the token.

## Preconditions

- A disposable Debian 12 VM with SSH access.
- Tailscale connected if the disposable VM should use tailnet networking.
- Same k3s version as prod, or a later compatible minor version.
- A recent snapshot from `uap-home-1`.
- The original server token from `/var/lib/rancher/k3s/server/token` or `/var/lib/rancher/k3s/server/node-token`,
  stored temporarily outside git.

## Create a Fresh Snapshot

```powershell
ssh uap@100.106.223.120 'SNAP=uap-restore-drill-$(date -u +%Y%m%dT%H%M%SZ); sudo k3s etcd-snapshot save --name $SNAP'
ssh uap@100.106.223.120 'sudo k3s etcd-snapshot list | grep uap-restore-drill-'
```

Record the snapshot filename from the output.

## Copy Snapshot and Token

Use a secure temporary directory on the operator machine or transfer directly to the disposable VM.

Example shape:

```powershell
$snapshot = "REPLACE_WITH_SNAPSHOT_NAME"
New-Item -ItemType Directory -Force .\tmp | Out-Null
ssh uap@100.106.223.120 "sudo install -m 0640 /var/lib/rancher/k3s/server/db/snapshots/$snapshot /tmp/$snapshot && sudo chown uap:uap /tmp/$snapshot"
scp uap@100.106.223.120:/tmp/$snapshot .\tmp\$snapshot
ssh uap@100.106.223.120 "sudo rm -f /tmp/$snapshot"
ssh uap@100.106.223.120 "sudo cat /var/lib/rancher/k3s/server/token" > .\tmp\server-token
```

Delete the local token copy after the drill.

## Restore on Disposable VM

Prepare `/etc/rancher/k3s/config.yaml` for the disposable host. Use its own node name and tailnet IP.

Copy the snapshot and token to the disposable VM:

```powershell
scp .\tmp\$snapshot uap@DISPOSABLE_HOST:/tmp/$snapshot
scp .\tmp\server-token uap@DISPOSABLE_HOST:/tmp/server-token
```

On the disposable VM:

```bash
sudo systemctl stop k3s || true
sudo install -d -m 0700 /var/lib/rancher/k3s/server
sudo install -m 0600 /tmp/server-token /var/lib/rancher/k3s/server/token
sudo install -d -m 0700 /var/lib/rancher/k3s/server/db/snapshots
sudo install -m 0600 /tmp/REPLACE_WITH_SNAPSHOT_NAME /var/lib/rancher/k3s/server/db/snapshots/REPLACE_WITH_SNAPSHOT_NAME
sudo k3s server \
  --config /etc/rancher/k3s/config.yaml \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/REPLACE_WITH_SNAPSHOT_NAME
sudo systemctl start k3s
```

If the disposable VM does not yet have the k3s service installed, install the same pinned version first with start
disabled, then run the restore command.

## Verify

```bash
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get namespaces
sudo k3s kubectl -n flux-system get deploy
sudo k3s kubectl get secret -n flux-system sops-age
```

Pass criteria:

- API server answers.
- Restored cluster contains expected namespaces.
- Flux objects are visible.
- `sops-age` exists.

Do not join this disposable restored node back to the real cluster.

## Cleanup

```powershell
Remove-Item .\tmp\server-token -Force
```

Destroy the disposable VM after the drill or wipe `/var/lib/rancher/k3s`.

## S3 Restore Note

When restoring from S3, pass S3 configuration flags to the restore command. The Kubernetes S3 config Secret cannot be
used during restore because the API server is not available yet.

Verified 2026-06-19 against Cloudflare R2 (EU endpoint): `k3s server --cluster-reset --etcd-s3 --etcd-s3-endpoint=... --etcd-s3-access-key=... --etcd-s3-secret-key=... --etcd-s3-bucket=uap-k3s-snapshots --etcd-s3-folder=prod --etcd-s3-region=auto --cluster-reset-restore-path=<snapshot-name>` downloaded the snapshot from R2, decrypted it with the home-1 server token, and restored etcd. The restored cluster showed both nodes, all namespaces, the Flux controllers, and the `uap-platform` Kustomization at the current commit.

## Secrets Encryption — Cross-Node Restore Result

**PASS 2026-07-12.** With `secrets-encryption: true`, a snapshot taken after creating a random canary Secret was
fetched back from R2 and restored on clean `debian-xfce` using k3s `v1.35.5+k3s1`. Only the snapshot and original
server token were transferred; `encryption-config.json` was deliberately absent before `cluster-reset`.

K3s extracted the encryption config from snapshot bootstrap data, started a new single-member etcd cluster and
returned the exact canary value byte-for-byte. Therefore snapshot + original token are sufficient for the current
configuration; the separately age-encrypted `dr/encryption-config.json` remains belt-and-suspenders, not a required
restore input. The prior `identity transformer tried to read encrypted data` result was caused by the incomplete
target startup, not missing snapshot material.

The production canary namespace, exact local/R2 test snapshot, staged token/value and all disposable k3s/CNI state
were removed. Production nodes remained Ready and the test VM returned to its original non-k3s state.

## Canary Secret-value restore drill (disposable-only)

Status: **verified PASS 2026-07-12**. Keep this procedure for future periodic drills. A repeat within this exact
repo-defined boundary needs no per-run approval: the restore target is disposable, the production object is a temporary
canary Secret, and cleanup is mandatory.

**Purpose.** Repeatably prove that a Secret *value* (not just the Secret object) survives a cross-node restore from
the R2 snapshot using the snapshot + original server token alone.

**Safety boundary.** Use only a **disposable k3s node** as the restore target. The drill creates a throwaway production
Secret and snapshot, then removes both. Using a live/non-disposable restore target, retaining test data or widening the
procedure is outside this standing authorization and requires explicit owner approval.

Run the prod-side steps from `uap-ops-1` (has `kubectl` + the R2 `rclone` remote). Reuse the **Restore on Disposable
VM** and **S3 Restore Note** sections above for the actual `cluster-reset` restore mechanics — this drill only adds
the canary Secret and the value read-back around them.

### 0. Check whether secrets encryption at rest is even on

This decides whether `encryption-config.json` is in scope at all.

```bash
# uap-home-1 — authoritative status + config + on-disk file
ssh uap@100.106.223.120 'sudo k3s secrets-encrypt status || true'
ssh uap@100.106.223.120 'grep -E "secrets-encryption|secrets-encrypt" /etc/rancher/k3s/config.yaml || echo "no secrets-encryption flag in config.yaml"'
ssh uap@100.106.223.120 'sudo test -f /var/lib/rancher/k3s/server/cred/encryption-config.json && echo "encryption-config.json PRESENT" || echo "encryption-config.json absent"'
```

- **Encryption DISABLED** (status "Disabled", no flag, file absent): values are stored plaintext in etcd. The
  restore in step 3 needs only snapshot + token; the read-back in step 4 will succeed with no encryption-config.
  That itself answers the TODO for the current setup ("not required, because encryption is off").
- **Encryption ENABLED** (status "Enabled", flag present, file present): proceed with the drill's core test —
  restore with **only** snapshot + token (do **not** pre-place `encryption-config.json`) and see if the value still
  decrypts (step 3/4).

### 1. Create a throwaway canary Secret in prod with a known value

```bash
# uap-ops-1 — generate + RECORD this value locally (not committed); you compare against it in step 4
CANARY_VALUE="dr-canary-$(date -u +%Y%m%dT%H%M%SZ)-$(head -c8 /dev/urandom | base64 | tr -dc 'a-z0-9')"
echo "$CANARY_VALUE"                      # write it down / keep in the operator's temp notes
kubectl create namespace dr-canary
kubectl -n dr-canary create secret generic dr-canary --from-literal=value="$CANARY_VALUE"
```

The value is a throwaway random string, so recording it locally for the drill is fine; still do **not** commit it.

### 2. Take an etcd snapshot to R2 (must be AFTER step 1 so it captures the canary)

```bash
# uap-home-1 — on-demand snapshot; prod config.yaml ships it to R2 (folder prod/)
ssh uap@100.106.223.120 'SNAP=dr-canary-$(date -u +%Y%m%dT%H%M%SZ); sudo k3s etcd-snapshot save --name "$SNAP"; echo "$SNAP"'
# uap-ops-1 — confirm it landed offsite; record the exact object name
rclone ls r2:uap-k3s-snapshots/prod/ | grep dr-canary
```

Record the snapshot filename. Also stage the **original server token** exactly as in **Copy Snapshot and Token**
above (`sudo cat /var/lib/rancher/k3s/server/token` → temp file outside git; delete after the drill).

### 3. Restore on the CLEAN disposable node — snapshot + token ONLY

On the disposable k3s node, run the **S3 Restore Note** `cluster-reset` command (restores directly from R2), passing
the R2 flags + `--cluster-reset-restore-path=<the dr-canary snapshot>`, with the original token installed at
`/var/lib/rancher/k3s/server/token`.

**Do NOT pre-place `encryption-config.json`.** That omission is the whole point: it tests whether the snapshot's
bootstrap data (protected by the token) already carries the encryption keys.

### 4. Read back the canary VALUE and compare

```bash
# disposable node, after k3s comes up
sudo k3s kubectl -n dr-canary get secret dr-canary -o jsonpath='{.data.value}' | base64 -d; echo
```

Interpretation (this is what settles the TODO):

- Output **equals the recorded `CANARY_VALUE`** → snapshot + token **alone** suffice; a separate
  `encryption-config.json` is **NOT** required. Update the caveat above to state this.
- Output is `identity transformer tried to read encrypted data` (or similar decrypt error) → the separate
  `encryption-config.json` **IS** required. Re-run: fetch `k3s-encryption-config.json.age` from R2 `dr/` (see
  **Bootstrap Materials Offsite** below), age-decrypt it, install it at
  `/var/lib/rancher/k3s/server/cred/encryption-config.json`, then repeat the `cluster-reset` restore and confirm the
  value now matches.

**Pass criterion:** the read-back value byte-for-byte matches the recorded `CANARY_VALUE` (in whichever of the two
configurations turns out to be required). Record which one it was.

### 5. Tear down

```bash
# uap-ops-1 — remove the prod canary
kubectl delete namespace dr-canary
# uap-ops-1 — optional: drop the throwaway snapshot so it is not mistaken for a routine backup
#   rclone delete r2:uap-k3s-snapshots/prod/<the dr-canary snapshot>
# operator machine — shred the staged token and the recorded canary value
shred -u ./tmp/server-token 2>/dev/null || rm -f ./tmp/server-token
```

Destroy the disposable node or wipe `/var/lib/rancher/k3s` (per **Cleanup** above). Do not join it to the real
cluster.

## Bootstrap Materials Offsite (R2 `dr/`)

For a self-contained cross-node DR, the server token and the secrets-encryption config are kept in R2 alongside the
etcd snapshots, **age-encrypted** (same recipient as `.sops.yaml`). Decryption needs the age **private** key — keep
it in a verified, owner-controlled escrow **off the homelab**. NOTE: the cluster's `sops-age` secret (the same key)
is readable from `uap-ops-1` via kubectl, so an in-homelab copy is **not** an independent escrow. These files are
static: re-upload only after rotating the server token or re-keying secrets-encryption. After uploading, shred the
staging copies: `shred -u /tmp/k3s-*.age` on the staging host (and on `uap-home-1` if produced there).

Upload (encrypt on `uap-home-1`, push from `uap-ops-1` which has the R2 `rclone` remote; shred the /tmp copies after):

```bash
# uap-home-1 — RECIP is the public age recipient from .sops.yaml
RECIP=$(awk -F"'" '/age:/{print $2}' .sops.yaml)   # or paste the age1... recipient
sudo age -r "$RECIP" -o /tmp/k3s-server-token.age            /var/lib/rancher/k3s/server/token
sudo age -r "$RECIP" -o /tmp/k3s-encryption-config.json.age  /var/lib/rancher/k3s/server/cred/encryption-config.json
sudo chown uap:uap /tmp/k3s-*.age
# move to uap-ops-1, then:
rclone copy k3s-server-token.age            r2:uap-k3s-snapshots/dr/
rclone copy k3s-encryption-config.json.age  r2:uap-k3s-snapshots/dr/
```

Restore use (on the replacement node, with the age private key present):

```bash
rclone copy r2:uap-k3s-snapshots/dr/k3s-server-token.age           .
rclone copy r2:uap-k3s-snapshots/dr/k3s-encryption-config.json.age .
age -d -i age-keys.txt -o server-token           k3s-server-token.age
age -d -i age-keys.txt -o encryption-config.json k3s-encryption-config.json.age
sudo install -m 0600 server-token /var/lib/rancher/k3s/server/token
sudo install -d -m 0700 /var/lib/rancher/k3s/server/cred
sudo install -m 0600 encryption-config.json /var/lib/rancher/k3s/server/cred/encryption-config.json
# then run the cluster-reset S3 restore above; secrets now decrypt because the encryption key matches.
```

Verified 2026-06-19: the offsite token age-decrypts back to the live token (round-trip OK).
