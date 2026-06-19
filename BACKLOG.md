# Backlog

Tracked items that are **not** done yet, split by who must act. Source: the 2026-06-19 cross-review
(`REVIEW-CODEX.md`) and `STATUS.md` -> Cross-Review Remediation. Done items live in STATUS.md, not here.

## Owner action required (blocks nothing else from continuing)

| Ref | Item | Why it needs the owner | Unblocks |
|---|---|---|---|
| #1 | Rotate the R2 token to a **bucket-scoped** key (Cloudflare dashboard, ~2 min) | Only the owner has the Cloudflare account | #10 (agent then updates SOPS + rclone + lifecycle) |
| #2 | **Independent off-homelab age-key escrow** + verify a decrypt with it (keystone DR) | Owner must place the master key in a vault outside the Proxmox homelab | Honest DR claim; #9 full proof |
| #5 | **Foreign VPS** (adequately sized, not a 1 GB etcd box) | Owner procures/pays + grants SSH | Stage 1 HA (3rd node), Stage 3 egress Plan A, removes the ops-1 SPOF |
| — | Retrieve the new Vaultwarden admin token from `~/vaultwarden/admin-token.NEW.txt` on ops-1, move to a password manager, then delete the file | Owner-only credential | — |
| — | (optional) Revoke the old "GitHub CLI" OAuth grant in GitHub settings; enable branch protection if upgrading to GitHub Pro | Owner GitHub account | full invalidation of the removed token |

## Agent-doable, but needs an owner "go" or a careful window

| Ref | Item | Note |
|---|---|---|
| #9 | **Canary cross-node restore drill** — create a canary Secret on prod, snapshot, restore on a disposable node from R2 with snapshot + token only, confirm the canary decrypts | Settles whether `encryption-config.json` is required (REVIEW-CODEX.md #3). Touches prod (a throwaway test Secret) + spins a disposable k3s. |
| #11 | **kubeconfig `0644`->`0600` + tailnet-only host firewall** (restrict 6443/10250/8472 off the LAN) | LIVE change on the single control-plane node + k3s restart + firewall = lockout risk. Do in a supervised window with a timed auto-rollback, not unattended. |
| #10 | **R2 lifecycle rule** for manual/on-demand snapshots (retention) | Blocked on #1 (do after the scoped token exists). |

## Notes

- Stage 2 (`Postgres HA + Garage`) manifests may be **prepared and reviewed** now (review-only scaffolding), but
  must NOT be applied until the Stage 1 HA gate is green — see `BUILD-PLAN.md` Stage 2 and `clusters/staging-stage2/`.
- Residual accepted for Stage 0P: classic GitHub branch protection unavailable on a free private repo; single-region
  R2; ops-1 remains a SPOF until services migrate into the cluster (Stage 3).
