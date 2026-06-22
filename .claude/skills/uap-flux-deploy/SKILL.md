---
name: uap-flux-deploy
description: Deploy a change to the cluster via Flux GitOps and VERIFY it actually reconciled. Use after editing anything under clusters/prod. A push alone is NOT a verified deploy.
---

# uap-flux-deploy

Flux is pull-based. "Pushed" != "deployed". The Ready check at the new SHA is the real confirmation.

## Steps

1. Ensure the gate is green: invoke **uap-verify**.
2. Commit + push: invoke **uap-commit-push** (push happens from uap-ops-1).
3. Reconcile / wait, then assert BOTH Flux objects are Ready at the new commit. Reach the cluster either via uap-home-1 (`sudo k3s kubectl`) or via uap-ops-1 (`kubectl`):
   ```bash
   ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system get gitrepository,kustomization"
   ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system describe kustomization uap-platform | tail -30"
   ```
   Expect `GitRepository/uap-platform` Ready (revision = your SHA) AND `Kustomization/uap-platform` Ready (Applied revision = your SHA).
4. Check the target workload, e.g. in uap-system:
   ```bash
   ssh uap@100.106.223.120 "sudo k3s kubectl -n uap-system get deploy,pod"
   ```

## Gotcha

- If your manifest is a new file, it must be referenced by a sibling `kustomization.yaml` or Flux never applies it (this is currently true of litellm.yaml/hermes.yaml — they are NOT in clusters/prod/infra/kustomization.yaml).

Authoritative reference: runbooks/flux-remote-git.md (Verify After Enabling), runbooks/gitops-flux-sops.md.
