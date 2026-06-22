---
name: uap-commit-push
description: Commit a change and get it pushed. The git origin + write deploy key live ONLY on uap-ops-1 (100.82.241.121), NOT the workstation. Use whenever a change is ready to land.
---

# uap-commit-push

## Hard facts

- The Windows workstation has NO `origin`. `git push` there fails. Pushes happen FROM uap-ops-1 (`100.82.241.121`) via the repo-scoped read-WRITE SSH deploy key.
- Flux follows `master` with prune:true on ./clusters/prod, so a push to master DEPLOYS. Treat master as production.

## Steps

1. Run the gate first: invoke **uap-verify** (or at minimum `python tests/static/secret_scan.py .`). Do not commit if it fails.
2. Set a canonical identity on the machine that creates the commit BEFORE committing (it currently defaults to the placeholder `Codex <codex@local>` / `Debian <uap@uap-ops-1.local>`):
   ```bash
   git config user.name  "UAP Codex Agent"      # distinct from the Claude-worker identity
   git config user.email "<a-real-routable-email>"
   ```
3. Commit with a Conventional-Commits subject and the required trailer:
   ```
   type(scope): summary

   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
   ```
4. Push from uap-ops-1 (the only host with origin + the write key). If you edited on the workstation, transfer the change to ops-1 first (tar/scp or git bundle/patch over ssh), then push there.

## Do NOT

- Do NOT `--no-verify` or bypass signing.
- Do NOT push straight to master if a branch-protection ruleset is in place — open a PR so the `static-checks` CI gate runs.

Authoritative reference: CLAUDE.md -> Git Remote Readiness, STATUS.md.
