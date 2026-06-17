#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the repository user, not root." >&2
  exit 1
fi

if [[ ! -d .git ]]; then
  echo "Run from the repository root on uap-ops-1." >&2
  exit 1
fi

command -v gh >/dev/null
command -v git >/dev/null
command -v kubectl >/dev/null
command -v ssh-keygen >/dev/null
command -v ssh-keyscan >/dev/null

branch="${UAP_GIT_BRANCH:-master}"
repo="${UAP_GITHUB_REPO:-}"
visibility="${UAP_GITHUB_VISIBILITY:-private}"
deploy_title="${UAP_FLUX_DEPLOY_KEY_TITLE:-uap-platform-flux}"
key_dir="${UAP_FLUX_KEY_DIR:-$HOME/.config/uap/flux-git}"
key_path="${key_dir}/uap-platform-flux"
sync_manifest="clusters/prod/flux-system/gotk-sync.ssh.yaml"
sync_example="clusters/prod/flux-system/gotk-sync.ssh.example.yaml"
sync_kustomization="clusters/prod/flux-system/kustomization.yaml"

if [[ "${visibility}" != "private" && "${visibility}" != "public" ]]; then
  echo "UAP_GITHUB_VISIBILITY must be 'private' or 'public'." >&2
  exit 1
fi

gh auth status -h github.com >/dev/null

if [[ -z "${repo}" ]]; then
  owner="$(gh api user --jq .login)"
  repo="${owner}/unified-agent-platform"
fi

if gh repo view "${repo}" >/dev/null 2>&1; then
  echo "github-repo-exists: ${repo}"
else
  gh repo create "${repo}" "--${visibility}" \
    --description "Unified Agent Platform infrastructure and GitOps repository"
  echo "github-repo-created: ${repo}"
fi

gh auth setup-git --hostname github.com >/dev/null

remote_url="https://github.com/${repo}.git"
git remote remove origin >/dev/null 2>&1 || true
git remote add origin "${remote_url}"
git push -u origin "${branch}"
echo "git-push-ok: ${remote_url} ${branch}"

install -m 0700 -d "${key_dir}"
if [[ ! -f "${key_path}" ]]; then
  ssh-keygen -t ed25519 -C "${deploy_title}" -N "" -f "${key_path}" >/dev/null
  chmod 0600 "${key_path}"
  chmod 0644 "${key_path}.pub"
fi

if gh repo deploy-key list -R "${repo}" --json title --jq '.[].title' | grep -Fxq "${deploy_title}"; then
  echo "github-deploy-key-exists: ${deploy_title}"
else
  gh repo deploy-key add "${key_path}.pub" -R "${repo}" --title "${deploy_title}"
  echo "github-deploy-key-added: ${deploy_title}"
fi

known_hosts="${key_dir}/known_hosts"
ssh-keyscan github.com >"${known_hosts}" 2>/dev/null
chmod 0644 "${known_hosts}"

kubectl -n flux-system create secret generic uap-platform-git-auth \
  --from-file=identity="${key_path}" \
  --from-file=known_hosts="${known_hosts}" \
  --dry-run=client -o yaml |
  kubectl apply -f -
echo "flux-git-auth-secret-ok"

if [[ ! -f "${sync_manifest}" ]]; then
  sed "s#ssh://git@REPLACE_WITH_GIT_HOST/REPLACE_WITH_OWNER/unified-agent-platform.git#ssh://git@github.com/${repo}.git#" \
    "${sync_example}" >"${sync_manifest}"
fi

if ! grep -Fq "gotk-sync.ssh.yaml" "${sync_kustomization}"; then
  printf "  - gotk-sync.ssh.yaml\n" >>"${sync_kustomization}"
fi

echo "flux-sync-manifest-ready: ${sync_manifest}"

if [[ "${UAP_COMMIT_AND_PUSH:-0}" == "1" ]]; then
  git add "${sync_manifest}" "${sync_kustomization}"
  if git diff --cached --quiet; then
    echo "flux-sync-no-git-changes"
  else
    git commit -m "Enable Flux Git sync"
  fi
  git push origin "${branch}"
  echo "flux-sync-committed-and-pushed"
else
  echo "Review, commit, and push the Flux sync manifest when ready."
fi
