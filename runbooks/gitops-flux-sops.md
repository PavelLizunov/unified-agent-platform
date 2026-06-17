# GitOps: Flux + SOPS

## Current State

- Flux version: `v2.8.8`.
- Installed controllers:
  - `source-controller`
  - `kustomize-controller`
  - `helm-controller`
  - `notification-controller`
- Image automation controllers are intentionally not installed at this stage.
- SOPS age key:
  - private key: node-local and Kubernetes Secret only;
  - public recipient: stored in `.sops.yaml` and `infra/sops/README.md`.

## Verify Flux

```powershell
ssh uap@192.168.0.201 "sudo k3s kubectl -n flux-system get deploy,pods"
```

Expected: four deployments, all `1/1`.

## Verify SOPS Key Secret

```powershell
ssh uap@192.168.0.201 "sudo k3s kubectl -n flux-system get secret sops-age"
```

Expected: `sops-age`.

## Enable Git Sync Later

When a remote Git URL exists:

1. Add a `GitRepository` in `clusters/prod/flux-system`.
2. Add a root Flux `Kustomization` pointing at `./clusters/prod`.
3. Configure SOPS decryption with:

```yaml
decryption:
  provider: sops
  secretRef:
    name: sops-age
```
