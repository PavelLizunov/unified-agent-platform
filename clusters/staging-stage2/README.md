# Stage 2 scaffolding — REVIEW ONLY (do NOT apply yet)

These manifests prepare Stage 2 (Postgres HA via CloudNativePG + Garage S3). They are **intentionally outside the
Flux-watched path** (`./clusters/prod`) and carry **no `kustomization.yaml`**, so neither Flux nor `kubectl apply -k`
will deploy them by accident.

## Apply gate (BUILD-PLAN Stage 2)

Do not promote until **all** are true:

1. Stage 1 HA gate is green — a 3rd independent k3s server exists and the node-loss failover drill passed.
2. The Stage 2 honest-HA decision is recorded: with `<2` independent worker nodes this is **recovery-oriented
   single-node** state (process failover + offsite backup), NOT node-HA. See BUILD-PLAN Stage 2.
3. Real secrets exist as SOPS-encrypted `*.sops.yaml` under `clusters/prod/...` (NOT the placeholders here).
4. Versions re-validated (see below).

## Promote (when the gate is green)

- Move/copy the reviewed manifests into `clusters/prod/` (e.g. `clusters/prod/infra` for the operator/Garage,
  `clusters/prod/apps` for the `Cluster`), add them to the relevant `kustomization.yaml`, create the SOPS secrets,
  commit, and let Flux reconcile.

## Version pins (re-validate at promotion)

| Component | Pinned here | Validate |
|---|---|---|
| CloudNativePG Helm chart | `0.28.3` | chart **appVersion (operator) >= 1.29.1** (CVE-2026-44477 fix) |
| PostgreSQL image | `17.x` | current supported minor for the chosen operator |
| Garage | `v2.3.0` | current upstream stable; single-node has NO redundancy (offsite backup only) |

## Milestones (from BUILD-PLAN)

- Process/pod failover: delete the primary pod -> new primary in seconds (testable on the single server; NOT HA).
- Node/failure-domain failover: power off the whole primary node -> primary moves, data intact (REAL HA gate).
- Garage: upload/download an object + verify the offsite backup round-trips.
