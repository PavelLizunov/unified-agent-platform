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

1. Choose the matching example:
   - `clusters/prod/flux-system/gotk-sync.ssh.example.yaml`
   - `clusters/prod/flux-system/gotk-sync.https-token.example.yaml`
2. Copy it to a real manifest name.
3. Replace URL placeholders with the real remote URL.
4. Create `flux-system/uap-platform-git-auth` if the repository is private.
5. Add the real sync manifest to `clusters/prod/flux-system/kustomization.yaml`.
6. Configure SOPS decryption with:

```yaml
decryption:
  provider: sops
  secretRef:
    name: sops-age
```

Do not add `gotk-sync.example.yaml` directly. It contains placeholders and is intentionally not referenced by
`kustomization.yaml`.

Detailed handoff: `runbooks/flux-remote-git.md`.

## Verify SOPS Decrypt

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke\sops-decrypt.ps1
```

Expected: `sops-decrypt-ok`.
