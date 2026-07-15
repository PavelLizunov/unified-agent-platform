# A7.3 Real-Project Canary Contract

Status: **executed six times on 2026-07-15; the autonomous failure path passed, but A7.3 is not accepted because a
successful delivery has not been demonstrated**.

The six historical per-attempt approvals are exhausted. ADR-031 now provides standing authorization for OpenAI
Luna/Sol/Terra model turns, ordinary subscription spend and automatic retry/escalation. The sixth attempt
proved the same bounded crash recovery, one autonomous review repair, runtime-attested Sol/Terra `xhigh` routing,
independent rejection and native/Central cleanup without a target PR. The coordinator foundation and exact evidence are recorded in
[`evidence/a7-3-activation-delivery-canary-2026-07-15.md`](evidence/a7-3-activation-delivery-canary-2026-07-15.md).
Before another canary, the target contract must cover a differently named custom executable from the durable runtime
owner record. Route selection now has deterministic `openai-autonomy-v1`; the coordinator must consume it before the
next canary.

No profile timer is enabled. Claude, local inference/GPU, new credentials/providers and destructive actions remain
outside the standing authority.

## Scope

The canary must use one existing repository and one build-1-configured routing profile already covered by its
repo-contract.
Mission input never supplies a shell command, local path, credential or model ID.

The approved change must:

- modify only the exact allowlist of 3–6 tracked files approved for that mission;
- cross one existing integration boundary (for example CLI→library, API→persistence or config→runtime);
- include deterministic unit/integration coverage for the changed behaviour;
- exclude secrets, infrastructure topology, destructive migration and unrelated refactoring;
- preserve the repository's stack and Definition of Done.

## Execution DAG

1. **Preflight:** record mission ID, target repository, default-branch SHA, dispatch profile, permitted file scope and
   clean disposable worktree. Resolve the deterministic author/reviewer route; fail closed on any mismatch or reroute.
2. **Dispatch:** activate exactly one Kanban root and one author worker. Every task/run/event retains the mission ID.
3. **Author:** implement and test only the approved change, then create one candidate commit. Reject unexpected paths,
   secrets, missing tests or a dirty base.
4. **Recoverable checkpoint:** after the author commit is durable but before its central acknowledgement, stop the
   coordinator at the pre-approved fault point. On restart, reconcile the existing task/worktree/commit; do not launch
   a second author or create a second candidate commit.
5. **Review:** use a separate read-only session against the exact candidate SHA. Runtime-derived model,
   provider, sandbox and session identity must pass `flow_contract.py`; otherwise stop.
6. **Delivery:** run repository gates, open the PR, wait for required CI, apply bounded fixes if permitted, and merge
   only the reviewed SHA after all gates are green.
7. **Post-verify:** fetch a fresh default branch, prove the reviewed commit is an ancestor of the merge, and rerun the
   repository's required post-merge check.
8. **Terminal and cleanup:** on the accepted path, remove the disposable worktree/branch and close the Kanban task
   only after merge and post-verify. After final author-check or review rejection, remove the same disposable state,
   durably close the native task with bounded failure gates, and let Central Hermes append `mission.failed`; that
   failure closure does not satisfy the successful-delivery gate. Preserve bounded evidence, not raw secrets or model
   output. Only after the matching success or failure evidence is durable may Central Hermes, never the build-1
   producer, write the terminal mission state through its authenticated local authority path.

## Acceptance evidence

One evidence bundle must link:

- mission/task/run IDs and ordered producer events;
- base, author, reviewed and merge SHAs;
- author/reviewer runtime attestations and separate session IDs;
- test commands, required CI run and PR;
- restart reconciliation proving one author, one candidate commit and no duplicate producer/terminal event;
- fresh-main post-verify and cleanup proof;
- final Central/Workspace/Telegram mission projection.

Any missing item is a failed canary, not a partial success.

## Standing execution authority

The repository contract and build-1 profile fix the target, integration boundary, allowed file scope, merge/deploy and
cleanup rules. The platform chooses Luna/Sol/Terra, reasoning effort, activation, retry and escalation automatically,
then performs every command, test, PR, merge, verification and cleanup. It asks the owner only for a genuine product
blocker or a dangerous action outside ADR-031; spending money is not such an action.
