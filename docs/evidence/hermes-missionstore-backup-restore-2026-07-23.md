# Hermes MissionStore backup and restore evidence — 2026-07-23

## Verdict

**PASS for a consistent MissionStore snapshot, R2 upload and non-destructive restore into a disposable PVC.**
The latest real Hermes archive restored `state.db` and `missions-v1.sqlite3`; both passed SQLite
`PRAGMA quick_check`, and the restored MissionStore contained **1072 committed events**. The disposable Job,
pod and PVC were removed after verification.

This evidence does not claim a destructive replacement of the production PVC, restored login/session usability,
or recovery after loss of the R2 credential itself.

## Immutable implementation identity

The change was deliberately split into small protected-branch PRs:

| PR | Merge | Result |
|---|---|---|
| [#421](https://github.com/PavelLizunov/unified-agent-platform/pull/421) | `f58f5cebeda838b94232410a18774c60611817db` | Version parity, MissionStore online snapshot, archive validator and restore canary |
| [#422](https://github.com/PavelLizunov/unified-agent-platform/pull/422) | `6af6229f9663c9985b82d8ed489d578800556aa7` | Root `auth.json` is distinguished from nested regeneratable state |
| [#423](https://github.com/PavelLizunov/unified-agent-platform/pull/423) | `bb32654cc1515564523fda461bdaefedab7447a8` | Unique canary resources and explicit failed-Job polling |
| [#424](https://github.com/PavelLizunov/unified-agent-platform/pull/424) | `a7ec7f2196d35430715cfa1989a8a9fb957f5213` | Restore verifier matches the deployed root runtime identity |
| [#425](https://github.com/PavelLizunov/unified-agent-platform/pull/425) | `f3b68654e2c06702347fd2e24f804eca25f31c4f` | Immutable read-only SQLite verification for WAL-mode snapshots |

Every PR passed the required `static-checks`; PR #425 used Actions run
[`30026942507`](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/30026942507).
The local full gate returned `verify-local-ok`, and the focused Linux test returned `hermes-backup-ok`.

Flux subsequently reported both objects Ready at the exact final merge:

```text
GitRepository/uap-platform Ready=True
Kustomization/uap-platform Ready=True
revision=master@sha1:f3b68654e2c06702347fd2e24f804eca25f31c4f
```

The deployed backup dump image is the same pinned Hermes v0.18.0 digest as the gateway:

```text
nousresearch/hermes-agent@sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f
```

## Backup proof

The first manual job failed closed because the archive contained root `auth.json` and a nested file with the same
basename. PR #422 corrected the validator to use exact root paths rather than basename matching.

The successor job completed and uploaded:

```text
hermes-backup-20260723-163330.zip
hermes-backup-manifest-ok
```

Before upload, the validator:

1. creates a consistent `missions-v1.sqlite3` snapshot with `sqlite3.Connection.backup()`;
2. atomically replaces any raw MissionStore entry in the ZIP;
3. requires exact root `state.db`, `auth.json` and `missions-v1.sqlite3`;
4. checks both SQLite databases and requires the `mission_events` table;
5. rejects missing, corrupt or wrong-schema authoritative state.

The scheduled `hermes-agent-backup` CronJob remained enabled with schedule `0 3 * * *` and keep-7 retention.

## Disposable restore proof

The canary intentionally exposed two real restore assumptions before passing:

- a non-root verifier could not traverse the restored owner-only state, so the verifier now matches the deployed
  root gateway identity;
- ordinary SQLite read-only mode attempted WAL sidecar access on the read-only PVC, so the verifier now uses
  `mode=ro&immutable=1` for a quiescent restored snapshot.

The final canary created unique resources:

```text
persistentvolumeclaim/hermes-restore-canary-1784825131-505195
job.batch/hermes-restore-canary-1784825131-505195
```

It imported the latest R2 archive and returned:

```text
hermes-restore-canary-ok mission_events=1072
hermes-agent-restore-ok
```

The EXIT cleanup removed the exact Job, pod and PVC. A subsequent namespace query found no
`hermes-backup-manual-*` or `hermes-restore-canary-*` resources.

## Claim boundary

Proven:

- MissionStore is present as an authoritative root object in every accepted new archive;
- its archived copy is produced through the SQLite online-backup API rather than raw copying;
- the latest uploaded archive can be imported into fresh storage;
- restored Central and MissionStore SQLite files are readable and internally consistent;
- the canary is repeatable, uniquely named and self-cleaning.

Not proven by this drill:

- overwriting or reattaching the live production PVC;
- restored Telegram/Codex authentication and end-to-end owner interaction;
- recovery when both the PVC and its R2 credential are unavailable;
- confidentiality beyond the currently owner-accepted R2 credential and encryption boundary.
