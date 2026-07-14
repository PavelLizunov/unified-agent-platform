---
name: hermes-flow-v2
description: "Run long or multi-checkpoint repository work through quota-aware Hermes Kanban with guarded Codex author/reviewer roles."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [coding, kanban, review, codex]
    related_skills: []
---

# Hermes Flow v2

Load this skill for repository work with more than one checkpoint/PR or an expected duration over 30 minutes. Do
not continue such work through a chain of `chat --resume` sessions.

## Hard contract

1. Use Hermes Kanban as the durable DAG/checkpoint ledger: `preflight → author → commit → reviewer → CI/PR →
   merge → cleanup`. Store artifacts under `/home/uap/swarm-out/<mission>/` and attach their paths to task results.
2. Before any write, run `/home/uap/swarm-bin/flow_contract.py route` with the installed policy/quota file and then
   `guard-repo` for the exact repository, remote, branch, and disposable worktree.
3. Never invoke an engine whose quota state is `quota_blocked`. In particular, do not probe Claude. Never use a
   local model unless the owner explicitly approved that exact mission.
4. Run the author with the exact model returned by the route. The author edits/tests only; the orchestrator stages
   an explicit allowlist and creates the commit after re-running checks.
5. Run the reviewer in a separate session with `codex exec --sandbox read-only`. Summarize each Codex JSONL together
   with its matching local rollout; runtime model and sandbox must match the approved route and role. For
   `same_provider_degraded`, the exact reviewer model must differ from the author model. The reviewer reads the real
   diff, runs checks, and produces `verification.json`; it never edits, commits, pushes, or merges.
6. Validate `summary.json` and `verification.json` against the current HEAD and green required CI. Use
   `--allow-same-provider-review` only when the route explicitly returned `same_provider_degraded`. It is forbidden
   for infra, security, and secrets.
7. At most two review/fix cycles. Complete the root card only after merge, default-branch proof, remote/local branch
   deletion, disposable worktree removal, and a green `terminal-check`.
8. When the task belongs to a central Hermes mission, use the installed `mission_adapter.py` ingress/sync boundary and
   preserve its `mission_id`/tenant. Never bypass its idempotency key. `--allow-dispatch` additionally requires the
   owner's approved runtime/profile, an explicit assignee and a non-scratch workspace.

The full command reference and artifact schemas are in `runbooks/hermes-flow-v2.md` in
`PavelLizunov/unified-agent-platform`.
