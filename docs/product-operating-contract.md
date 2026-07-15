# Product Operating Contract

Status: **accepted by the owner on 2026-07-14**. This document defines the target product behaviour of UAP.
It does not claim that the current deployment already satisfies the contract.

## 1. Owner and platform roles

- The owner provides a goal and may discuss material product, performance or technology trade-offs.
- The owner is **not** a developer, reviewer, operator or test runner in the delivery loop.
- UAP turns the goal into a mission and carries it to the repository-specific Definition of Done.
- UAP asks the owner only when a decision is irreversible, materially changes the product, requires new credentials
  or external authority, creates real destructive risk, or no safe allowed route can make progress.
- Existing repository contracts and recorded preferences are used before asking a repeated question.

## 2. One product, one mission plane

- External NousResearch `hermes-agent` remains the foundation of the agent layer.
- Central Hermes is the only source of truth for sessions, missions, status and events.
- Workspace and Telegram are synchronized views of that same state: the same history, mission identifiers, questions,
  progress and final result.
- Flow, swarms, coding agents, test VMs and build hosts are execution facilities behind a Hermes mission. They do not
  create a second user-facing control plane or an independent mission history.
- Every child task, worker, test, review, PR, deploy and verification event is correlated to one `mission_id`.

## 3. Autonomous delivery contract

Unless the repository contract says otherwise, an accepted mission includes:

1. inspect the repository contract and current state;
2. plan the smallest complete change;
3. create an isolated branch/worktree;
4. implement and self-correct;
5. run every relevant deterministic test and required platform/VM gate;
6. obtain independent review when required by risk or repository policy;
7. create the PR, wait for CI and fix failures;
8. merge, deploy or release when the project defines those steps;
9. perform post-deploy/post-release verification;
10. clean up temporary workers/worktrees and return an evidence-backed result.

The platform retries, diagnoses and switches between **already approved** routes on its own. Luna, Sol and Terra are
standing-approved OpenAI subscription capacity; their selection, reasoning effort, retry, escalation and ordinary
subscription spend never require another confirmation. A failed attempt is not a reason to turn the owner into an
operator.

Submitting a mission authorizes its normal repository-defined workers and tests. It does not authorize a new model
provider, a new privileged route, destructive testing or use of the owner's personal GPU.

## 4. Quality, cost and context

- Quality is the first priority. Use the most reliable approved route suitable for the task.
- Deterministic compilers, validators, tests and CI are the primary evidence; model self-assessment is not a gate.
- Send only relevant context, reuse durable mission artifacts and avoid repeatedly feeding the same repository/logs to
  models.
- Parallelism is used only when it shortens the critical path or provides genuinely independent review.
- A mission is complete only when all mandatory gates are green or the result is honestly marked blocked with evidence.

## 5. Owner gates

Explicit owner approval is required for:

- enabling a new model provider/runtime outside the approved OpenAI Luna/Sol/Terra policy;
- using the owner's Windows PC or GPU. UAP may not even probe it unless the owner has enabled the explicit
  **GPU for UAP** mode;
- destructive/failover/restore tests against non-disposable state;
- new credentials, external accounts or authority;
- an architectural change that supersedes an accepted ADR;
- irreversible product or data decisions.

Within an approved policy, ordinary model selection, worker creation, retries and test execution are platform duties.
Ordinary subscription or monetary spend is not a dangerous operation and is not an owner gate.

## 6. Observation and reporting

Workspace shows a compact mission view:

- current stage, useful progress estimate and blocking state;
- on expansion: tasks/DAG, active workers, live terminal/tool output, file changes, tests, review, PR/CI and deploy events;
- the exact question that needs owner input, if any;
- final result and evidence without requiring the owner to inspect raw logs.

Telegram receives the same mission status, owner questions and final result. It must not maintain a separate history.

The normal final report is concise: outcome, important technical decisions, completed checks, PR/deploy/release links and
known debt.

## 7. Engineering defaults

- Preserve the existing project stack unless there is a measured reason to change it.
- Prefer a modular monolith over premature microservices: one deployable unit with explicit internal modules is easier
  for agents to change, test and reason about atomically. Split a service only for a proven isolation, scaling, security
  or lifecycle boundary.
- Keep production code modular and dependencies minimal; prefer standard-library/native platform capabilities.
- New durable daemons and strict state machines favour Rust; small infrastructure/Kubernetes/network utilities may use
  Go; existing web UI stays in its established TypeScript stack; declarative formats describe desired state, not
  complex control flow.
- Do not add new Python production runtimes by default. Existing stable Python is not rewritten wholesale; replace it
  only when that subsystem is being changed and the replacement has a clear reliability or maintenance benefit.
- New end-user desktop applications should avoid Electron. UAP's remote Workspace may remain web/PWA; its interface
  should be compact, functional and minimal rather than marketing-oriented.
- Support relevant target platforms through repository-defined automated tests, not manual owner testing.

## 8. Current contract gaps

The A6.4 controlled canary added one central mission log, fail-closed central-only Workspace views and correlated
build-1 execution evidence. The remaining gaps are not accepted end-state behaviour:

1. Workspace and Telegram synchronize the new mission projection, not complete chat/session history or a shared
   answer-and-resume loop for owner questions.
2. The profile-bound A7 coordinator and schema-v3 three-cycle profile are installed. Current source adds durable
   independent-review/required-CI escalation and same-PR repair, but that exact v2 revision and a successful
   PR/CI/merge/post-verify delivery remain unproven live.
3. Workspace polls current snapshots. It does not provide durable event-cursor replay for every intermediate terminal
   update, and direct logs/tmux may still be needed for full live detail.
4. Mission events/subscriptions, terminal output, adapter state, completed Kanban tasks and disposable worktrees have no
   complete retention/cleanup lifecycle. An open PR that exhausts all autonomous repair cycles is intentionally retained
   with its exact remote branch as bounded failure evidence because GitHub offers no conditional PR-close mutation.
5. The Flow contract derives model and sandbox policy from the exact Codex rollout `turn_context`; the OpenAI-only
   v1 route is installed and the v2 quality-failure route is validated in source but still awaits exact live rollout.
   OS-independent read-only filesystem and credential isolation remain unproven.
6. The prepared terminal endpoint now requires both the general API bearer and a direct loopback source. Producer
   events use a closed schema and protect every allowed string before storage; mission DB and adapter state are
   owner-only on POSIX. These offline hardening changes still await a verified A7 rollout.
7. Telegram delivery is at-least-once and has a duplicate window after remote send but before cursor persistence.
8. The explicit **GPU for UAP** enable gate is a product requirement but is not yet enforced as a platform invariant.

These gaps drive the post-A6 milestones in `docs/next-steps.md`. Spark Runner remains parked until the UAP mission
plane is coherent and the owner explicitly resumes it.
