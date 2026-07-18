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

1. Workspace and Telegram synchronize the mission projection and owner question/answer resume, but not complete
   cross-channel chat/session history. A bound Telegram chat and the exact accepting Workspace session can route an
   ordinary message to their one open mission question with restart-safe source-message replay. Both implementations
   are deployed and passed in-pod component checks; a real cross-channel owner question/answer campaign remains
   pending.
2. The profile-bound A7 coordinator and `openai-autonomy-v2` route are installed. The corrected schema-v3 runtime
   passed one Telegram-bound non-toy acceptance canary through timer intake and recovery. A registered schema-v4
   profile later accepted ordinary Workspace goals and delivered non-toy code plus a follow-up documentation repair
   through runtime-attested author/reviewer, multi-platform CI, exact-head merge, fresh-main post-verify, Central
   terminal convergence and cleanup. The follow-up included a real review rejection and autonomous correction. A later
   ordinary Telegram goal used the same registered profile, survived a controlled exact pre-turn capacity failure,
   completed Sol/Terra delivery and produced terminal sequence 27 plus a verified completion bundle. That was an
   adversarial correction campaign: reviewer recovery and Central capacity-history completion fixes were installed
   while preserving the same durable mission, so a clean all-fixes-preinstalled run remains stronger evidence. These
   campaigns prove both owner entry channels only for one exact registered profile; generic arbitrary-repository intake
   and route-profile creation from an unconstrained owner goal remain outside that proof.
   The registered pilot now also carries immutable `delivery_mode: none`; Central requires explicit
   `delivery: not_applicable` evidence instead of treating fresh-main verification as a deploy. Actual `deploy` and
   `release` modes remain fail-closed until their artifact, environment and deployed-revision gates are implemented
   and proven live.
3. Workspace now uses the Central cursor contract for the selected mission and passed a live 20-event reconnect
   canary. Its Central timeline remains intentionally bounded; direct logs may still be needed for full raw tool detail.
4. Central retains the latest 100 unbound terminal mission histories, never prunes the currently bound mission, and
   keeps a payload-free tombstone so a retired stable `mission_id` cannot be reused.
   Completed Kanban tasks are archived. Native Kanban GC bounds their events/logs to 30 days only while the board has
   no nonterminal task, so a long-running worker log is not removed; deferred GC is retried automatically. Deleting
   the 30-day retry state requires a successful idle-board GC at or after that deadline; a legacy task first archived
   during migration starts that bounded archive-event retention clock then. Delivery
   state is private and retained for 30 days, then crash-safely removed through a rediscoverable renamed directory;
   disposable worktrees are removed immediately after verification. An open PR that
   exhausts all autonomous repair cycles is intentionally retained with its exact remote branch as bounded failure
   evidence because GitHub offers no conditional PR-close mutation.
5. The Flow contract derives model, effort and sandbox policy from the exact Codex rollout `turn_context`; the
   OpenAI-only v2 route ran live with Sol author and separate Terra reviewer. The source coordinator now adds a
   Linux OS-enforced reviewer process boundary: strict read-only filesystem/home, explicit writable model/Codex
   runtime homes, read-only candidate/state, hidden unrelated `/proc`, and inaccessible common credential stores and
   control-plane environment names. PR #266 passed required CI, exact merge `a0d8f391...` is installed, and the
   installed exact-wrapper probe proved the intended write/credential/proc/user-runtime boundary. A real
   attempt then found a Type=oneshot ordering deadlock in the transient unit. PR #271 removed `After=` while retaining
   the parent `BindsTo=` lifetime boundary. The first corrected restart safely quarantined the interrupted reviewer but
   exposed a permanent `reconciling` state; PR #272 now permits only a clean exact-SHA, unchanged-draft-PR reviewer
   retry after the old unit is unloaded. The same mission completed a runtime-attested Terra read-only review inside
   the corrected unit. Author ambiguity still fails closed.
   Restart-safe capacity retry/whole-route fallback is covered hermetically, including scheduled cooldown outside the
   finite Kanban claim TTL. The ordinary Telegram campaign proved one controlled exact pre-turn stderr recovery on the
   same Sol model without an owner question or duplicate terminal result. It did not observe a natural provider
   envelope, `capacity_wait`, exhausted burst or whole-route fallback.
6. The terminal endpoint requires both the general API bearer and a direct loopback source. Producer events use a
   closed schema and protect every allowed string before storage; mission DB and adapter state are owner-only on POSIX.
   The A7 success path exercised terminal completion. The new reviewer boundary narrows filesystem writes and
   credential reach on build-1; author isolation and secrets stored outside the enumerated host stores remain
   follow-up work.
7. Telegram delivery is at-least-once and has a duplicate window after remote send but before cursor persistence.
8. The explicit **GPU for UAP** enable gate is a product requirement but is not yet enforced as a platform invariant.
9. A closed canonical completion-evidence bundle and deterministic semantic verifier are implemented for the
   registered no-deploy profile and installed on build-1. The ordinary Telegram campaign produced the first live
   artifact; the installed verifier accepted semantic digest `d05c16b7...`. The initial schema binds delivery
   runtime, Git/PR/CI/review/post-verify/cleanup and Central terminal identities. It does not yet bind ordinary input
   channel/source event, Workspace and Telegram cursors, a deployed revision, a journal proof of timer origin or a
   signed/GitHub-attested artifact. Those omissions prevent treating it as the final Product Operating Contract
   completion certificate.

These gaps drive the post-A6 milestones in `docs/next-steps.md`. Spark Runner remains parked until the UAP mission
plane is coherent and the owner explicitly resumes it.
