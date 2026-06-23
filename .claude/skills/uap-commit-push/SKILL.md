---
name: uap-commit-push
description: Commit a change and get it pushed. The git origin + write deploy key live ONLY on uap-ops-1 (100.82.241.121), NOT the workstation. Use whenever a change is ready to land.
---

# uap-commit-push

## Hard facts

- The Windows workstation has NO `origin`. `git push` there fails. Git operations happen FROM uap-ops-1 (`100.82.241.121`) via the repo-scoped read-WRITE SSH deploy key. `gh` is authed on ops-1 (account `PavelLizunov`). Identity is already set: `UAP Agent <slovnmi@gmail.com>`.
- The repo is PUBLIC and `master` is protected by the `protect-master` ruleset: **a direct `git push origin master` is REJECTED.** Changes land via a **PR** that requires a green **`static-checks`** CI check (0 human approvals — the owner doesn't review). After merge, Flux reconciles `master`. See `docs/next-steps.md`, ADR-026.

## Steps (changes land via PR — NOT direct push)

1. Run the gate first: invoke **uap-verify** (at minimum `python tests/static/secret_scan.py .` and, if you touched `hermes/`, `python -m unittest discover -s hermes/tests -p 'test_*.py'`). Do not proceed if it fails.
2. On uap-ops-1, branch + commit (transfer workstation edits to ops-1 first via tar/scp). Conventional-Commits subject + the trailer:
   ```bash
   git checkout -b <type/short-topic>
   git commit -m "type(scope): summary" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
   git push -u origin <type/short-topic>      # the deploy key may push non-master branches
   ```
3. Open + auto-merge a PR (the deploy key pushes the branch; `gh` opens/merges the PR):
   ```bash
   gh pr create --base master --head <type/short-topic> --title "type(scope): summary" --body "..."
   gh pr merge --auto --squash <pr-number>    # merges automatically once `static-checks` is green
   ```
4. The merge only succeeds when **`static-checks`** is green. Then Flux reconciles `master`.

## Do NOT

- Do NOT `git push origin master` directly (blocked by the ruleset) or use `--no-verify`.
- Do NOT disable/bypass the `protect-master` ruleset to force a change in — fix the failing check instead.

Authoritative reference: CLAUDE.md -> Git Remote Readiness, STATUS.md, ADR-026, `docs/next-steps.md`.
