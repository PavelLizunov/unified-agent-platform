# SOPS / age

Public age recipient for `prod`:

```text
age1ellxh9rynjv2n2sau9mekpt3qmt7r9w7t7zqjj6plx3nd2d0cg9sys9s85
```

The private key is intentionally not stored in this repository.

Current bootstrap placement:

- Node-local key: `/home/uap/.config/sops/age/keys.txt` on `uap-home-1`.
- Cluster secret: `flux-system/sops-age`, key `age.agekey`.
- SOPS CLI: `/usr/local/bin/sops` on `uap-home-1`, pinned to `v3.13.1`.

Encrypted Kubernetes secrets should use the `*.sops.yaml` suffix and live under `clusters/prod/`.

Current smoke fixture:

- `clusters/prod/infra/sops-smoke.sops.yaml`
- Verified by `tests/smoke/sops-decrypt.ps1`.

Do not add plaintext secrets to this repository. Generate plaintext in a temporary file or stdin, encrypt with SOPS,
then delete the plaintext before committing.
