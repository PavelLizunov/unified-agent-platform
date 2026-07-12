# Hermes Task Recovery

Use this runbook for a Hermes pod/client interruption during repository work. It does not authorize a destructive
k3s restore; that remains owner-gated in `runbooks/restore-drill.md`.

## Checkpoint

Before failure injection or risky work:

1. Take an exact-name k3s snapshot and confirm its `s3://` R2 entry with the `uap-etcd-snapshot` skill.
2. Confirm the Hermes PV reclaim policy is `Retain`, recent backup Jobs are complete and `state.db` passes
   `PRAGMA integrity_check`.
3. Run a full Hermes backup and record its object name and size.
4. Use a unique build-1 worktree and marker path. Record the Hermes session id and current pod UID.

## Resume after a pod/client interruption

1. Make the task write a `PRE` marker, run a bounded long command, then write `POST`.
2. Interrupt the pod only after independently observing `PRE`.
3. Require the interrupted client to exit non-zero without a terminal success response.
4. Do not reuse or delete the worktree yet. Client cancellation does not cancel an already running remote process.
5. Check the remote process and markers independently. Wait for it to finish or terminate it deliberately.
6. Resume the same Hermes session with an inspect-only prompt. Do not rerun the original mutation.
7. Require one bounded read tool call, a terminal recovery result, and another `state.db` integrity check.

## Restore and dependency failure smokes

- Import the latest backup only into an isolated pod backed by `emptyDir`; never write the live PVC. Require every
  restored SQLite database, including `.codex/*.sqlite`, to pass `PRAGMA integrity_check`.
- Test model egress loss in an isolated pod with a label-scoped deny-all NetworkPolicy. Proxy environment variables
  are not an egress boundary for Codex app-server. Require timeout/failure and no assistant success response.
- Test build-1 loss in an isolated pod with a private `emptyDir` and a fake `ssh` executable that returns non-zero.
  Require one attempted tool call and the exact blocked terminal result; do not touch live build-1.
- Delete all isolated pods, Jobs and NetworkPolicies, then confirm the live pod is Ready and its database is healthy.

## Accepted M10 evidence (2026-07-12)

- Snapshot `uap-local-20260711-233801-uap-home-1-1783813081` was present locally and in R2.
- Backup `hermes-backup-20260711-233827.zip` imported 6,760 files; all five SQLite databases were healthy.
- Session `20260711_234054_8def86` survived a pod roll and resumed with
  `M10-RECOVERED-POST-PRESENT` without rerunning the remote mutation.
- Isolated model-egress and build-1 failures produced no false success; all temporary resources were removed.
