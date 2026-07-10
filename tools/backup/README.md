# build-1 offsite backup

Closes the build-1 data-loss gap. `uap-build-1` (100.85.56.31) is **not** a k3s node
and **not** in GitOps, so the etcd→R2 snapshots and the in-cluster
`hermes-agent-backup` CronJob do not cover its earned state. The one irreplaceable
thing there is the **knowledge system SQLite registry** (`~/knowledge/knowledge.db`):
canonical records + documents + append-only audit + the sqlite-vec index. This ships a
consistent nightly snapshot (plus the small node-local config) to Cloudflare R2.

See also: `runbooks/knowledge-system.md` (what build-1 holds) and
`clusters/prod/infra/hermes-agent-backup.yaml` (the in-cluster pattern this mirrors —
same R2 bucket `uap-k3s-snapshots`, same retention style).

## What it backs up

| Path (on build-1) | Why | In backup? |
|---|---|---|
| `~/knowledge/knowledge.db` | source of truth (WAL) | **yes** — via `.backup`, WAL-safe |
| `~/.config/ai-search.env` | web-search provider keys (owner-supplied) | yes, if present |
| `~/knowledge/bin/` | deploy glue not in git (`nightly.sh`, `weekly.sh`, `drive-sync.sh`) | yes |
| `~/knowledge/.venv`, `models/`, `drive-mirror/`, `logs/`, `reports/` | regeneratable (`uv sync`, re-download, `reindex`, re-sync) | **no**, by design |
| `~/knowledge/bin/knowledge.py` | in git (`tools/knowledge/knowledge.py`) | incidental (whole `bin/`) |

The archive can contain `ai-search.env` (provider keys) — same exposure class as the
hermes-agent R2 backup, which already ships plaintext auth to this bucket. Harden with a
**bucket-scoped R2 key** (per `REVIEW-CODEX.md`). The archive is written `chmod 600`.

## Install (on build-1, run once)

```sh
# 1) deploy the script next to the other knowledge jobs
install -m 755 tools/backup/build1-knowledge-backup.sh ~/knowledge/bin/build1-knowledge-backup.sh

# 2) ensure build-1's rclone has an R2 remote named `r2` (this is the ONE operator input).
#    Copy the [r2] stanza from ops-1 (100.82.241.121:~/.config/rclone/rclone.conf), or add a
#    bucket-scoped key:  rclone config   ->  new remote `r2`, type s3, provider Cloudflare.
rclone lsf r2:uap-k3s-snapshots/ >/dev/null   # must succeed before enabling the timer

# 3) dry-run once, confirm an archive lands in R2 under knowledge/
R2_REMOTE=r2 ~/knowledge/bin/build1-knowledge-backup.sh

# 4) install the systemd timer (root)
sudo install -m 644 tools/backup/build1-knowledge-backup.service /etc/systemd/system/
sudo install -m 644 tools/backup/build1-knowledge-backup.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now build1-knowledge-backup.timer
systemctl list-timers build1-knowledge-backup.timer
```

If `sqlite3` is missing: `sudo apt-get install -y sqlite3`.

## Restore

```sh
# 1) list + pull the dated archive from R2
rclone lsf r2:uap-k3s-snapshots/knowledge/
rclone copy r2:uap-k3s-snapshots/knowledge/build1-knowledge-YYYYMMDD.tar.gz /tmp/
mkdir -p /tmp/kn-restore && tar -xzf /tmp/build1-knowledge-YYYYMMDD.tar.gz -C /tmp/kn-restore
ls /tmp/kn-restore            # knowledge-YYYYMMDD.db, ai-search.env, knowledge-bin/

# 2) VERIFY before swapping in. If integrity_check reports a missing vec0 module, load the
#    extension the same way datasette/knowledge.py does, then re-check.
sqlite3 /tmp/kn-restore/knowledge-YYYYMMDD.db 'PRAGMA integrity_check;'   # expect: ok
sqlite3 /tmp/kn-restore/knowledge-YYYYMMDD.db 'SELECT count(*) FROM records;'

# 3) swap in (stop readers first so nothing holds a WAL handle)
sudo systemctl stop knowledge-web.service          # datasette read-only viewer
cp ~/knowledge/knowledge.db ~/knowledge/knowledge.db.pre-restore   # keep the current one
cp /tmp/kn-restore/knowledge-YYYYMMDD.db ~/knowledge/knowledge.db
# restore config only if it was lost:
#   cp /tmp/kn-restore/ai-search.env ~/.config/ai-search.env && chmod 600 ~/.config/ai-search.env
sudo systemctl start knowledge-web.service
knowledge stats                                     # sanity: record/document counts look right
```

The restored `.db` already contains the sqlite-vec index — no `reindex` needed. Reindex
only if you changed the embedding model.

## ops-1 local-models-router config (related gap)

The Hermes brain router on `uap-ops-1` (systemd `local-model-router`, endpoint
`http://100.82.241.121:8090/v1`) is the other node-local, not-in-GitOps config. Its code
(`tools/local-models/route.py`) **is** in git; only the systemd unit is node-local. Capture
it out-of-band — it is tiny and holds no earned state:

```sh
# on ops-1
sudo cp /etc/systemd/system/local-model-router.service ~/local-model-router.service.bak
rclone copy ~/local-model-router.service.bak r2:uap-k3s-snapshots/ops1-config/
```

If it grows an env/config file with backend URLs or a `ROUTER_KEY`, add that path here (a
`ROUTER_KEY` is a secret — SOPS it in git, do not ship a plaintext key without a
bucket-scoped R2 key). See `runbooks/offsite-backups.md`.
