# hermes-agent DR: PVC backup + restore (PR B)

> The hermes-agent state PVC has no other safety net. This runbook covers the daily R2 backup
> and how to restore after a node/disk loss. Companion: `hermes-agent-codex-brain.md` (deploy +
> config ownership).

## Why this exists (the gap)

`PVC hermes-agent-data` is **`local-path`**, hostPath-pinned to **uap-home-2**, and is **NOT** in the
etcd->R2 snapshots (those capture k8s API objects + the PV *definition*, never the hostPath bytes).
So a uap-home-2 disk loss would lose **all earned state**: `state.db` (sessions/messages), the **Codex
brain** (`.codex/{memories_1,goals_1,state_5}.sqlite`), `kanban.db`, `cron/jobs.json`, agent-enriched
`memories/USER.md`, `SOUL.md`, `channel_directory.json`, the authoritative Central mission log
`missions-v1.sqlite3`, and the live `auth.json`. The bulk of the PVC
(~400M of `.local`/codex logs/caches) is regeneratable; the irreplaceable state is small.

## What runs

- **CronJob `hermes-agent-backup`** (`clusters/prod/infra/hermes-agent-backup.yaml`) — daily 03:00,
  pinned to uap-home-2 (it co-mounts the RWO PVC as a second reader). It runs a **FULL** `hermes backup`
  (NOT `--quick` — `--quick` omits `.codex/`, the Codex brain) into an emptyDir, then `rclone copy`s the
  zip to **`r2:uap-k3s-snapshots/hermes-agent-backup/`**. Retention: keep the **most recent 7**.
- **Secret `hermes-agent-backup-r2`** (SOPS) — the `[r2]` rclone remote (reused from the existing R2
  access; same bucket as the etcd snapshots, distinct folder).
- The backup is a **consistent** snapshot. `hermes backup` v0.18 uses `sqlite3.backup()` for `.db` files,
  but treats the UAP `missions-v1.sqlite3` as a normal file. Before upload, the repo-owned validator
  creates a separate `sqlite3.backup()` snapshot and atomically replaces that raw ZIP entry. The live PVC
  is never modified. FULL zip is ~40M today (it also sweeps in regeneratable `node_modules`/logs).
- **Completeness is enforced** (this was a silent gap — the old check only verified one `.codex/*.sqlite`):
  a manifest check **fails** the job on an empty/corrupt zip or a missing **hard-required** file
  (`state.db`, `missions-v1.sqlite3`, `auth.json` — always-present, owned by uid 10000). Both required
  SQLite databases must pass `PRAGMA quick_check`; the MissionStore snapshot must contain
  `mission_events`. NOTE `hermes backup` runs as its service uid **10000** internally (even though the
  dump container is root), so a few **root-owned, regeneratable** files (claude global config,
  `.codex/config.toml` seeded from the ConfigMap, stray demo session logs) are **skipped with a WARNING,
  not a failure** — failing on those would leave **no backup**, worse than an incomplete one.

The upload goes **direct to Cloudflare R2** (the CronJob sets no `HTTPS_PROXY`), so it is **independent of
the LLM egress proxy** — backups keep working even when the German VLESS exit is down.

## Pinned runtime (verify after a roll)

The hermes-agent image, the backup images, and the Codex/Claude CLIs are pinned (by digest / version)
so the deployed worker matches the self-tested one. After a `hermes-agent` roll, confirm the runtime:

```bash
kubectl -n uap-system get deploy hermes-agent -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
# -> nousresearch/hermes-agent@sha256:b6c01922...   (v0.18.0)
POD=$(kubectl -n uap-system get pods -l app=hermes-agent -o name | grep -v backup | head -1)
kubectl -n uap-system exec "$POD" -c gateway -- sh -lc \
  '/opt/hermes/.venv/bin/hermes --version; /opt/data/.local/bin/codex --version; /opt/data/.local/bin/claude --version'
# expected: Hermes Agent v0.18.0 ; codex-cli 0.142.0 ; 2.1.193 (Claude Code)

# The backup dump image must match the gateway image exactly:
kubectl -n uap-system get cronjob hermes-agent-backup \
  -o jsonpath='{.spec.jobTemplate.spec.template.spec.initContainers[?(@.name=="dump")].image}{"\n"}'
# -> the same b6c01922... digest
```

The CLIs are seed-if-absent on the PVC, so bumping the pinned `npm i -g ...@version` in
`clusters/prod/infra/hermes-agent.yaml` only takes effect on a fresh PVC (or after deleting the old
binary). Bump deliberately and re-verify here.

## PV reclaim policy (run once)

local-path PVs default to `reclaimPolicy: Delete`, so an accidental `PVC` delete drops the bytes. Flip the
**existing** PV to `Retain` (it is a dynamically-provisioned PV with a generated name, not in Git, so this
is an imperative one-time action):

```bash
PV=$(kubectl -n uap-system get pvc hermes-agent-data -o jsonpath='{.spec.volumeName}')
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'   # -> Retain
```

With `Retain`, deleting the PVC leaves the PV `Released` (data intact on disk). To reuse it, clear
`spec.claimRef` on the PV and re-create the PVC, or provision a fresh PVC and restore from R2 (below).

Because this is live (not declarative) state, a **re-created PVC / restore / node reschedule can silently
regress to `Delete`**. Guard against that with the live-smoke check (not in CI — needs cluster access):

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\ops\check-pv-reclaim.ps1 -Require   # -> pv-reclaim-ok
```

It is also wired into `tests/verify-local.ps1 -IncludeOps -Require`. Re-run it (and re-patch above) after
any PVC re-create or restore.

## Verify the backup (manual run)

```bash
kubectl -n uap-system create job --from=cronjob/hermes-agent-backup hermes-backup-manual
kubectl -n uap-system wait --for=condition=complete job/hermes-backup-manual --timeout=600s
kubectl -n uap-system logs job/hermes-backup-manual -c dump | grep hermes-backup-manifest-ok
kubectl -n uap-system logs job/hermes-backup-manual -c ship | tail
# objects now in R2:
rclone --config <r2.conf> lsf r2:uap-k3s-snapshots/hermes-agent-backup/    # from ops-1, or exec the ship container
kubectl -n uap-system delete job hermes-backup-manual
```

## Prove restore on a disposable PVC

Run the repo-owned canary from a host with the production `kubectl` context:

```bash
sh tests/ops/check-hermes-agent-restore.sh
# -> hermes-restore-canary-ok mission_events=<count>
# -> hermes-agent-restore-ok
```

The script pulls the latest archive with the existing in-cluster R2 Secret, imports it with the same
v0.18 image into a uniquely named `local-path` PVC, verifies both SQLite databases and reads the restored
`mission_events` table. Its `trap` removes only the uniquely named Job and disposable PVC. It never mounts
or mutates `hermes-agent-data`, never prints credentials or mission contents, and is safe to repeat.

## Restore (after node/disk loss)

1. Bring up a fresh `hermes-agent-data` PVC (GitOps re-creates it on the surviving/replacement node; if
   you replaced uap-home-2, re-pin the Deployment/PVC nodeSelector to the new hostname).
2. Pull the latest zip from R2 onto the new PVC and import it **before** the gateway writes new state:
   ```bash
   # exec a shell in the (initContainer-only / scaled-to-0) context, or a throwaway pod mounting the PVC
   rclone --config <r2.conf> copy r2:uap-k3s-snapshots/hermes-agent-backup/<latest>.zip /opt/data/restore/
   env HOME=/opt/data hermes import /opt/data/restore/<latest>.zip --force
   ```
   `hermes import` restores config, sessions (`state.db`), Central missions
   (`missions-v1.sqlite3`), the Codex brain (`.codex/*.sqlite`), kanban, cron, and memories.
3. **Re-auth Codex.** The `auth.json` in the zip carries a single-use refresh token that is almost
   certainly stale by restore time (hermes refreshes it in place between backups). If the brain 401s,
   re-seed `codex-auth` (see `hermes-agent-codex-brain.md` -> "Create / rotate the codex-auth SOPS
   secret") and roll the pod.
4. GitOps re-seeds the **managed** config (brain overlay `/etc/hermes/config.yaml`, proxy/allowlist
   `/etc/hermes/.env`) and the seed-if-absent files automatically — those need no restore.

## Hardening follow-ups

- **R2 credential scope is accepted as-is.** The backup reuses the same R2 credential as etcd snapshots. Owner
  decided on 2026-07-12 not to rotate or rescope it; do not change this without a new owner decision.
- **Client-side encryption.** The zip contains plaintext `auth.json` + `.env` (Codex OAuth + Telegram
  token) — same exposure class as the unencrypted etcd snapshots already in this bucket. R2 is private +
  encrypted-at-rest, but for defense-in-depth add an rclone `crypt` remote or age-encrypt before upload
  (mirroring `~/ops-backup/backup.sh`'s `.age` step). Restore then decrypts before `hermes import`.
