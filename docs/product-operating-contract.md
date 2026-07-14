# Product Operating Contract

Status: **accepted by the owner on 2026-07-14**. This document defines the target product behaviour of UAP.
It does not claim that the current deployment already satisfies the contract.

## 1. Owner and platform roles

- The owner provides a goal and may discuss material product, cost, performance or technology trade-offs.
- The owner is **not** a developer, reviewer, operator or test runner in the delivery loop.
- UAP turns the goal into a mission and carries it to the repository-specific Definition of Done.
- UAP asks the owner only when a decision is irreversible, materially changes the product/cost/performance, requires
  credentials or external authority, or no safe allowed route can make progress.
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

The platform retries, diagnoses and switches between **already approved** routes on its own. A failed attempt is not a
reason to turn the owner into an operator.

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

- enabling or changing the default model/provider/runtime policy;
- adding a paid route or materially changing expected cost;
- using the owner's Windows PC or GPU. UAP may not even probe it unless the owner has enabled the explicit
  **GPU for UAP** mode;
- destructive/failover/restore tests against non-disposable state;
- new credentials, external accounts or authority;
- an architectural change that supersedes an accepted ADR;
- irreversible product or data decisions.

Within an approved policy, ordinary model selection, worker creation, retries and test execution are platform duties.

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

The following are known gaps, not accepted end-state behaviour:

1. ADR-029 currently describes central Hermes for Workspace and a separate local Hermes for Flow. This creates two
   control/state boundaries instead of one mission plane.
2. Workspace sessions, scheduled jobs, local Task Lite and Flow/Kanban tasks are separate entities and do not yet form
   one correlated `mission_id` lifecycle.
3. Workspace does not yet provide a dependable unified view of tasks, workers, live output, tests, review and delivery
   progress; direct logs/tmux are still needed.
4. Workspace has local fallback/state paths that can expose stale or ambiguous data when the central source is
   unavailable.
5. The demonstrated coding path still contains operator/orchestrator steps; phone/Workspace goal to autonomous
   PR/CI/merge/deploy/post-verify is not yet a proven unattended loop.
6. The explicit **GPU for UAP** enable gate is a product requirement but is not yet enforced as a platform invariant.

These gaps are addressed in `docs/next-steps.md`, Phase A6. Spark Runner remains parked until the UAP mission plane is
coherent and the owner explicitly resumes it.
