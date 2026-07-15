# A7.3 Real-Project Canary Contract

Status: **design only; no target, model, activation, fault injection, merge or deploy is authorized**.

The pre-activation foundation may be prepared without that bundle. It is limited to offline, non-spawning recovery
primitives such as deterministic event reconciliation and reconstruction of disposable adapter cache from native
Kanban authority; it must not install a periodic poller or pass `--activate`.

## Scope

The canary must use one owner-approved existing repository and one owner-approved, build-1-configured routing profile.
Mission input never supplies a shell command, local path, credential or model ID.

The approved change must:

- modify 3–5 tracked files;
- cross one existing integration boundary (for example CLI→library, API→persistence or config→runtime);
- include deterministic unit/integration coverage for the changed behaviour;
- exclude secrets, infrastructure topology, destructive migration and unrelated refactoring;
- preserve the repository's stack and Definition of Done.

## Execution DAG

1. **Preflight:** record mission ID, target repository, default-branch SHA, dispatch profile, permitted file scope and
   clean disposable worktree. Resolve the owner-approved author/reviewer routes; fail closed on any mismatch or reroute.
2. **Dispatch:** activate exactly one Kanban root and one author worker. Every task/run/event retains the mission ID.
3. **Author:** implement and test only the approved change, then create one candidate commit. Reject unexpected paths,
   secrets, missing tests or a dirty base.
4. **Recoverable checkpoint:** after the author commit is durable but before its central acknowledgement, stop the
   coordinator at the pre-approved fault point. On restart, reconcile the existing task/worktree/commit; do not launch
   a second author or create a second candidate commit.
5. **Review:** use a separate owner-approved read-only session against the exact candidate SHA. Runtime-derived model,
   provider, sandbox and session identity must pass `flow_contract.py`; otherwise stop.
6. **Delivery:** run repository gates, open the PR, wait for required CI, apply bounded fixes if permitted, and merge
   only the reviewed SHA after all gates are green.
7. **Post-verify:** fetch a fresh default branch, prove the reviewed commit is an ancestor of the merge, and rerun the
   repository's required post-merge check.
8. **Cleanup:** remove the disposable worktree/branch and close the Kanban task only after merge and post-verify.
   Preserve bounded evidence, not raw secrets or model output. Only after that evidence is durable may Central Hermes,
   never the build-1 producer, write the terminal mission state through its authenticated local authority path.

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

## Single owner approval bundle

Before execution the platform asks once for the exact target/goal, integration boundary, allowed file scope,
author/reviewer routes, activation, recoverable fault point, merge/deploy authority, cleanup authority and time/cost
ceiling. After approval the platform performs every command, test, retry, PR, merge, verification and cleanup; the owner
does not become an operator.
