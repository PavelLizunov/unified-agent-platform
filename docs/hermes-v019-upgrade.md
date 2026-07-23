# Hermes Agent v0.19 upgrade — controlled preparation (BLOCKED, by design)

Status: **BLOCKED — deterministic blocker in place.** Production pin is unchanged.
Date: 2026-07-24.

This document records a controlled attempt to prepare the NousResearch
`hermes-agent` v0.18.0 → v0.19 upgrade. The exact v0.19 artifact/digest could not
be cryptographically verified, so per the task contract the production pin was
**not** advanced; instead a deterministic blocker and verified compatibility
evidence were added. No live cluster mutation, deploy, commit, push or PR.

## Why the upgrade is blocked (verified facts)

1. **Upstream publishes DATE tags only.** `git ls-remote --tags
   https://github.com/NousResearch/hermes-agent` (cryptographic tag→commit) shows
   `v2026.7.1`, `v2026.7.7`, `v2026.7.7.2`, `v2026.7.20`, … There is **no `v0.19`
   tag** and **no documented `v0.19 ↔ date-tag` mapping** anywhere in the repo
   (`STATUS.md`, `DECISIONS.md`, `docs/`, `runbooks/` were searched). "v0.19" is
   only this repo's internal next-version label.
2. **Current pin source verified end-to-end; image digest is an accepted
   historical production pin.** Internal `v0.18.0` == upstream tag
   `v2026.7.1` == source commit `7c1a029553d87c43ecff8a3821336bc95872213b` (the
   overlay's `UPSTREAM_COMMIT`). The tag->commit mapping is cryptographically
   verified via `git ls-remote --tags`. The readiness probe re-fetched that
   commit and confirmed **all 7 fingerprinted source files match the overlay
   `FILES` table byte for byte**
   (`tests/fixtures/hermes-v019-readiness.json`, `current_pin_baseline`).
   Image digest pinned in manifests:
   `sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f`
   (`hermes-agent.yaml` bootstrap + gateway, `hermes-agent-backup.yaml`).
   **This digest is an accepted historical production pin** recorded from the
   manifest (PR #35 lineage); it was NOT independently re-pulled or
   signature-verified. Any new v0.19 digest requires independent
   registry/signature verification before it may be accepted.
3. **The image manifest digest cannot be cryptographically verified from this
   environment.** Pinning `@sha256:` requires the genuine published digest; that
   needs pulling the image / verifying a publisher signature, which is not
   possible on the workstation and is not a live-cluster operation we may do here.
   Copying a digest string from a web page is **not** verification — and inventing
   one is forbidden by the task and by ADR-027's fail-closed model.

## The pin is an atomic unit (why a partial change breaks production)

The fail-closed initContainer (`hermes-agent.yaml`, ADR-027/030) fingerprints the
**running image's source** at boot and CrashLoops the pod on any mismatch. These
four parts MUST describe the same upstream source:

- image digest in the manifests (`b6c019…`),
- mission overlay `UPSTREAM_COMMIT` (`7c1a029…`),
- initContainer `--source-commit 7c1a029…`,
- mission overlay `FILES` / `PATCHED_FILES` fingerprint tables.

Advancing the image to a v0.19 candidate **without** rebasing+verifying the
overlay (or vice versa) makes the boot fingerprint mismatch → CrashLoop. So the
unit moves atomically or not at all.

## Verified v0.19 rebase scope (drift evidence)

`tools/hermes-mission/v019_readiness.py` measured how far each candidate "next"
tag has drifted from the mission overlay's fingerprint table (a drifted file means
the overlay fails closed and MUST be rebased — new `FILES`/`PATCHED_FILES` plus
re-verified `replace()` fragments):

| Candidate tag | Commit | Drifted files | Unchanged (fragment still applies byte-for-byte) |
|---|---|---|---|
| v2026.7.7   | `f9eca7e…` | 5/7 | `hermes_cli/kanban.py`, `hermes_cli/kanban_db.py` |
| v2026.7.7.2 | `9de9c25…` | 5/7 | `hermes_cli/kanban.py`, `hermes_cli/kanban_db.py` |
| v2026.7.20  | `3ef6bbd…` | 7/7 | — (full overlay rebase required) |

Drifted set for v2026.7.7/.2: `gateway/platforms/api_server.py`, `gateway/run.py`,
`hermes_cli/commands.py`, `hermes_cli/main.py`, `plugins/platforms/telegram/adapter.py`.

## Native replacements vs retained overlays

**No overlay code was deleted.** ADR-027/029 allow removing an overlay insertion
only once upstream is *proven* to provide equivalent behavior; nothing is proven
yet. The drift table is the starting point, not proof:

- **Retained (all of them, for now):** every ADR-027 runtime-compat insertion
  (8 files) and every ADR-030 mission insertion (7 files + `uap_missions.py` +
  `uap_media.py`). The behavioral guarantees they enforce are listed in
  `tools/hermes-mission/test_overlay.py` (~150 exact assertions: Central
  MissionStore, ordinary intake, owner gates, per-topic media allowlist,
  Telegram/Workspace projection, STT/media, atomic Kanban GC/idempotency/permissions).
- **Native-replacement candidates (UNPROVEN — do not act without proof):** for
  v2026.7.7/.2 only, `kanban.py`/`kanban_db.py` are byte-identical to v0.18.0, so
  our fragments there still apply unchanged; whether v0.19 *natively* adopted any
  of our patches (e.g. atomic idle GC, owner-only DB permissions, active
  idempotency uniqueness) requires reading the v0.19 source and a targeted
  equivalence test per insertion before any deletion.

## Scope note: the Workspace overlay is a separate pin

`tools/hermes-workspace/apply_overlay.py` (ADR-029 Central Workspace backend) is
pinned to a **different** upstream commit `c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c`
(not a hermes-agent release tag) and is rendered into its own ConfigMap. It is
**not** part of the hermes-agent gateway image upgrade and is untouched here, but
a real v0.19 change must keep it consistent (it projects the same central
missions). The ADR-027 runtime-compat overlay (`hermes-agent-config.yaml`) is
fragment-based (fails closed when a fragment is absent) rather than commit-pinned,
so its v0.19 rebase is "re-verify each fragment against the new source."

## What "unlock v0.19" requires (procedure to make the guard pass)

The deterministic blocker is `tests/static/test_hermes_v019_pin_guard.py` (runs in
CI `static-checks`). It passes only while production sits on a pin listed in its
`ACCEPTED_PINS` (currently just v0.18.0) with a fully consistent unit. All
load-bearing checks use explicit `raise` (not `assert`) so they survive
`python -O`. To unlock a
real v0.19, a future PR must:

1. **Owner decision:** confirm which upstream date tag is "v0.19" (new provider/
   version/architecture-boundary change → owner-gated per ADR-031/AGENTS.md).
2. **Verify the new image digest independently** (pull the exact tag from the
   registry, record the `@sha256:` manifest-list digest; verify publisher
   signature if available).  This is the step the current v0.18.0 digest did
   NOT go through in this guard -- it is an accepted historical production pin.
3. **Rebase the mission overlay** against the chosen source commit:
   - set `UPSTREAM_COMMIT` and initContainer `--source-commit` to the new commit;
   - recompute `FILES` from the pristine source and `PATCHED_FILES` via
     `apply_overlay.py <checkout> --print-patched-hashes`;
   - re-verify every `replace()` fragment still anchors (re-run
     `tools/hermes-mission/test_overlay.py` against the new commit);
   - delete an insertion only with a per-insertion native-equivalence proof.
4. **Re-verify the ADR-027 runtime-compat fragments** against the new source
   (`tests/static/test_hermes_runtime_compat.py` + manual fragment review).
5. **Refresh the readiness fixture**
   (`python tools/hermes-mission/v019_readiness.py --write-fixture`).
6. **Add the verified entry to `ACCEPTED_PINS`** in the guard (digest +
   source_commit). The guard then passes only if the whole unit is consistent.
7. Bump `hermes-agent/config-rev` to roll the pod; run the canary below.

## Live canary steps (only after the guard passes and a PR merges)

1. Merge the unlock PR (green `static-checks` incl. the pin guard + overlay
   idempotence). Flux reconciles `clusters/prod`.
2. Watch the rollout: `kubectl -n uap-system rollout status deploy/hermes-agent`.
   The initContainer must log `overlay applied`/`overlay already applied` (mission)
   and the runtime-compat patch must not abort. A fingerprint mismatch CrashLoops
   visibly — that is the fail-closed signal, not a silent degrade.
3. Smoke the invariants on the live pod (owner Telegram + Workspace):
   ordinary text intake → mission created; `/projects`, `/mission`, `/status`
   owner commands; per-topic media routing; voice-note STT; Workspace session
   projection of the same central mission; OpenAI-only Luna/Sol/Terra route.
4. Confirm `hermes --version`/`codex --version`/`claude --version` match the pins.

## Rollback steps

1. Revert the unlock PR (restores digest `b6c019…`, `UPSTREAM_COMMIT 7c1a029…`,
   the v0.18.0 `FILES`/`PATCHED_FILES`, and `config-rev`). Flux reconciles back.
2. `kubectl -n uap-system rollout status deploy/hermes-agent`; the Recreate
   strategy brings the single pod back on the v0.18.0 image. State lives on the
   `hermes-agent-data` PVC and is untouched by the image change.
3. If a Kanban schema migration ran forward under v0.19, verify the v0.18.0 overlay
   still opens the DB (the overlay migrations are additive/idempotent); restore
   from the R2 backup (`hermes-agent-backup`) only if needed — restore is
   owner-gated and destructive.

## Changed files in this preparation

- `tools/hermes-mission/v019_readiness.py` — NEW read-only, skip-friendly probe
  (verifies current pin, measures candidate drift; not auto-run in CI).
- `tests/fixtures/hermes-v019-readiness.json` — NEW verified drift fixture.
- `tests/static/test_hermes_v019_pin_guard.py` — NEW deterministic blocker guard
  (CI `static-checks`).  All load-bearing checks use explicit `raise` (not
  `assert`) so they survive `python -O`.  Includes hermetic negative regression
  tests (dependency-injected, never touch production files) proving failure for:
  unaccepted digest, multiple/mismatched digests, UPSTREAM_COMMIT mismatch,
  `--source-commit` mismatch, fixture field mismatches, missing/drifted baseline,
  and broadened gitleaks allowlist.
- `docs/hermes-v019-upgrade.md` — this document.

Production manifests, the overlay source (`apply_overlay.py`), `FILES`/
`PATCHED_FILES`, `UPSTREAM_COMMIT`, `--source-commit` and the image digest are
**unchanged**.
