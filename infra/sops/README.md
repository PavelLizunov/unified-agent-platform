# SOPS / age

Public age recipient for `prod`:

```text
age1ellxh9rynjv2n2sau9mekpt3qmt7r9w7t7zqjj6plx3nd2d0cg9sys9s85
```

The private key is intentionally not stored in this repository.

Current bootstrap placement:

- Node-local key: `/home/uap/.config/sops/age/keys.txt` on `uap-home-1`.
- Cluster secret: `flux-system/sops-age`, key `age.agekey`.

Encrypted Kubernetes secrets should use the `*.sops.yaml` suffix and live under `clusters/prod/`.
