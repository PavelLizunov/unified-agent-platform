# Independent Codex Cross-Review

Date: 2026-06-19  
Reviewed commit: `0ab1d056726bba90e5a8d2b65f73ce8584fad664` (`master`)  
Mode: read-only review; no destructive tests; secret values were not printed or recorded.

> **Banner (2026-06-23):** point-in-time review of commit `0ab1d05`. **Superseded in part by the 2026-06-22/23
> hermes-agent / vibe-coding pivot** (see `STATUS.md`, `docs/next-steps.md`, ADR-022..026). The handoff-drift this
> review flagged reopened at larger scale (the live model+agent layer was absent from CLAUDE.md/STATUS.md) and is now
> addressed. The **foundation findings remain valid** — HA, ops-1 blast-radius, DR are tracked as Track B in
> `docs/next-steps.md`.

## Scope

Independent adversarial review of the Stage 0P repository and live nodes:

- `uap-home-1` (`100.106.223.120`) — k3s server;
- `uap-ops-1` (`100.82.241.121`) — operator VM;
- GitOps/Flux sync, R2 etcd backups and restore drill;
- VLESS egress and Vaultwarden;
- secret hygiene, DR, Ansible idempotency and plan consistency.

The working tree was clean before this report was added. Flux was observed reconciling the reviewed commit:

```text
GitRepository/uap-platform: Ready=True
Kustomization/uap-platform: Applied revision master@sha1:0ab1d056...
```

## Executive Verdict

The repository contains no detected committed plaintext secret, and the core architecture corrections
(Garage instead of MinIO, Restate storage model, ADR-018 egress, ADR-021 flannel over `tailscale0`) are broadly
consistent.

However, Stage 2 must not start yet. Stage 1 HA is not complete, the operator VM has an excessive combined blast
radius, cross-node Secret recovery has not been demonstrated end-to-end, and the Stage 2 placement/milestone can
produce a false HA result.

## Requested HIGH Findings

### 1. R2 credentials on `uap-ops-1` — CONFIRMED

The live `~/.config/rclone/rclone.conf`:

- exists with mode `0600`;
- is not encrypted as an rclone configuration;
- contains literal plaintext S3 credentials;
- uses the same Access Key ID and Secret Access Key as
  `kube-system/k3s-etcd-snapshot-s3-config`;
- points to the same normalized R2 endpoint;
- can list/read the `uap-k3s-snapshots` bucket.

Safe comparison output:

```text
rclone_whole_config_encrypted=no
credential_access_key_same=yes
credential_secret_same=yes
rclone_secret_storage=literal-plaintext
endpoint_same_normalized=yes
r2_visible_buckets=uap-k3s-snapshots
```

The bucket has no versioning, no Object Lock, and no object-expiration lifecycle rule. Its only lifecycle rule is
the Cloudflare default multipart-upload abort rule. Compromise of `uap-ops-1` therefore exposes `prod/` and `dr/`
to read, overwrite and, with normal R2 Object Read & Write permissions, deletion.

This is more severe than an isolated R2 credential leak because the same VM also has cluster-admin Kubernetes
access. An attacker can read the `flux-system/sops-age` Secret and use it to decrypt the age-encrypted k3s token
stored under `dr/`.

### 2. VLESS material in `~/.secrets` — CONFIRMED WITH QUALIFICATION

Observed on `uap-ops-1`:

```text
~/.secrets mode=0700
sb-client.json mode=0600
singbox.json mode=0600
vless.decoded mode=0600
vless.sub.raw mode=0600
```

All four are plaintext JSON and contain three VLESS UUIDs and three REALITY public-key fields. No REALITY private
key was found. The active systemd user service runs sing-box with
`/home/uap/.secrets/sb-client.json`.

`singbox.json`, `vless.decoded`, and `vless.sub.raw` are identical duplicate copies. The UUIDs are live tunnel
credentials; the REALITY keys present are client-side public keys, not server private keys.

### 3. Cross-node Secret restore — TEST GAP CONFIRMED, STATED THEORY REFUTED

The recorded drill proves restoration of etcd objects, nodes, namespaces and Flux resources, but does not record a
successful read of a known Secret value:

- `runbooks/restore-drill.md:112-123`
- `STATUS.md:166-167`

The R2 `dr/` materials were added in commit `0ab1d05`, after the drill commit `acb47ae`, so the drill could not have
used the R2 copy of `encryption-config.json`.

The current runbook's technical explanation is incorrect. Current k3s documentation states that an etcd snapshot
with secrets encryption enabled already contains the secrets-encryption configuration and keys. This bootstrap
material is encrypted using a key derived from the original server token. Restoring to another host requires the
original server token.

Therefore:

- snapshot + correct original server token should be sufficient for Secret recovery;
- a separate `encryption-config.json` copy is additional defence, not an established mandatory prerequisite;
- the actual failure mode must be tested, not inferred.

Required proof: restore onto a clean disposable node using the R2 snapshot and original token, then read and compare
a deliberately created canary Secret. Also test the documented procedure without pre-installing
`encryption-config.json`.

References:

- <https://docs.k3s.io/cli/etcd-snapshot>
- <https://docs.k3s.io/cli/token>

### 4. R2 snapshot retention — PARTIALLY REFUTED

Confirmed:

- live config has `etcd-snapshot-retention: 7`;
- neither live config nor the S3 config Secret contains `etcd-s3-retention`;
- the R2 bucket has no expiration lifecycle rule.

However, k3s `v1.35.5+k3s1` has a distinct S3 retention option with default `5`. Scheduled S3 snapshots therefore
do not accumulate without limit merely because the explicit key is absent.

Manual/on-demand snapshots have no automatic retention and do accumulate. At review time `prod/` contained one
scheduled and two manually named snapshots.

`STATUS.md:189` is inaccurate when it describes the R2 retention as `7`; that configured value is local retention.

### 5. `uap-ops-1` as SPOF and security concentration — CONFIRMED

The 2 GiB, no-swap VM simultaneously holds or runs:

- sing-box egress;
- Vaultwarden;
- R2 credentials;
- GitHub credentials;
- cluster-admin kubeconfig;
- an SSH private key authorized on both k3s nodes.

Vaultwarden observations:

```text
image=docker.io/vaultwarden/server:latest
healthcheck=none
data=/home/uap/vaultwarden/data
Vaultwarden backup artifacts=0
Vaultwarden backup timers=0
```

The VM is on `pve-ninitux`, the same physical Proxmox node as `uap-home-1`. Proxmox VM backups are still pending.

Repository searches found no implementation or recovery runbook for sing-box or Vaultwarden. This contradicts the
description of `uap-ops-1` as disposable in `runbooks/uap-ops-node.md:5`.

### 6. Stage 3 egress endpoint — CONFIRMED BLOCKER

Live state:

```text
sing-box listener=127.0.0.1:12080
tailnet TCP 100.82.241.121:12080=unreachable
local proxy test through 127.0.0.1:12080=HTTP 200
uap-system Service count=0
xray-egress Service=absent
```

`clusters/prod/apps/kustomization.yaml` has an empty resource list. The declared
`http://xray-egress.uap-system.svc:8118` endpoint in `runbooks/llm-egress-vless.md:172` does not exist.

The live sing-box process is functional locally, but in-cluster LiteLLM cannot reach it in its current binding.

## Additional Findings Missed by the Previous Review

### HIGH — GitHub-to-cluster takeover path

On `uap-ops-1`, `gh` is authenticated with scopes:

```text
repo, workflow, read:org
```

GitHub reports no branch protection rules. Flux follows mutable `master` directly, applies `clusters/prod`, enables
`prune: true`, and the Flux kustomize-controller can perform `*` on `*` cluster-wide.

Compromise of the GitHub token can therefore become cluster-admin code execution through a direct push and Flux
reconciliation.

Evidence:

- `clusters/prod/flux-system/gotk-sync.ssh.yaml:8-31`
- live `kubectl auth can-i '*' '*' --as=system:serviceaccount:flux-system:kustomize-controller` returned `yes`;
- GitHub GraphQL `branchProtectionRules.totalCount` returned `0`.

### HIGH — DR age-key escrow is not independent

The age private key was found on `uap-home-1`. It was not found on `uap-ops-1` or the Windows workstation.

If `uap-home-1` is lost, the reviewed environment has no demonstrated independent copy capable of decrypting the
age-encrypted server token in R2. `STATUS.md` should not call DR materials complete until the owner has verified an
off-homelab escrow copy and performed a restore with it.

Do not put the private key value in git, markdown, prompts or logs.

### HIGH — Stage 2 can pass a false Postgres HA milestone

`BUILD-PLAN.md:168-170` says all three Postgres instances run on the home server while also calling for pod
anti-affinity and topology spreading. The milestone at `BUILD-PLAN.md:173` only deletes the primary pod.

That tests process/pod failover, not node or failure-domain failover. Three pods on one physical host may pass while
remaining a single-node SPOF.

Before implementation, define the honest Stage 2 claim:

- either recovery-oriented single-node state services until suitable worker failure domains exist;
- or provide enough independent worker nodes/storage for real Postgres HA and test loss of a whole node.

### HIGH — Ansible does not guarantee convergence

The k3s server and agent playbooks render config before checking only for `/usr/local/bin/k3s`. They do not notify a
k3s restart when config changes, and installation/role selection is skipped whenever the binary already exists.

Relevant locations:

- `infra/ansible/playbooks/30-k3s-server.yml:33-54`
- `infra/ansible/playbooks/31-k3s-agent.yml:30-51`

Consequences:

- config changes can be silently unapplied until an unrelated restart;
- upgrades are not enforced;
- promoting an existing agent to server is not safely represented;
- checking binary presence does not verify the installed role or version.

The Ansible syntax check passed on `uap-ops-1`, but a two-run live idempotency/convergence test has not been recorded.

### MEDIUM/HIGH — Broad kubeconfig and network exposure

The tracked k3s config explicitly sets `write-kubeconfig-mode: "0644"`:

- `infra/k3s/uap-home-1.config.yaml:13`
- `infra/ansible/templates/k3s-server.config.yaml.j2:21`

The live admin kubeconfig is consequently world-readable on the VM. The API server (`6443`), Flannel VXLAN
(`8472`) and kubelet (`10250`) listen on all interfaces; no host firewall rules were observed, and port 6443 was
reachable through the LAN address.

This is inconsistent with the intended “tailnet-only” administrative boundary.

### MEDIUM — Handoff/source-of-truth drift

`CLAUDE.md` is stale and conflicts with both `STATUS.md` and live state:

- `CLAUDE.md:45` says no Git origin exists;
- `CLAUDE.md:49` says Git/S3 readiness is missing;
- `CLAUDE.md:137-140` lists Git sync, S3 and restore drill as future tasks.

All three were already complete at the reviewed commit.

`STATUS.md` omits the live Vaultwarden and sing-box services and incorrectly reports S3 retention as 7.

### MEDIUM — Restate DR is underspecified

ADR-020 correctly removes Postgres as Restate's durable store. The architecture now correctly describes Bifrost,
RocksDB and S3 snapshots.

However, Restate documentation distinguishes operational partition snapshots from complete disaster-recovery
backups. A Stage 4 DR design must cover metadata, logs, partition stores and node configuration rather than assuming
that Garage snapshots alone constitute a complete multi-node backup.

Reference: <https://docs.restate.dev/references/architecture>

### MEDIUM — Garage deployment version and availability claim need review

`runbooks/garage-object-store.md:64` pins Garage `v2.1.0`; the current release observed during review is `v2.3.0`.
The exact version must be revalidated before deployment.

Garage upstream explicitly warns that a single-node deployment has no redundancy. The repository documents this
partially, but Stage 2 must not label single-node Garage as HA merely because offsite recovery exists.

Reference: <https://garagehq.deuxfleurs.fr/documentation/quick-start/>

## Secret Hygiene

Passed:

```text
tests/static/secret-scan.ps1 -> secret-scan-ok
tests/static/validate-iac.ps1 -> iac-static-ok
```

Additional manual scanning covered:

- all reachable git objects;
- 62 unreachable git blobs;
- age private-key signatures;
- PEM/private-key blocks;
- GitHub, Anthropic, OpenRouter and Tailscale token signatures;
- R2 plaintext key fields;
- VLESS URI markers.

No committed plaintext secret was found.

Limitations:

- the repository scanner does not currently detect common GitHub/Anthropic/OpenRouter/R2/VLESS signatures;
- it does not inspect shell history, arbitrary ignored files or remote nodes;
- the ignored local Windows kubeconfig ACL allows read access to `CodexSandboxUsers`;
- live plaintext secrets on `uap-ops-1` are outside git and therefore invisible to the repository gate.

No matching live secret values were found in `.bash_history`; neither checked Linux account had a bash history file.

## Plan Consistency and Sequencing

### Consistent

- Garage replaces MinIO across the active design.
- Restate's durable log is not mapped to Postgres.
- ADR-018 defines the dedicated non-RU LLM egress path.
- ADR-021 and live configs use `node-ip` on tailnet plus `flannel-iface: tailscale0`.
- Live k3s config materially matches the tracked node config.

### Inconsistent or unsafe

- `BUILD-PLAN.md:3-4` and `:117` prohibit Stage 2 before a green Stage 1 milestone.
- The live cluster has one k3s server and one agent; it is not HA.
- Building Stage 2 services now would violate the documented sequence. Preparing and reviewing manifests is safe;
  applying Stage 2 is not.
- The planned Postgres placement cannot support an honest physical-node HA claim.
- ADR-018 Plan B requires an in-cluster `xray-egress` with at least two replicas, while live state is one host-local
  sing-box instance on the operator VM.

## Top Three Required Actions Before Stage 2

1. **Reduce the `uap-ops-1` blast radius.**
   - Enable branch protection/required review or otherwise prevent direct privileged pushes.
   - Replace the broad GitHub token with least privilege.
   - Separate R2 backup credentials from interactive rclone credentials and limit prefixes/permissions where
     possible.
   - Add tested Vaultwarden and ops-node backup/recovery procedures.

2. **Finish and prove DR.**
   - Put the age private key in a verified independent owner-controlled offsite escrow.
   - Repeat the cross-node restore using only the documented offsite inputs.
   - Read and compare a canary Kubernetes Secret.
   - Correct the false requirement for separately restored `encryption-config.json`.
   - Set explicit S3 retention and a policy for manual snapshots.

3. **Complete Stage 1 and correct the Stage 2 HA test.**
   - Add the third independent k3s server and pass the destructive failover milestone with owner approval.
   - Fix Ansible role/version/config convergence and record a real idempotency run.
   - Define Postgres placement across real failure domains or explicitly downgrade the Stage 2 claim to recovery,
     then test loss of the relevant failure domain.

## Safe Continuation Notes for Claude Code

- Treat this report as review evidence, not as a new ADR.
- Do not silently change ADR-018..021.
- Do not print or copy any live credentials while addressing findings.
- Any node shutdown, restore, credential rotation or deletion test requires owner approval.
- Before implementing fixes, update `CLAUDE.md` and `STATUS.md` to remove stale statements and establish file
  ownership if Codex and Claude will work concurrently.

