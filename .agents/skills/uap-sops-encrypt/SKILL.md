---
name: uap-sops-encrypt
description: Encrypt a Kubernetes Secret with SOPS for clusters/prod. MUST run on uap-home-1 (sops is absent on Windows; the age private key lives only there). Use when adding/rotating any secret.
---

# uap-sops-encrypt

## Where (non-negotiable)

- Encrypt ON `uap-home-1` (`100.106.223.120`), where `sops` is installed. Encryption uses the public age recipient below; the private key on uap-home-1 is needed only to decrypt and verify. Windows can edit ciphertext but has no `sops` installation.

## Invariants (get any of these wrong and SOPS silently leaves fields plaintext -> committed secret)

- File path MUST match `.sops.yaml` path_regex: it must live under `clusters/prod/` and be named `*.sops.yaml` (or `*.sops.yml`). Files outside clusters/prod/ are NOT auto-encrypted.
- Put secret values under `data:` or `stringData:` only — `.sops.yaml` `encrypted_regex` is `^(data|stringData)$`. A secret under any other key is left plaintext by design.
- Recipient is the repo age key `age1ellxh9rynjv2n2sau9mekpt3qmt7r9w7t7zqjj6plx3nd2d0cg9sys9s85`.

## Steps

1. On uap-home-1, write the plaintext manifest with values under data/stringData.
2. Encrypt in place: `sops --encrypt --in-place clusters/prod/.../<name>.sops.yaml`.
3. Confirm it is actually encrypted: the file now contains a `sops:` block and `ENC[AES256_GCM...` values.
4. SHRED the plaintext if any temp copy existed (`shred -u <tmp>`); never leave plaintext on disk or in shell history.
5. Add the file to `clusters/prod/infra/kustomization.yaml` so Flux applies it.
6. Verify the exact new file on uap-home-1: `SOPS_AGE_KEY_FILE=/home/uap/.config/sops/age/keys.txt sops --decrypt clusters/prod/.../<name>.sops.yaml >/dev/null`.

Never paste a secret value into a prompt, log, markdown, or commit message.

Authoritative reference: infra/sops/README.md, .sops.yaml, runbooks/gitops-flux-sops.md.
