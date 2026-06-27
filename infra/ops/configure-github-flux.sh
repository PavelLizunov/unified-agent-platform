#!/usr/bin/env bash
set -euo pipefail

# Bootstrap the GitHub origin + Flux SSH git-sync from uap-ops-1.
#
# ADR-026: the repo is PUBLIC and `master` is protected by the free `protect-master` ruleset
# (PR required + the `static-checks` CI a required check). Deploys are PR-gated -- Flux reconciles
# whatever lands on `master`, and the only way onto `master` is a merged PR. So this script does NOT
# routinely direct-push `master`: it pushes a setup branch and opens a PR (UAP_COMMIT_AND_PUSH=1).
# Exceptions: the first-time bootstrap of a fresh/empty repo (no ruleset exists yet) pushes `master`
# to establish the default branch, and UAP_ALLOW_DIRECT_MASTER_PUSH=1 is an explicit break-glass.

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
visibility="${UAP_GITHUB_VISIBILITY:-public}"
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
if [[ "${visibility}" == "private" ]]; then
  echo "WARNING: visibility=private. ADR-026 relies on a PUBLIC repo so the free 'protect-master'" >&2
  echo "         ruleset can enforce the required 'static-checks' check. A private free repo CANNOT" >&2
  echo "         enforce the master ruleset (needs GitHub Pro). Set UAP_GITHUB_VISIBILITY=public." >&2
fi

gh auth status -h github.com >/dev/null

if [[ -z "${repo}" ]]; then
  owner="$(gh api user --jq .login)"
  repo="${owner}/unified-agent-platform"
fi

if gh repo view "${repo}" >/dev/null 2>&1; then
  echo "github-repo-exists: ${repo}"
  repo_was_created=0
else
  gh repo create "${repo}" "--${visibility}" \
    --description "Unified Agent Platform infrastructure and GitOps repository"
  echo "github-repo-created: ${repo}"
  repo_was_created=1
fi

gh auth setup-git --hostname github.com >/dev/null

remote_url="https://github.com/${repo}.git"
git remote remove origin >/dev/null 2>&1 || true
git remote add origin "${remote_url}"

# ADR-026: `${branch}` (master) is PR-gated by 'protect-master'; do NOT routinely direct-push it.
# A first-time bootstrap of a FRESH repo legitimately establishes master (no ruleset exists yet);
# re-running against an existing repo must go through a PR (or explicit break-glass).
if [[ "${repo_was_created}" == "1" ]]; then
  git push -u origin "${branch}"
  echo "git-push-ok (initial bootstrap of a fresh repo): ${remote_url} ${branch}"
elif [[ "${UAP_ALLOW_DIRECT_MASTER_PUSH:-0}" == "1" ]]; then
  echo "WARNING: break-glass direct push to '${branch}' (UAP_ALLOW_DIRECT_MASTER_PUSH=1) -- this" >&2
  echo "         bypasses the protect-master PR flow; prefer a PR." >&2
  git push -u origin "${branch}"
  echo "git-push-ok (break-glass): ${remote_url} ${branch}"
else
  echo "skip-direct-master-push: '${repo}' already exists and '${branch}' is PR-gated (ADR-026)."
  echo "  Land changes via a branch + PR (see UAP_COMMIT_AND_PUSH below), not a direct push."
fi

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
    # ADR-026: land via a branch + PR, never a direct push to the protected `${branch}`.
    setup_branch="${UAP_SETUP_BRANCH:-ops/enable-flux-git-sync}"
    git checkout -B "${setup_branch}"   # -B (not -b) so a re-run reuses the branch instead of aborting
    git commit -m "Enable Flux Git sync"
    git push -u origin "${setup_branch}"
    if gh pr create --base "${branch}" --head "${setup_branch}" \
        --title "Enable Flux Git sync" \
        --body "Bootstrap: enable the Flux SSH git-sync manifest. Merges via the protect-master PR flow (ADR-026)."; then
      echo "flux-sync-branch-pushed-pr-opened: ${setup_branch} -> ${branch}"
    else
      echo "flux-sync-branch-pushed: ${setup_branch} (open a PR to ${branch} manually)"
    fi
    git checkout "${branch}" --quiet    # leave the repo back on the default branch for the next run
  fi
else
  echo "Review the Flux sync manifest, then land it via a branch + PR (master is PR-gated, ADR-026)."
fi
