# Prod Infra Manifests

`namespaces.yaml` is currently the only resource included by `kustomization.yaml`.

`sops-smoke.sops.yaml` is a decrypt fixture for SOPS/age validation. It is intentionally not included in the raw
Kustomize resource list yet, because manual `kubectl apply -k` does not decrypt SOPS files. Add encrypted secrets
to a Flux `Kustomization` only after its `decryption.provider: sops` block is active.
