# Hermes Agent v0.19.0 upgrade — deployed

Status: **DEPLOYED — PR #457 merged; Flux and the live gateway verified.**
Date: 2026-07-24.

Live re-check on 2026-07-25:

- Flux source and `uap-platform` Kustomization were Ready at `master@sha1:2ee6134d`;
- the gateway image was pinned to
  `sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a`;
- `hermes --version` returned `Hermes Agent v0.19.0 (2026.7.20) · upstream 3ef6bbd2`;
- the pod was Ready with zero restarts;
- later Telegram topic-routing/final-delivery probes and the authenticated source-preflight probe exercised the
  upgraded gateway/execution boundary successfully.

Build-1 remains a separately pinned v0.18 execution plane by design. This completed central upgrade does not claim
that build-1 was upgraded to v0.19.

## Verified provenance

- **Upstream:** official stable GitHub release "Hermes Agent v0.19.0", tag
  `v2026.7.20`, peeled commit `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`,
  `prerelease=false`. Owner-confirmed.
- **Image digest:** independently verified from Docker Hub registry HEAD:
  manifest-list `sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a`,
  amd64 child `sha256:a6ce64e2038867885c2c90f6602425e6e70293d5e6d952a0e603a99265e01c40`.
- **Pre-upgrade rollback pin:** v0.18.0, tag `v2026.7.1`, commit
  `7c1a029553d87c43ecff8a3821336bc95872213b`, digest
  `sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f`.
  Live rollback target until v0.19 deployment completes.

## Pin unit (atomic)

The fail-closed initContainer fingerprints the running image at boot. These
four parts describe the same upstream source and move atomically:

1. Image digest in manifests (`f7b350…`).
2. Mission overlay `UPSTREAM_COMMIT` (`3ef6bbd…`).
3. initContainer `--source-commit 3ef6bbd…`.
4. Overlay `FILES`/`PATCHED_FILES` fingerprint tables (7 files, 0/7 drift).

Build-1 runtime is pinned separately at v0.18 (`BUILD1_UPSTREAM_COMMIT`,
`BUILD1_FILES`, `BUILD1_PATCHED_FILES`) and does not depend on the central
pin.

## Runtime-compat patches (ADR-027)

| Patch | v0.19 status |
|---|---|
| exec_command exit-code (display.py, tool_guardrails.py) | retained, anchor matches |
| guardrail injection (codex_runtime.py) | retained, re-anchored to `make_codex_app_server_event_bridge` |
| guardrail halt + terminal response (codex_runtime.py) | retained, terminal check uses `turn.final_text` |
| userMessage echo suppression (codex_event_projector.py) | retained, anchor matches |
| partial/completed exit-code (cli.py) | retained, re-anchored to v0.19 context |
| web dashboard resume (web_index.js) | retained, rebased: v0.19 emits `stored_session_id` but does NOT update `?resume=` natively |
| SSO password bypass (middleware.py) | **deleted** — native in v0.19 (`supports_password`) |
| session_id in info dict (server.py) | **deleted** — native in v0.19 (`stored_session_id`) |

## Changed files

- `clusters/prod/infra/hermes-agent.yaml` — 2× image digest, config-rev, `--source-commit`, web asset cp + volumeMount
- `clusters/prod/infra/hermes-agent-backup.yaml` — 1× image digest
- `clusters/prod/infra/hermes-agent-config.yaml` — runtime-compat.py rebased (6 patches kept, 2 deleted)
- `clusters/prod/infra/hermes-mission-runtime.yaml` — re-rendered from rebased overlay
- `tools/hermes-mission/apply_overlay.py` — UPSTREAM_COMMIT, FILES, PATCHED_FILES, BUILD1_* tables, async/route-table fragments
- `tools/hermes-mission/test_overlay.py` — v0.19 route-table/startup-guard/native-patch regressions, build1 regression
- `tools/hermes-mission/v019_readiness.py` — CURRENT_PIN v0.19, verified digest comments
- `tests/static/test_hermes_v019_pin_guard.py` — ACCEPTED_PINS += v0.19.0, restore script scan, label/tag validation
- `tests/static/test_hermes_runtime_compat.py` — v0.19 fixtures, executable post-turn behavioral tests
- `tests/static/test_hermes_mission_deployment.py` — source-commit, config-rev, web volumeMount
- `tests/fixtures/hermes-v019-readiness.json` — regenerated from probe (v0.19 baseline, 0/7 drift)
- `tests/ops/check-hermes-agent-restore.sh` — image digest
- `runbooks/hermes-agent-dr.md` — v0.19 expected runtime, v0.18 labelled rollback
- `runbooks/vibe-coding-acceptance.md` — v0.19 expected runtime
- `docs/hermes-v019-upgrade.md` — this document

## Rollout procedure

**Precondition:** no active missions or pending work on the agent.

1. **Pre-upgrade backup:** create a fresh `hermes backup` on the live v0.18
   pod. Ship to R2. Prove a disposable v0.18 restore from this archive
   (uniquely named PVC, verify SQLite databases). This archive is the
   rollback artifact.
   For a v0.18 disposable restore proof from this branch:
   `HERMES_RESTORE_MODE=v0.18-rollback tests/ops/check-hermes-agent-restore.sh`
2. Merge the unlock PR (green `static-checks` incl. pin guard + overlay).
   Flux reconciles `clusters/prod`.
3. Watch rollout: `kubectl -n uap-system rollout status deploy/hermes-agent`.
   initContainer must log `overlay applied` and runtime-compat must not abort.
4. Smoke invariants: Telegram text intake → mission; `/projects`, `/mission`,
   `/status`; per-topic media; voice STT; Workspace projection;
   `hermes --version` = v0.19.0.
5. **Post-upgrade backup:** trigger a v0.19 backup Job. Verify zip + R2 ship.
   Prove a disposable v0.19 restore separately.

## Rollback

**Do NOT claim direct downgrade over a v0.19-mutated PVC.** If v0.19 ran
Kanban migrations forward, the v0.18 overlay may not open the DB cleanly.

Safe rollback (Flux-aware):
1. **Suspend Flux** so it does not fight the scale-down:
   `flux suspend kustomization uap-platform -n flux-system`.
   Verify: `flux get kustomization uap-platform -n flux-system` shows `Suspended: True`.
2. **Suspend the backup CronJob** so it cannot schedule a NEW backup against a
   half-rolled-back / downgraded PVC with a mismatched image:
   `kubectl -n uap-system patch cronjob hermes-agent-backup -p '{"spec":{"suspend":true}}'`.
   Verify: `kubectl -n uap-system get cronjob hermes-agent-backup -o jsonpath='{.spec.suspend}{"\n"}'` → `true`.
   Suspending the CronJob stops NEW Jobs only; an already-running owned Job still
   co-mounts the RWO PVC as a second reader — drain it in step 3 before touching
   the PVC.
3. **Drain the active backup Job and prove quiescence.** Build `active_jobs` from
   the Jobs OWNED by `CronJob/hermes-agent-backup` (exact `ownerReference` query —
   never a name prefix) that are CURRENTLY ACTIVE (`.status.active > 0`).
   Historical completed/failed Jobs are deliberately EXCLUDED so they are never
   waited on or deleted:
   ```bash
   active_jobs=$(kubectl -n uap-system get jobs -o json | jq -r '
     .items[]
     | select(.metadata.ownerReferences[]?
         | select(.kind=="CronJob" and .name=="hermes-agent-backup"))
     | select((.status.active // 0) > 0)
     | .metadata.name')
   ```
   For each active Job, give it a bounded chance to finish within the CronJob's
   deadline (`activeDeadlineSeconds: 1800`); then — whether it completed or timed
   out — delete THAT exact previously-active Job with `--wait=true` so its owned
   pod is gone before the PVC is touched. On timeout, delete immediately after the
   failed wait. Historical inactive Jobs are never touched. (If `active_jobs` is
   empty, this loop is a no-op.)
   ```bash
   for j in $active_jobs; do
     kubectl -n uap-system wait --for=condition=complete job/"$j" --timeout=1800s || true
     kubectl -n uap-system delete job "$j" --wait=true
   done
   ```
   Then prove quiescence before any scale-down / PVC restore:
   ```bash
   # (a) no ACTIVE Job owned by CronJob/hermes-agent-backup -> true
   kubectl -n uap-system get jobs -o json | jq -e '
     [ .items[]
       | select(.metadata.ownerReferences[]?
           | select(.kind=="CronJob" and .name=="hermes-agent-backup"))
       | select((.status.active // 0) > 0) ] | length == 0'
   # (b) for each previously-active Job, no pod whose EXACT ownerReference is
   #     Job/<that name> (no name prefix; no scan of historical Job pods).
   #     If active_jobs was empty, this loop is a no-op. -> true
   for j in $active_jobs; do
     kubectl -n uap-system get pods -o json | jq -e --arg job "$j" '
       [ .items[]
         | select(.metadata.ownerReferences[]?
             | select(.kind=="Job" and .name == $job)) ] | length == 0'
   done
   ```
4. **Scale down:** `kubectl -n uap-system scale deploy/hermes-agent --replicas=0`.
   Wait for pod termination: `kubectl -n uap-system wait pod -l app=hermes-agent --for=delete --timeout=120s`.
5. **Revert the unlock PR** in Git. This restores the v0.18 digest,
   UPSTREAM_COMMIT, FILES and config-rev, **and MUST also set `spec.suspend: true`
   declaratively** in `clusters/prod/infra/hermes-agent-backup.yaml`, so the
   backup stays suspended across Flux reconciliation (an imperative patch alone
   would be reverted the moment Flux resumes). Do NOT resume Flux yet.
6. **Restore** the recorded pre-upgrade v0.18 backup archive to clean PVC state
   (the gateway is down, so it cannot write new state). **Production restore is
   destructive and owner-gated** (see `runbooks/hermes-agent-dr.md`). Do NOT claim
   in-place downgrade over a v0.19-mutated PVC is safe. Any throwaway import pod
   used to touch the downgraded PVC MUST be pinned to the exact v0.18 digest
   `nousresearch/hermes-agent@sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f`
   BEFORE it mounts the PVC — never run `hermes import` against the downgraded
   PVC with a v0.19 (or tag-only) image.
7. **Resume Flux only after the rollback PR is merged:**
   `flux resume kustomization uap-platform -n flux-system`. Flux reconciles the
   reverted v0.18 manifests — the backup CronJob stays suspended **declaratively**
   — and scales the pod back up. Verify the CronJob is still suspended
   post-reconcile:
   `kubectl -n uap-system get cronjob hermes-agent-backup -o jsonpath='{.spec.suspend}{"\n"}'` → `true`.
8. Verify v0.18 smoke invariants **while the backup remains declaratively
   suspended**.
9. **Re-enable the backup CronJob through a small follow-up Git PR** (remove
   `spec.suspend` or set it `false` in `clusters/prod/infra/hermes-agent-backup.yaml`),
   merge it, let Flux reconcile, and verify
   `kubectl -n uap-system get cronjob hermes-agent-backup -o jsonpath='{.spec.suspend}{"\n"}'` → `false`.
   Do NOT re-enable with an imperative `kubectl patch` — Flux would revert it.
