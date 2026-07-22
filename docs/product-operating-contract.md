# Product Operating Contract

Status: **accepted by the owner on 2026-07-14**. The current deployment has a GitHub-attested completion
certificate for the exact registered no-deploy pilot boundary and a verified live completion bundle for the first
closed production deploy driver, `vpnctl`/`vpnctld-systemd-v1`. This document still defines the wider target product
behaviour; section 8 records the capabilities not covered by that exact proof.

The closed schema-v3 subject binds an ordinary Telegram goal, the required ordinary Workspace answer, both channel
cursors/projection identities and the autonomous OpenAI delivery suffix. It does not claim arbitrary repository/profile
discovery, an actual deploy/release target, complete cross-channel chat transcripts, HA or a platform-wide GPU/local
runtime hard deny.

## 1. Owner and platform roles

- The owner provides a goal and may discuss material product, performance or technology trade-offs.
- The owner is **not** a developer, reviewer, operator or test runner in the delivery loop.
- UAP keeps questions, feasibility checks and trade-off discussion in chat. An explicit execution request turns the
  agreed goal into a mission and carries it to the repository-specific Definition of Done; `/run` and `/discuss` are
  deterministic escape hatches when wording is intentionally unusual.
- The owner chooses from server-registered projects in Workspace or names one in Telegram; repository paths, models
  and commands are never accepted from the owner message. If the project is ambiguous, the platform asks one
  deterministic clarification and resumes the original goal.
- UAP asks the owner only when a decision is irreversible, materially changes the product, requires new credentials
  or external authority, creates real destructive risk, or no safe allowed route can make progress.
- Existing repository contracts and recorded preferences are used before asking a repeated question.
- A cataloged `setup_required` project can be discussed from its Workspace card. The chat receives only server-owned
  repository metadata and remains read-only; an explicit setup command creates a reviewable UAP mission. The project
  stays unavailable for coding intake until its exact profile, runner and canary have made the catalog status `ready`.

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
Telegram voice notes are ordinary owner input after successful transcription through the configured Hermes STT path;
a transcription failure is reported without creating a mission.

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
   are deployed and passed in-pod component checks. The approved-profile `architecture_change` producer is now live:
   ordinary Telegram mission `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` created one inert root and deterministic
   question before any model, accepted only exact ordinary `APPROVE`, resumed the same root and completed delivery.
   Telegram-origin mission `mission-intake-503332fe3dcba802ded5f3a1bd513026` then accepted its sole ordinary answer
   through Workspace, resumed the same root, completed PR/CI/merge/post-verify/cleanup and produced a signed schema-v3
   certificate with both cursors at 27 and one projection identity. Complete cross-channel chat history remains
   pending; unsupported privileged capabilities still fail closed.
2. The profile-bound A7 coordinator and `openai-autonomy-v2` route are installed. The corrected schema-v3 runtime
   passed one Telegram-bound non-toy acceptance canary through timer intake and recovery. A registered schema-v4
   profile later accepted ordinary Workspace goals and delivered non-toy code plus a follow-up documentation repair
   through runtime-attested author/reviewer, multi-platform CI, exact-head merge, fresh-main post-verify, Central
   terminal convergence and cleanup. The follow-up included a real review rejection and autonomous correction. A later
   ordinary Telegram goal used the same registered profile, survived a controlled exact pre-turn capacity failure,
   completed Sol/Terra delivery and produced terminal sequence 27 plus a verified completion bundle. That was an
   adversarial correction campaign: reviewer recovery and Central capacity-history completion fixes were installed
   while preserving the same durable mission, so a clean all-fixes-preinstalled run remained stronger evidence. A
   later clean owner-gated Telegram mission ran with all fixes preinstalled and completed Sol/Terra delivery, PR #9,
   CI, merge, post-verify, concrete terminal result and cleanup, then produced the first verified schema-v2 artifact.
   PR #286 also closes unsafe fresh initialization after loss of private coordinator state: projected execution
   history, surviving mission-local artifacts and a lost automatic owner-gate checkpoint now fail before model/Git/
   GitHub mutation. The exact merge is installed and all six timers passed a natural tick. This is safe detection;
   automatic reconstruction after total `delivery-state.json` loss is still not claimed.
   PR #296 restored the server-owned ordinary Telegram mapping to the same automatic registered-v4 profile used by
   Workspace; exact review, CI, Flux rollout, Ready/API checks and a natural coordinator tick passed. The separate
   owner-gate profile remains available only for deliberate privileged-flow diagnostics. These campaigns prove both
   owner entry channels only for exact registered profiles; generic arbitrary-repository intake and route-profile
   creation from an unconstrained owner goal remain outside that proof.
   No-deploy profiles carry immutable `delivery_mode: none`; Central requires explicit `delivery: not_applicable`
   evidence instead of treating fresh-main verification as a deploy. The registered `vpnctl` profile now has the
   first closed `delivery_mode: deploy` implementation: exact merged revision, production environment, installed
   payload SHA-256, bounded retry, rollback and health verification are terminal gates. Ordinary Workspace mission
   `mission-intake-e2d2812bf5197db2a0c68754f2351b20` passed that complete path for PR #127 and exact production
   revision `770dce0...`; its schema-v4 bundle also proves cleanup and one deployment attempt. The negative
   post-deploy projection attempt and PR #397 correction are preserved in
   `docs/evidence/vpnctl-production-deploy-live-canary-2026-07-22.md`. `release` and all other deploy targets remain
   fail-closed.
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
   The A7 success path exercised terminal completion. The installed coordinator now applies the same parent-bound Linux
   namespace to both model actors: author may additionally write its disposable worktree, while reviewer remains
   exact-SHA read-only. Common credential stores and control-plane environment are hidden from both. Reviewer has live
   mission proof. PR #279 installed the author boundary, its installed adversarial probe passed, and a controlled real
   Sol author completed with rollout-derived OpenAI/model/effort/sandbox attestation while changing only the allowed
   disposable file. The later owner-gated ordinary mission completed Sol authoring and Terra review on the exact
   combined revision. Secrets outside the enumerated host stores remain follow-up work.
7. Telegram delivery is at-least-once and has a duplicate window after remote send but before cursor persistence.
8. The explicit **GPU for UAP** enable gate is a product requirement but is not yet enforced as a platform invariant.
9. A closed canonical completion-evidence bundle and deterministic semantic verifier are implemented for the
   registered no-deploy profile and installed on build-1. The ordinary Telegram campaign produced the first live
   artifact; the installed verifier accepted semantic digest `d05c16b7...`. The initial schema binds delivery
   runtime, Git/PR/CI/review/post-verify/cleanup and Central terminal identities. PR #275 deploys a compatible closed
   v2 schema that binds the server-owned ordinary input platform and hashed source key/message to the deterministic
   mission identity without persisting raw channel identifiers. The owner-gated Telegram canary produced the first
   live v2 artifact; the installed verifier accepted semantic digest `4dbb3b92...`, its systemd invocation chain contains
   five exact unit identities, and Workspace/Telegram both converged at cursor 27. A deployed revision is not applicable
   to this registered no-deploy target. PR #295 published the exact closed schema-v3 bundle from cross-channel mission
   `mission-intake-503332fe3dcba802ded5f3a1bd513026` on protected `master`. It additionally binds the Workspace and
   Telegram cursors/projection identities and the answer platform. The master-only GitHub-hosted workflow independently
   re-ran the semantic verifier and issued SLSA provenance for byte digest `92178a9b...`, bound to merge `a127994...`,
   `refs/heads/master` and the exact workflow identity. This is the final two-channel certificate for the exact
   registered owner-gated no-deploy pilot. It is not evidence for arbitrary repository/profile discovery, the new
   vpnctl deploy path, other deploy/release modes, complete chat transcripts, HA or a platform-wide GPU/local-runtime hard deny. Exact
   attestation evidence:
   `docs/evidence/signed-completion-attestation-2026-07-19.md`.
10. The first live Telegram success notification exposed only a generic result. Current source replaces that constant
    at Central's terminal-authority boundary with a bounded deterministic summary of the accepted goal, changed paths,
    PR, verified revision, required gates and delivery applicability. PR #277 passed required CI, exact Flux rollout,
    mounted-runtime verification and an in-pod Central/Telegram component assertion. The owner-gated live mission later
    emitted the concrete accepted goal, PR #9, merge, gates, no-deploy applicability and four changed paths through the
    shared terminal projection.

These gaps drive the post-A6 milestones in `docs/next-steps.md`. Spark Runner remains parked until the UAP mission
plane is coherent and the owner explicitly resumes it.
