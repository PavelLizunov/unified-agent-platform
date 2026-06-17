# Flux Remote Git Sync

## Current State

Flux controllers are installed, but Git sync is not enabled because no real remote Git URL is configured.

Current local repository state:

- branch: `master`
- remote: not configured
- local Windows SSH key fingerprint: `SHA256:YLFbDMRbeUldpLQW8dmMihAQbRgCVBhmQGTW98rgm9c`
- GitHub and Bitbucket did not accept the local key during the last check.
- Windows SSH over tailnet was not listening on port `22`, so Flux cannot read this repository directly from the
  Windows workstation yet.

## Recommendation

Use an always-available external Git remote for Flux.

Local Git on Windows is acceptable for development, but it is not a good Flux source unless Windows OpenSSH Server is
enabled and the machine is expected to stay online. If Windows is off, Flux cannot reconcile from it.

## SSH Remote Path

Use this path when the Git host supports deploy keys:

1. Create or choose a remote repository.
2. Create a read-only deploy key for Flux.
3. Add the public deploy key to the Git host.
4. Create the Kubernetes Secret in `flux-system`.
5. Copy `clusters/prod/flux-system/gotk-sync.ssh.example.yaml` to a real manifest.
6. Replace URL placeholders.
7. Add the real manifest to `clusters/prod/flux-system/kustomization.yaml`.

Flux expects SSH credentials with `identity` and `known_hosts`.

Secret creation shape:

```powershell
ssh-keygen -t ed25519 -C flux-uap-platform -f .\tmp\flux-uap-platform -N ""
ssh-keyscan REPLACE_WITH_GIT_HOST > .\tmp\flux-known-hosts
kubectl -n flux-system create secret generic uap-platform-git-auth `
  --from-file=identity=.\tmp\flux-uap-platform `
  --from-file=known_hosts=.\tmp\flux-known-hosts `
  --dry-run=client -o yaml
```

Do not commit the private key or plaintext Secret. Use SOPS if the Secret must live in git.

## HTTPS Token Path

Use this path if the Git host does not support deploy keys cleanly.

Flux expects a Secret with `username` and `password` for basic auth. For GitHub/GitLab-style tokens, the token is
usually stored as `password`.

```powershell
kubectl -n flux-system create secret generic uap-platform-git-auth `
  --from-literal=username=REPLACE_WITH_USERNAME `
  --from-literal=password=REPLACE_WITH_TOKEN `
  --dry-run=client -o yaml
```

Do not commit the plaintext token.

## Local Windows Git Option

Only use this if the owner explicitly wants Git hosted on the workstation.

Requirements:

- OpenSSH Server enabled on Windows.
- Tailnet SSH reachable from `uap-home-1`.
- A bare repository path readable by the SSH user.
- A Git URL that works from `uap-home-1`.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 -GitUrl "ssh://USER@100.114.172.40/C:/path/to/unified-agent-platform.git"
```

## Verify After Enabling

```powershell
ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system get gitrepository,kustomization"
ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system describe gitrepository uap-platform"
ssh uap@100.106.223.120 "sudo k3s kubectl -n flux-system describe kustomization uap-platform"
```

Pass criteria:

- `GitRepository/uap-platform` is Ready.
- `Kustomization/uap-platform` is Ready.
- Reconciliation applies `clusters/prod`.
