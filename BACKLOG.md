# Backlog

Tracked items that are **not** done yet, split by who must act. Reality-synced against `master` on
2026-07-12. Done items live in `STATUS.md`, not here.

## Owner action required (blocks nothing else from continuing)

| Ref | Item | Why it needs the owner | Unblocks |
|---|---|---|---|
| #2 | **Independent off-homelab age-key escrow** + verify a decrypt with it (keystone DR) | Owner must place the master key in a vault outside the Proxmox homelab | Homelab-loss recovery of age-encrypted DR material |
| — | Retrieve the new Vaultwarden admin token from `~/vaultwarden/admin-token.NEW.txt` on ops-1, move to a password manager, then delete the file | Owner-only credential | — |
| — | (optional) Revoke the old "GitHub CLI" OAuth grant in GitHub settings | Owner GitHub account | full invalidation of the token already removed from ops-1 |

## Agent-doable, but needs an owner "go" or a careful window

| Ref | Item | Note |
|---|---|---|
| #11 | **Tailnet-only host firewall** (restrict 6443/10250/8472 off the LAN) | Firewall changes on the single control-plane node carry lockout risk. Do in a supervised window with a timed auto-rollback, not unattended. |

## Notes

- Stage 2 (`Postgres HA + Garage`) manifests may be **prepared and reviewed** now (review-only scaffolding), but
  must NOT be applied until the Stage 1 HA gate is green — see `BUILD-PLAN.md` Stage 2 and `clusters/staging-stage2/`.
- The Codex subscription brain is live again as of 2026-07-11 (#119); the local Qwen/Ornith router remains the
  documented fallback. No model credential currently blocks the vibe-coding pilot.
- Owner decision 2026-07-12: keep the current R2 credential scope and lifecycle unchanged. Do not rotate or alter
  R2 policy without a new owner decision; the broader credential blast radius is accepted.
- Hermes development readiness and the canary cross-node Secret restore are complete; see `STATUS.md` and
  `runbooks/restore-drill.md`.
- Still open: single-region R2; ops-1 remains a SPOF until services migrate or their restores are proven.
- Future reference only: the third k3s server / HA path is parked until a new owner budget decision; it is not an
  active owner action.
