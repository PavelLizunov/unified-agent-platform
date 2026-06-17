# Flux System

`gotk-components.yaml` is pinned to Flux `v2.8.8` and currently installs the minimal runtime set:

- `source-controller`
- `kustomize-controller`
- `helm-controller`
- `notification-controller`

Git sync is not enabled yet because this repository does not have a remote URL configured. When a remote is
available, add a `GitRepository` and a root `Kustomization` here.
