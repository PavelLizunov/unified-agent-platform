# Current Status

Last updated: 2026-07-19

## Phase

- Current phase: **post-Stage 0P** — infra bootstrap done; the **model + agent layers are LIVE** in `uap-system`
  (see "Model & Agent Layer" below). Active direction (2026-06-22/23 **pivot**): **vibe-coding** — adopt the
  external NousResearch **hermes-agent** as the harness (the bespoke `hermes/hermes.py` is parked). See
  `docs/next-steps.md`, `docs/infrastructure.md`, `docs/research/`.
- **Product workflow contract accepted 2026-07-14 (ADR-030); A6 controlled canary complete.** Hermes remains the
  agent-layer foundation. Central Hermes now owns one live `mission_id`/event history, Workspace and Telegram render
  that projection, and build-1 publishes correlated Flow/Kanban execution evidence. The exact proof and its remaining
  automation boundary are recorded in `docs/evidence/a6-4-controlled-canary-2026-07-14.md`. Canonical behaviour remains
  `docs/product-operating-contract.md`.
- **A6.1 central mission contract complete offline 2026-07-14.** `docs/hermes-mission-contract-v1.md` fixes the minimal
  `mission_id`, ordered event envelope, lifecycle and cursor/replay rules. A fake central backend proves that Workspace
  and Telegram projections converge after refresh/reconnect, while the pinned Workspace overlay makes
  `HERMES_CENTRAL_ONLY=1` fail closed instead of selecting local sessions, profiles, tasks, Kanban, jobs or native
  Conductor state. At the A6.1 checkpoint this repository change had not restarted or redeployed the live Workspace;
  the later owner-approved A6.4 rollout is recorded below.
- **A6.2 build-1 adapter complete offline 2026-07-14.** `tools/swarm/mission_adapter.py` reuses native Hermes Kanban,
  creates one root task under a deterministic idempotency key, and emits correlated producer events for tasks,
  workers, bounded terminal output, files, tests/review and PR/deploy evidence. Fault injection proves restart without
  duplicate work/events. At the A6.2 checkpoint the adapter was not installed live; A6.4 later installed and exercised
  it once. At that A6.2 checkpoint automatic central intake-to-dispatch was absent; A7.3 later installed and accepted
  the fixed-profile timer path described below.
- **A6.3 synchronized observation live and A6.4 canary complete 2026-07-14.** `tools/hermes-mission/runtime.py` adds one
  stdlib/SQLite mission log and reducer inside the pinned central Hermes modular monolith. The pinned Hermes overlay
  adds authenticated mission API routes and Telegram `/mission`/notifications; the Workspace overlay adds a compact
  Dashboard projection with stage/progress and expandable tasks, workers, bounded terminal, changes, gates and
  delivery links. After the offline gates passed, PRs #178/#179 rolled out the exact pinned runtime and Workspace
  overlay. Mission `a6-canary-help-20260714` completed through the approved `openai-codex`/`codex_app_server` route
  with recorded author label `gpt-5.6-luna` and reviewer label `gpt-5.6-sol`. The current telemetry contract does not
  derive either model ID from a runtime event or prove the review process was OS-enforced read-only. Target PR #2
  passed CI, merged and passed fresh-main verification. Central and Workspace projections matched and Telegram reached
  the terminal cursor. Qwen/local inference, GPU, Claude, swarm, Spark and destructive tests were not used.
- **Post-A6 Codex telemetry attestation is complete offline.** `flow_contract.py summarize-codex` now binds the
  `codex exec --json` thread ID to the matching local rollout and derives the exact model, provider and sandbox policy
  from its single runtime `turn_context`. Declared-label, wrong-sandbox and reroute mismatches fail closed. Read-only
  reprocessing of the saved A6.4 author/reviewer artifacts confirmed Luna/workspace-write and Sol/read-only on Codex
  CLI `0.144.3`; the addendum is in the canary evidence. At that post-A6 checkpoint the gate was not yet wired into a
  live worker; A7.3 later used the runtime attestation live. It still does not prove an OS-independent read-only
  filesystem or credential boundary.
- **A7.1 merged and A7.2 live blocked handoff complete 2026-07-15.** PR #189 folded the reviewed bounded pull,
  starvation fix, retry/collision guards, local terminal authority, closed/redacted producer schema and owner-only
  state into `master`. PRs #190/#191 made the no-activate native root atomically sticky-blocked in pinned Hermes and
  fixed exact deployment staging. Flux is Ready at `7214ad78`; Central and build-1 carry the exact Kanban patch. Mission
  `a7-blocked-20260715-7214ad7-03` produced one blocked/unassigned root, one `task.upsert`, zero runs and a null second
  poll, with no worker/model process. At the A7.2 checkpoint the poll was manually invoked and no timer, activation or
  autonomous delivery loop was installed; A7.3 subsequently installed and accepted that path. Exact A7.2 evidence:
  `docs/evidence/a7-2-live-blocked-handoff-2026-07-15.md`.
- **A7.3 fixed-profile autonomous delivery accepted (2026-07-17).** After the earlier recoverable VPNRouter run and
  its four harness corrections (#218-#221), PR #238 was independently reviewed, passed exact-head CI, merged and was
  installed on build-1. Telegram-bound mission `a7-clean-ledger-list-20260717-a0fc5a` then ran on the corrected runtime
  from the profile timer with no manual coordinator tick or mid-run repair. The deterministic complex route used a
  runtime-attested Sol `xhigh` author and a distinct exact-SHA read-only Terra `xhigh` reviewer. The planned
  post-author-commit crash resumed without a duplicate author or candidate. Target
  [PR #5](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/5) passed Python/Linux/macOS/Windows CI, merged exact
  candidate `0389b7b...` as `811c24a...`, and fresh-main `cargo test --all-targets --locked` passed. Central and
  Workspace returned the same terminal projection hash at sequence 22, the bound Telegram cursor reached 22, and the
  task/run, branch and worktrees converged to their required cleanup state. This accepts A7.3 at the configured
  fixed-profile boundary, not as generic arbitrary-repository intake or complete cross-channel chat history. Exact
  evidence: `docs/evidence/a7-3-clean-telegram-canary-2026-07-17.md`; the earlier recovery evidence remains in
  `docs/evidence/a7-3-activation-delivery-canary-2026-07-15.md`.
- **Registered project intake and full repository inventory are live for Workspace and Telegram (2026-07-19).**
  PR #302 introduced the first three-project execution boundary. The follow-up inventory records all 33 owner GitHub
  repositories: 11 have reviewed autonomous profiles, 12 active repositories require profile setup, 3 are read-only
  and 7 are archived. Workspace shows readiness and intended Linux/Windows/macOS/test-VM targets without exposing
  commands, credentials or checkout paths. `hermes-flow-v2-pilot`, `vpnctl`, `VPNRouter`, `vpnrouter-gateway`,
  `suflyor`, `spark-runner`, `subfleet`, `slipstream-rust`, `unified-agent-platform`, `gs-ninitux` and
  `ninitux-landing` are currently
  executable; known-but-unready projects fail before mission acceptance. Workspace has
  `Settings -> Проекты и доступы` with an HttpOnly project-selection cookie. Ordinary
  Telegram text either resolves an exact project alias or durably keeps the original goal while asking for one of the
  ready projects. Build-1 has persistent one-minute timers for each registered profile; the Linux projects run local
  checks on build-1, while Suflyor's required build gate runs on GitHub Windows and Slipstream's required CI builds
  Linux x86/ARM, Windows x86/ARM and macOS Intel/ARM artifacts. This is the registered
  no-deploy boundary: a GitHub repository is not executable merely because it appears in inventory. The historical
  standalone `boosty_api_rs` entry is read-only because its active implementation is part of `vpnctl`; full cross-channel chat transcript
  replication is not claimed. Telegram voice/audio now enters the same intake through the local, checksum-pinned
  GigaAM-v3 e2e RNNT Q4 CPU preprocessor. The deployed OGG/Opus canary completed in 2.815 seconds at 222,728 KiB peak
  RSS; a second canary created one Central mission and replayed the stable Telegram source to the same receipt after a
  new `MissionStore` instance. Decode/STT failure still creates no mission. Workspace displays the Central result but
  does not yet provide a binary voice-upload control. Exact proof and allowed claims:
  `docs/evidence/local-voice-stt-rollout-2026-07-20.md`.
- **A7 observation and lifecycle baseline implemented (2026-07-17).** Workspace owns the separate owner-answer
  capability and resumes the same durable mission/root; coordinator processes explicitly lack that key. Central keeps
  the latest 100 unbound terminal mission histories while protecting the currently bound mission; payload-free
  tombstones prevent reuse of retired stable IDs. Terminal pruning also removes obsolete subscription-history
  references. Successful and exhausted deliveries archive their native Kanban
  task. Hermes' existing 30-day event/log GC runs only while the board has no nonterminal task and is retried when
  deferred, preventing cleanup from truncating a long-running worker log. Removing 30-day delivery state requires a
  separate successful GC checkpoint after that deadline; an earlier completion-time GC is not sufficient. A legacy
  task first archived during migration keeps its retry state until that new archive event is 30 days old. Delivery
  evidence remains owner-only for 30 days; deliveries remove disposable worktrees immediately. Central DB/WAL/SHM,
  adapter state and the common state root are owner-only on POSIX.
  PRs #235/#236 are deployed centrally and on build-1; exact rollout evidence is in
  `docs/evidence/a7-lifecycle-rollout-2026-07-17.md`. The Telegram-bound non-toy acceptance canary subsequently passed;
  no additional lifecycle service is required for the fixed-profile A7.3 boundary.
- **Central terminal authority is transport-independent (2026-07-18).** Delivery/rejection gates now cause Central
  to atomically commit the authoritative terminal event without requiring a Workspace client, Telegram subscriber or
  notification checkpoint. Telegram leases and cursors deliver that already-committed event at least once; an outage
  leaves the mission terminal, while the existing persistent profile poll drains one pending terminal outbox event on
  later ticks until only the lagging cursors catch up. Repair missions keep their inherited binding until their
  committed terminal update is checkpointed. Restart, expired-lease, partial-send, late-subscription and
  single-terminal regression tests cover the boundary. The two ordinary Workspace missions on 2026-07-18 then each
  committed exactly one terminal event without a Telegram delivery prerequisite, providing live success-path rollout
  evidence; Telegram-outage recovery remains covered hermetically rather than by that campaign.
- **OpenAI autonomy policy is explicit and fail-closed (2026-07-15, ADR-031).** `flow_contract.py delivery-route`
  deterministically maps closed repo-contract signals to standing-approved Luna/Sol (`standard`), Sol/Terra
  (`complex`) or Terra/Sol (`escalated`) author/reviewer sessions. Ordinary subscription spend, reasoning effort,
  retry and escalation require no owner confirmation. Unknown signals and genuinely privileged flags remain blocked;
  Claude, local inference and GPU are outside this route. PR #216 installed `openai-autonomy-v1` and atomically
  migrated the stopped build-1 profile to schema v3/three cycles. Current source `openai-autonomy-v2` additionally
  treats failed author gates, independent-review rejection and required-CI failure as durable quality failures: the next
  tick automatically raises the OpenAI route. Before a PR exists, exhausted author gates retain only redacted bounded
  diagnostics and terminate after local cleanup without PR evidence. Once a PR exists, the coordinator repairs the same
  durably bound PR. Both successful and failed CI retain only bounded name/outcome metadata. PR number/head/base are
  durable identity and repair pushes use an exact prior-head lease. Final post-PR failure requires a live Kanban claim and
  exact PR identity. Because GitHub has no server-side conditional close,
  an open failed PR and exact remote branch are preserved as bounded evidence while local disposable state is cleaned;
  if the PR is already closed, only its unchanged branch/head is lease-deleted. Compatible in-progress v1 route
  and PR identity remain recoverable, including lost responses after the initial push, PR create or a successful
  repair push.
  The coordinator treats the exact trusted pre-turn Codex capacity terminal as an operational, non-quality condition:
  two same-model retries precede an author-only whole-route fallback, while reviewer retries remain frozen to the exact
  candidate route. Retry/fallback/round state and `not_before` are durable, capped rounds never create an owner
  question; cooldown parks the exact task as `scheduled` and automatically claims a new run when due, so the finite
  Kanban claim TTL cannot strand a capacity wait. Unknown, post-start or worktree-changing failures remain fail-closed.
  Hermetic tests cover exact-source classification, restart persistence, approved route pairing and reviewer freeze.
  PRs #259/#260 deployed the bounded `mission.notice` projection to Central, Workspace and Telegram. A later ordinary
  Telegram mission fired a controlled wrapper with the exact pre-turn CLI capacity phrase, recovered on the first
  same-model Sol retry with `owner_action_required=false`, then completed author/review/PR/CI/merge/post-verify/cleanup
  and terminal sequence 27 without an owner question or quality-failure increment. This proves the deployed controlled
  recovery path, not a naturally occurring provider-capacity envelope, `capacity_wait`, burst exhaustion or
  whole-route fallback. Exact evidence:
  `docs/evidence/automatic-capacity-observation-rollout-2026-07-18.md` and
  `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
  The campaign also proved that capacity retries legitimately leave historical `scheduled` worker projections. PR
  #273 changed Central completion from “exactly one worker total” to “zero or more ordered scheduled workers followed
  by exactly one successful terminal worker”; running, failed, malformed and multiple-terminal histories still block.
  Flux applied exact merge `9cb7546...`; the rolled pod was Ready with zero restarts and mounted runtime hash
  `7198fe7c...`. The next natural tick appended the single sequence-27 `mission.completed` event.
  The deployed coordinator now places every reviewer Codex process in a transient user-systemd unit
  bound to its parent coordinator. The Linux mount namespace is read-only except for the mission-local model home
  and Codex runtime home; the candidate/source/state paths are explicitly read-only, common credential stores and
  control-plane environment names are inaccessible, `/proc` hides unrelated processes, and `PrivateTmp` separates
  scratch data. PR #266 passed required CI and exact merge `a0d8f391...` is installed on build-1. Source/installed
  coordinator and systemd-unit hashes match, all five timers resumed, and the installed exact-wrapper probe denied
  writes outside the two approved homes while hiding the actual delivery credential file, unrelated `/proc` and
  user-runtime IPC. The first real reviewer attempt exposed an ordering deadlock: `After=` made the transient child
  wait for its still-activating Type=oneshot parent while the parent waited for review. PR #271 retained `BindsTo=` but
  removed that ordering edge. Recovery then correctly quarantined the interrupted reviewer, exposing that the durable
  `reconciling` state had no convergence transition. PR #272 added reviewer-only retry after proving the old transient
  unit was unloaded, the read-only checkout was clean at the exact candidate and the draft PR was unchanged. Author
  ambiguity remains fail-closed. Exact merge `ea597a9...` is installed on build-1, and the same mission then completed
  a real runtime-attested Terra `xhigh` read-only review of candidate `255d4e46...` inside the corrected transient unit,
  followed by green CI and exact-head merge. Exact evidence:
  `docs/evidence/reviewer-os-isolation-rollout-2026-07-18.md` and
  `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
  The installed coordinator now applies the same parent-bound namespace to author Codex turns. The author receives one
  additional writable path—its deterministic disposable worktree—while source checkout, sibling worktrees and mission state
  remain read-only; common credentials, control-plane environment, unrelated `/proc` and the user runtime remain
  hidden. PR #279 passed required CI, exact merge `fd5199d...` is installed, source/installed coordinator hashes match,
  the installed adversarial wrapper probe passed and all five timers resumed. A controlled real Sol `xhigh` author
  changed only its allowed disposable file and passed rollout-derived OpenAI/workspace-write attestation inside the
  boundary. Ordinary owner-gated mission `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` then completed Sol
  authoring, Terra review, PR #9, CI, merge, post-verify and cleanup on that installed boundary. Exact evidence:
  `docs/evidence/author-os-isolation-rollout-2026-07-19.md` and
  `docs/evidence/automatic-owner-question-live-canary-2026-07-19.md`.
  Central dispatch admission also keeps one serial execution lane per exact profile: while a nonterminal mission has
  a projected task, later accepted missions remain durable FIFO candidates but are not handed off. A hermetic
  MissionStore/adapter restart test proves that the successor receives a distinct root only after the predecessor is
  terminal; live multi-mission evidence remains pending.
  It then cleans disposable state and records terminal failure. PR #217 merged and the schema-v3 live profile used
  `openai-autonomy-v2` for the successful seventh canary. The later Telegram-bound acceptance canary passed on the
  corrected runtime; channel/session work beyond the authoritative mission projection remains a separate product gap.
- **Delivery applicability is explicit for the registered pilot (2026-07-18).** Its server-owned intake route and
  schema-v4 profile declare immutable `delivery_mode: none`. Central completion now additionally requires the
  coordinator's `delivery: not_applicable` event, so fresh-main post-verify cannot masquerade as a deployment. Existing
  missions without the field preserve their legacy completion contract. `deploy` and `release` route declarations
  fail before mission acceptance/profile activation until exact artifact, environment, deployed-revision and health
  gates are implemented; this closes applicability for the no-deploy pilot, not generic deployment automation.
  Exact PR/CI/Flux/build-1 rollout evidence:
  `docs/evidence/registered-delivery-applicability-rollout-2026-07-18.md`.
- **Canonical completion evidence is deployed and the first live bundle passed (2026-07-18).** The registered
  schema-v4 profile opts into one owner-only `completion-evidence.json` written only after Central terminal, cleanup
  and Kanban archive. Its closed schema binds the mission and immutable goal digest to canonical profile/policy/runtime
  hashes, a restart-safe systemd invocation hash-chain, exact candidate/review/PR/CI/merge/default identities,
  runtime-attested distinct author/reviewer sessions, post-verify, cleanup and the terminal Central projection. A
  deterministic CLI rejects changed bytes and recomputed semantic violations; restart verifies rather than rewrites a
  completed bundle. PR #268 passed required CI and exact merge `83f193ae...` is installed on build-1. Source/installed
  hashes match and all five timers are active. Ordinary Telegram mission
  `mission-intake-0c72cde02b5ef62972a30bc998f316b9` later reached terminal sequence 27 and produced a private bundle
  with semantic digest `d05c16b7...`; the installed independent verifier returned
  `hermes-flow-completion-evidence-ok`. It binds the exact Sol/Terra sessions, candidate, target PR #8, CI run
  `29659412330`, merge/default, post-verify, cleanup and terminal projection. That already emitted live bundle remains
  schema v1 and therefore does not contain input lineage.
  Exact evidence: `docs/evidence/canonical-completion-evidence-rollout-2026-07-18.md` and
  `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
  PR #275 deploys closed bundle schema v2 for registered ordinary intake: Central persists only the
  server-owned `workspace`/`telegram` platform plus full source-key and source-message SHA-256 values, the verifier
  requires the source-key prefix to match deterministic `mission-intake-*`, and existing v1 bundles remain valid.
  Flux exact-SHA rollout, in-pod deterministic/replay proof, build-1 exact installation and installed v1/v2 verifier
  checks passed. Owner-gated Telegram mission `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` then produced the
  first live v2 bundle; the installed verifier accepted semantic digest `4dbb3b92...`. The bundle binds input lineage,
  owner-answer hash and five systemd service invocations. Exact evidence:
  `docs/evidence/completion-input-lineage-rollout-2026-07-18.md` and
  `docs/evidence/automatic-owner-question-live-canary-2026-07-19.md`.
- **The exact registered no-deploy two-channel completion certificate is GitHub-attested (2026-07-19).** PR #295
  published the closed schema-v3 bundle for mission `mission-intake-503332fe3dcba802ded5f3a1bd513026`. It binds
  ordinary Telegram intake, the exact ordinary Workspace owner answer, both channel cursors at sequence 27 and the
  same projection `bc4fe1095ad47411`, plus Sol/Terra runtime attestations, target PR #11, required multi-platform CI,
  exact merge/default `290ed192...`, explicit no-deploy applicability, post-verify and cleanup. Independent exact-SHA
  Sol read-only review and PR/master CI passed. The protected-master workflow re-ran the semantic verifier and issued
  SLSA provenance for certificate byte digest `92178a9b...`, merge `a127994...`, `refs/heads/master` and the exact
  GitHub-hosted signer workflow. PR #296 then restored ordinary Telegram intake to the automatic registered-v4 profile;
  its independent review, PR/master CI, exact Flux rollout, Ready pod, authenticated API 200 and natural registered
  timer tick passed. The owner-gate profile remains only for deliberate privileged-flow diagnostics. Generic
  repository/profile discovery, actual deploy/release modes, complete cross-channel chat history, HA and a
  platform-wide GPU/local-runtime deny remain outside this exact proof. Exact evidence:
  `docs/evidence/signed-completion-attestation-2026-07-19.md`.
- **Owner terminal result has a live concrete shared result (2026-07-19).** The earlier successful ordinary Telegram
  campaign ended with `Delivery completed, merged, and verified`, while the useful facts existed durably but were not
  rendered to the owner: the implemented `summary` behavior, changed API/CLI/tests/README, target PR #8, green
  multi-platform CI and merged revision. Current source replaces the constant at Central's single terminal-authority
  boundary with one bounded deterministic result built from the accepted goal plus projected changed paths, PR,
  verified default revision, required gates and delivery applicability. Workspace and Telegram already render that
  same projection; no new model call or channel-specific state is added. PR #277 passed required CI, Flux applied exact
  merge `40255f04...`, mounted runtime bytes matched and an in-pod temporary-store assertion passed. Mission
  `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` later delivered the first live concrete result with its accepted
  goal, PR #9, merge, gates, delivery applicability and four changed paths. Exact evidence:
  `docs/evidence/concrete-terminal-result-rollout-2026-07-19.md` and
  `docs/evidence/automatic-owner-question-live-canary-2026-07-19.md`.
- **Interrupted-author recovery and clearer Russian progress are deployed (2026-07-19).** PR #299 closes the final
  audit P2 where an ambiguous author unit was gone and its disposable worktree had also disappeared: the mission now
  follows one restart-safe execution-failure/cleanup/archive path without another author or quality escalation.
  Telegram and Workspace localize existing stage, notice, question and terminal fields without changing durable
  protocol identities. The first Workspace upgrade stopped fail-closed on its exact predecessor hash; PR #300 added
  that single compatibility hash plus a regression. Flux is Ready at `97e6fb4...`, Central and build-1 hashes match,
  the Workspace production build/HTTP check passed, and all six timers completed a natural successful tick. Exact
  evidence: `docs/evidence/interrupted-author-and-russian-progress-rollout-2026-07-19.md`.
- **Ordinary bound Telegram owner answers passed live (2026-07-19).** The ordinary Telegram ingress
  now reuses `MissionStore.ingest_owner_turn()`: when that exact chat/topic is bound to a `waiting_owner` mission, its
  stable platform message becomes the answer to the open question rather than a second mission. The source message
  ID is persisted in `mission.answer`, so restart/lost-response replay returns the same event and a changed replay
  fails closed. PR #264 passed CI, Flux applied exact merge `4cd2c60f...`, the rolled pod's mounted hashes matched the
  merged runtime and pinned overlay outputs, API health returned 200 and an in-pod temporary-store scenario passed.
  The owner-gated live canary then rejected unrelated `/approve`, stored exact ordinary `APPROVE` once, resumed the
  same root and completed delivery. A later Telegram-origin mission accepted its ordinary answer through Workspace and
  completed the same delivery lifecycle; complete cross-channel transcript synchronization is not claimed. Exact
  evidence:
  `docs/evidence/ordinary-bound-telegram-answer-rollout-2026-07-18.md` and
  `docs/evidence/automatic-owner-question-live-canary-2026-07-19.md` and
  `docs/evidence/cross-channel-owner-answer-live-canary-2026-07-19.md`.
- **Ordinary Workspace owner answers passed a live cross-channel canary (2026-07-19).** A later ordinary message in
  the exact Central session that accepted a mission now answers its single open question through
  `MissionStore.ingest_owner_turn()` instead of creating a second goal. The stable source message ID survives restart
  and delayed replay, changed text collides fail-closed, and multiple open questions are rejected rather than guessed.
  The existing structured answer action remains compatible. PR #270 passed CI, Flux applied exact merge
  `5d95eada...`, the mounted runtime/overlay hashes matched and an in-pod temporary-store scenario returned
  `live-workspace-answer-component-ok`. Telegram-origin mission
  `mission-intake-e966529d2686998b2c8f55acd06716a8` then stored one ordinary Workspace `APPROVE` as event 4, resumed
  root `t_a68746e4`, and completed target PR #10, terminal sequence 27 and cleanup. Exact evidence:
  `docs/evidence/ordinary-workspace-owner-answer-rollout-2026-07-18.md` and
  `docs/evidence/cross-channel-owner-answer-live-canary-2026-07-19.md`.
- **Automatic pre-execution owner-question production passed live (2026-07-19).** An approved-profile
  `architecture_change` now creates/reconciles one inert sticky-blocked root before publishing a deterministic
  `mission.question` bound to mission/goal/policy identity. Central accepts only exact `APPROVE`; response loss and
  restart converge on the same question/root, then the durable answer resumes that root and the approved flag is
  removed only from the exact route calculation. Local/GPU, new provider, credentials and destructive flags remain
  fail-closed. PRs #281-#283 passed CI and were installed through exact Flux/build-1 rollout. Ordinary Telegram mission
  `mission-intake-ae5dcea53ec9e8419aa15ca01b0228fd` produced the question before any model, accepted exact ordinary
  `APPROVE`, resumed the same root and completed PR #9 through terminal and cleanup. A second Telegram-origin mission
  accepted ordinary `APPROVE` through Workspace, resumed its same root and completed PR #10 through terminal sequence
  27 and cleanup. Exact evidence: `docs/evidence/automatic-owner-question-live-canary-2026-07-19.md` and
  `docs/evidence/cross-channel-owner-answer-live-canary-2026-07-19.md`.
- **Missing coordinator state now fails closed on build-1 (2026-07-19).** PR #286 prevents an active or previously
  executed mission from silently reinitializing as fresh when `delivery-state.json` is absent. Projected execution
  history, surviving mission-local artifacts and a lost automatic owner-gate checkpoint stop before model/Git/GitHub
  mutation; only pristine admission and the existing inert generic `waiting_owner` recovery remain valid. The exact
  merge `4eaa8f9...` is installed, source and installed coordinator hashes match, installer/check/systemd verification
  passed, and all six enabled timers completed a natural successful tick. This is fail-closed detection, not automatic
  reconstruction after total state loss. Evidence:
  `docs/evidence/missing-delivery-state-fail-closed-rollout-2026-07-19.md`.
- HA status: **not HA ready and deferred indefinitely by owner decision (2026-07-12)**. Two local k3s VMs
  (one server/control-plane, one agent) = a single etcd member. The active strategy is one control-plane,
  R2 backups, and the verified restore drill; adding a third server is not an active owner action.
- k3s status: **local bootstrap running on `uap-home-1` with `uap-home-2` joined as an agent**.
- **Cross-node Secret restore: PASS 2026-07-12.** A snapshot created after a throwaway canary Secret was fetched
  back from R2 and restored on clean `debian-xfce` with only the snapshot + original server token. The snapshot
  supplied the encryption config automatically and the Secret value matched byte-for-byte. All canary resources,
  credentials, k3s state and the test snapshot were removed; production and the target returned healthy.
- **Brain reality (current, since 2026-07-11):** the live hermes-agent brain is **Codex `gpt-5.6-luna`** through
  `codex_app_server` (`provider: openai-codex`). Owner device-auth restored the ChatGPT-Plus OAuth lineage; an
  explicit in-pod Luna probe returned `LUNA-PROBE-OK`. The ops-1 `qwen-35b`/`ornith-9b` local-models-router, which served as
  brain from 2026-07-06 through 2026-07-11, remains the documented manual fallback. Coding delegation stays on build-1.
- ✅ **Quality gate is ENFORCED.** The owner does not review code; the agent's self-test + CI **is** the gate, and it
  is now enforced. The repo is **public**, the GitHub ruleset `protect-master` is **active**, a PR is **required**, and
  the `static-checks` CI check (`.github/workflows/ci.yml`) is a **required (strict) status check** — direct push to
  `master` is **BLOCKED**. Deploys are PR-gated: branch → PR → green `static-checks` → merge → Flux reconciles `master`
  (`prune:true`). Human code review remains absent by design. See `docs/next-steps.md` (Platform hardening).
- **Post-A4 hardening pass — DONE 2026-06-28** (against the Codex bug-hunt, `BUG-HUNT-CODEX-2026-06-28.md`).
  8 items **merged** (each independently reviewed): secret-scan SOPS hole (structural `ENC[` check +
  provider-token patterns + fixtures now run in CI), backup completeness (root dump, no pipe-masking,
  expected-file manifest), this doc-set's drift, `hermes-legacy` **parked** + documented, `validate_iac`
  orphan path-bug, `verify-local` `-Require` (false-green), `configure-github-flux.sh` ADR-026 alignment,
  and a PV-`Retain` DR live-smoke (`tests/ops/check-pv-reclaim.ps1`). **#35** (pin hermes-agent runtime —
  image digest = v0.17.0, `codex@0.142.0`, `claude@2.1.193`, rclone digest — + harden: no-RBAC SA,
  `automountServiceAccountToken:false`, seccomp RuntimeDefault, TCP probes) and **#36** (harden
  `singbox-egress-ha`: drop-all-caps, seccomp, no-RBAC SA, TCP probes) are **MERGED + live** (owner-merged
  2026-06-30, rolled and verified — see the follow-up below). `runAsNonRoot`/cap-drop on the agent pod
  remain deferred + documented (s6 needs root; Codex runs danger-full-access).
- **2026-06-30 follow-up:** caught and fixed a real regression before the owner could hit it — PR #35 was
  branched before #38 merged and reverted #38's warn-not-fatal backup fix back to FATAL ("root avoids
  skips" is false: `hermes backup` drops to uid 10000 internally regardless of dump-container privileges).
  GitHub's mergeable check was stale (computed pre-#38); a local rebase surfaced the real conflict. Pushed
  a correction onto `chore/pin-harden-hermes-agent` (commit `dafa3f9`) that keeps #38's logic and only the
  legitimate digest pins. At that checkpoint PR #35 was mergeable + green and PR #36 was unaffected; both merged
  later on 2026-06-30. Also committed the 3 local-only Codex audit docs that never made it into git (PR #39,
  merged) and closed the doc gaps they exposed: a stale CLAUDE.md bug-hunt pointer, and a 5th hermes-legacy
  finding (summarizer drops the untrusted-tool-result boundary) missing from `hermes/README.md`'s
  accepted-as-parked-risk list. Ported the BOM-proof base64 SSH transport to `check-ops-node.ps1` /
  `check-ops-deploy-path.ps1`, and in the process found it had also silently broken the already-merged
  `check-pv-reclaim.ps1`: `.gitattributes` forces `*.ps1` to CRLF on a Windows checkout, and the stray
  `\r` corrupts the remote bash parse. Fixed all three by stripping CR before base64-encoding (PR #40,
  merged). Also added (owner-approved): seed-if-absent install of the
  [ponytail](https://github.com/DietrichGebert/ponytail) anti-overengineering coding skill (native Hermes
  plugin, `full` mode) into hermes-agent's boot initContainer — bundled into PR #35 rather than a
  competing PR on the same file. Dependabot #1-4 remained open at that checkpoint; exact current-major commit pins
  and a regression rejecting every mutable remote Action ref were added on 2026-07-19 without a major-version upgrade.
- **2026-06-30 PR #35/#36 merged + rolled — post-roll verify DONE.** `hermes-agent`: pod 1/1 Running,
  `hermes --version`/`codex --version`/`claude --version` match the pins exactly, dedicated SA +
  `automountServiceAccountToken:false` live, `tests/ops/check-pv-reclaim.ps1 -Require` →
  `pv-reclaim-ok`, ponytail installed at `/opt/data/plugins/ponytail` and **enabled** on first real boot
  (`hermes plugins list` confirmed it then). On 2026-07-12 it was found installed but disabled, so the owner chose
  to remove the dead plugin/bootstrap and retain only two concise managed coding/report rules. `claude -p` verified
  working end-to-end. `singbox-egress-ha`: pod
  1/1 Running, `sing-box check` valid, reachability confirmed from inside hermes-agent (telegram=302,
  chatgpt=403 — the expected signature). The Codex OAuth later expired because of its single-use refresh-token
  lineage; the local router carried the brain from 2026-07-06 until owner device-auth restored Codex on 2026-07-11
  (#119). `claude -p` uses separate OAuth and was unaffected.
- **Egress ops hardening — DONE 2026-07-10** (the vpnrouter-gateway goal, `docs/research/vpnrouter-gateway-egress-goal.md` §10).
  Phase 0 verdict (#107): `vpnrouter-gateway` is a TUN/L3 LAN gateway — it cannot render our HTTP-CONNECT-proxy
  egress (no `mixed`/`:12080` inbound, no `urltest`, always emits `direct`), so Level 1/2 adoption = no-go; the
  dependency-free alternative was adopted instead. Shipped: **SNI pre-flight gate** in
  `infra/sops/gen-singbox-failover.py` (#108) — `--against <deployed>` diffs fresh-vs-deployed servers keyed by
  `(host, port)` (the subscription renames nodes), FAILS CLOSED (exit 3) on any REALITY `server_name` change or
  pool add/remove; ack = `--allow-sni-drift` / `ALLOW_SNI_DRIFT=1`; regression test in CI (`tests/static/`).
  **Decrypt-verify guard** in the regen runbook (#109) — the freshly-encrypted `.sops.yaml` is piped into
  `sops -d` on `uap-home-1` BEFORE the PR, so a transport-corrupted secret fails locally instead of as Flux
  "no identity matched" post-merge. **First real rotation through the new pipeline (#110):** the gate caught the
  deployed pool lagging the subscription (+United States VLESS), acked → 7-server secret + `config-rev`
  v3-7servers → Flux rolled the pod → verified live from build-1 through the new pod (telegram=302,
  anthropic=401, exit IP non-RU); hermes Telegram long-poll auto-reconnected with no escalation. The 2026-07-09
  incident class (silent SNI drift, corrupted secret transport, blind config edit) is now surfaced/blocked at
  authoring time.

## Proxmox

- Endpoint: `https://192.168.0.169:8006/` (local LAN only).
- Proxmox version observed: `8.4.1`.
- Online nodes:
  - `pve-ninitux`
  - `pve-ninitux2`
  - `pve-ninitux3`
- Shared storage used: `nfs-share`.
- Backup-only storage: `backup-pve2` on the separate `pve-ninitux2` disk; clients are only
  `pve-ninitux` and `pve-ninitux3` (no self-mount).
- Bridge used: `vmbr0`.
- Storage change made: `nfs-share` content types now include `import` so cloud images can be imported.
- **Proxmox VM backups DONE 2026-07-13:** cluster job `uap-critical-daily` backs up VMIDs
  `102/201/202/203` at `03:15` with snapshot mode, zstd, 50 MiB/s cap and retention
  `keep-last=2,keep-weekly=2,keep-monthly=1`. VM203 produced a 2.03 GB archive from a 30 GB disk;
  `zstd -t`, isolated restore to an unstarted disposable VMID, and `qemu-img check` passed. Cleanup passed.
  `uap-healthcheck.timer` sends missing/stale failures and one successful size/free-space report per day
  to the owner's existing Telegram chat after `05:00 Europe/Moscow`; delivery test passed.

## Local VMs

| VMID | Name | Proxmox node | IP | Resources | Status |
|---|---|---|---|---|---|
| 201 | `uap-home-1` | `pve-ninitux` | `192.168.0.201` | 4 vCPU, 8 GB RAM, 80 GB disk | running |
| 202 | `uap-home-2` | `pve-ninitux3` | `192.168.0.202` | 6 vCPU, 8 GB RAM, 32 GB disk | running |
| 203 | `uap-ops-1` | `pve-ninitux` | `192.168.0.203` | 2 vCPU, 2 GB RAM, 30 GB disk | running |
| 102 | `uap-build-1` | `pve-ninitux3` | `192.168.0.99` | 8 vCPU, 16 GB RAM, 100 GB disk | running |

`uap-home-2` was resized to 6 vCPU / 8 GB (#86/#87). `uap-build-1` (VMID 102) is an **always-on Ubuntu 22.04 dev/build
VM** — **not a k3s node and not in GitOps**; it hosts the build-1 track services (see "Build-1 track" below).

## Tailnet

| Device | Tailnet name | Tailnet IP |
|---|---|---|
| `uap-home-1` | `uap-home-1.tail9fd337.ts.net` | `100.106.223.120` |
| `uap-home-2` | `uap-home-2.tail9fd337.ts.net` | `100.94.228.67` |
| `uap-ops-1` | `uap-ops-1.tail9fd337.ts.net` | `100.82.241.121` |
| `uap-build-1` | `uap-build-1.tail9fd337.ts.net` | `100.85.56.31` |
| Windows | `desktop-m922ij2.tail9fd337.ts.net` | `100.114.172.40` |
| Mac | `pavels-mac-mini.tail9fd337.ts.net` | `100.116.97.112` |

## VM Baseline

- OS: Debian 12 (bookworm).
- User: `uap`.
- SSH keys: from `infra/ssh/agent-authorized-keys.pub`.
- SSH hardening:
  - `PasswordAuthentication no`
  - `PermitRootLogin no`
- `sudo -n true`: verified for user `uap`.
- `qemu-guest-agent`: installed and active.
- Tailscale: installed and authenticated.

## k3s

- Server installed on: `uap-home-1`.
- Agent installed on: `uap-home-2`.
- Version: `v1.35.5+k3s1`.
- Runtime: `containerd://2.2.3-k3s1`.
- Server internal IP: `100.106.223.120`.
- Agent internal IP: `100.94.228.67`.
- Config tracked at:
  - `infra/k3s/uap-home-1.config.yaml`
  - `infra/k3s/uap-home-2.agent.config.yaml`
- Local credential file: `kubeconfig.uap-home-1` (ignored by git).
- System pods verified Ready:
  - `coredns`
  - `local-path-provisioner`
  - `metrics-server`
- Smoke deployment verified with `registry.k8s.io/pause:3.10`.
- `uap-home-2` can reach `uap-home-1:6443` over tailnet.
- Scheduling on `uap-home-2` verified with a targeted `registry.k8s.io/pause:3.10` pod.
- Reboot test: passed. `uap-home-1` rebooted and k3s returned Ready.
- Manual etcd snapshot created and listed:
  - `uap-local-20260617T134555Z-uap-home-1-1781703956`
  - size: `1646624` bytes

## GitOps

- Flux installed: `v2.8.8`.
- Runtime controllers installed:
  - `source-controller`
  - `kustomize-controller`
  - `helm-controller`
  - `notification-controller`
- Image automation controllers are intentionally not installed.
- Flux manifests are pinned in `clusters/prod/flux-system/gotk-components.yaml`.
- SOPS/age configured:
  - public recipient stored in `.sops.yaml`;
  - private age key stored outside git on `uap-home-1`;
  - Kubernetes Secret: `flux-system/sops-age`.
- SOPS CLI installed on `uap-home-1`: `v3.13.1`.
- SOPS smoke fixture: `clusters/prod/infra/sops-smoke.sops.yaml`.
- SOPS decrypt smoke: passed with the node-local age key.
- Namespace applied from skeleton:
  - `uap-system`
- Flux Git sync **active**: `GitRepository` + `Kustomization` `uap-platform` reconcile `clusters/prod` from the
  GitHub remote via a read-only SSH deploy key + SOPS decryption. First real SOPS secret applied by Flux:
  `k3s-etcd-snapshot-s3-config` in `kube-system`.

## Model & Agent Layer (LIVE — 2026-06-23)

The model + agent value layers are deployed in namespace `uap-system`. **All of them are now Flux-reconciled**
(verified against `clusters/prod/infra/kustomization.yaml`): `litellm.yaml`, `litellm-keys.sops.yaml`, `hermes.yaml`,
`hermes-keys.sops.yaml`, and every hermes-agent manifest are referenced by the kustomization. **B0 is DONE.**

- **subfleet** (Flux-managed): wraps the **Claude subscription** as an OpenAI-compatible **chat** API (spawns the
  bundled `claude` CLI per request; drops `tools`/`tool_calls`). `subfleet-bridge.uap-system.svc:18902`. Egress to
  Anthropic via the in-cluster `singbox-egress` (VLESS+REALITY, ADR-018). Retained for the owner's **other**
  projects (a Telegram bot + web sessions); it is not an automatic route in current ADR-031 UAP Flow delivery.
- **LiteLLM** v1.89.0 — deployed + smoke-verified, **Flux-reconciled** (`clusters/prod/infra/litellm.yaml` +
  `litellm-keys.sops.yaml` are now referenced by the kustomization). OpenAI gateway, groups
  `smart-cloud`/`-think`/`balanced-cloud`/`cheap-cloud`/`smart-cloud-pinned`; tailnet via `tailscale serve` on
  `uap-home-1`; `opus-4-8` verified end-to-end.
- **Hermes-legacy** (bespoke `hermes/hermes.py`) — deployed + smoke-verified, now **Flux-reconciled** (`hermes.yaml`
  + its `hermes-keys` SOPS Secret are referenced by the kustomization). Prompt-based ReAct/ReWOO tool agent,
  NodePort `:30890`, 41 unit + 8 integration tests. **PARKED** — superseded by the external hermes-agent direction.

LiteLLM/Hermes and the hermes-agent stack are now *running + verified* **and** *reconciled by GitOps* — **B0 is DONE**
(see `docs/next-steps.md`).

## Local FC Brain — Track A1 (PROVEN 2026-06-23)

Phase A1 of the hermes-agent pilot: a **local, native-function-calling** brain on the RTX, no cloud egress.

- **Host:** `desktop-m922ij2` (RTX 5060 Ti 16 GB, Blackwell sm_120, driver 610.62 / CUDA 13.3); **not always-on**, so
  this historical A1 brain is **opportunistic**. It is not the current durable brain: since 2026-07-11 Central Hermes
  uses Codex Luna, while the ops-1 `qwen-35b`/`ornith-9b` router is only a manual fallback (see "Brain reality" in
  Phase).
- **Stack:** **Ollama 0.16.1** (native Windows) serving **`gpt-oss:20b`** — already on disk, so **no model download
  over the RU network**. Chosen over a fresh Hermes/Qwen pull for that reason; `--tool-call-parser hermes` (vLLM) /
  `--jinja` (llama.cpp) are the equivalents if a Hermes/Qwen GGUF is swapped in. **WSL2/Docker are NOT installed**, so
  vLLM-in-WSL2 is deferred (heaviest path).
- **Proof (the A1 "Done" gate):** against `http://127.0.0.1:11434/v1/chat/completions` with a `tools` array, the model
  returns a **structured `tool_calls`** object — `get_weather({"city":"Paris"})`, `finish_reason=tool_calls` — **not
  text**; feeding the tool result back yields a correct final answer (`finish_reason=stop`); a bare greeting yields
  **no** tool call. Served `context_length=65536` (>= 64k), **100% GPU**, ~14.7 GB VRAM (`/api/ps`).
- **Reproduce:** `powershell -ExecutionPolicy Bypass -File .\tests\smoke\local-fc-toolcall.ps1 -StartOllama` →
  `local-fc-toolcall-ok`. Runbook: `runbooks/local-fc-model.md`.
- **Not yet done (Phase A2):** running hermes-agent itself against this endpoint (bind Ollama to the tailnet +
  `security.allow_private_urls: true` for the CGNAT `100.64/10` range). A1 proves the *endpoint contract*, not the
  hermes-agent startup/run.

## hermes-agent — Track A2 (DEPLOYED + verified 2026-06-24)

Phase A2: the external NousResearch **hermes-agent** gateway as a Flux-managed k3s workload, brain = the **Codex /
ChatGPT-Plus subscription** (`codex_app_server`) reached through `singbox-egress`. Owner chose the GitOps/k3s path
over bare Docker.

> **Current again since 2026-07-11 (#119).** Codex `gpt-5.6-luna` is the live brain after owner re-auth and the
> owner's cost-sensitive model switch. The local
> `qwen-35b`/`ornith-9b` interval (2026-07-06 through 2026-07-11) proved the manual fallback path; its router and
> runbook remain available. See "Brain reality" above.

- **Proven in the real image (2026-06-24):** running `nousresearch/hermes-agent:latest` (v0.17.0) in-cluster,
  `hermes chat -q` drove the Codex brain (gpt-5.5) to **execute a tool end-to-end** (wrote a `BRAIN-OK` file). The
  Codex subscription reaches OpenAI through the cluster egress (chatgpt.com); raw `curl` probes are unfaithful
  (Cloudflare resets curl's TLS fingerprint, not the real Rust codex CLI).
- **Deployed via Flux (PR #8, merged):** `Deployment hermes-agent` in `uap-system` is **1/1 Running** on
  `uap-home-2` (manifests `clusters/prod/infra/hermes-agent{,-config}.yaml` + the SOPS `codex-auth.sops.yaml`, all
  in the kustomization). The bootstrap initContainer (codex install onto the PVC + cred seed into hermes's OWN auth
  store + chown to uid 10000) succeeded; the gateway runs persistently (no messaging platform yet — that's A3). The
  4 non-obvious knobs (creds in hermes's own store, not `~/.codex`; `codex_app_server`; codex `danger-full-access`;
  uid-10000 + egress env) are in `runbooks/hermes-agent-codex-brain.md`.
- **Owner action done:** `codex login` on the desktop with the owner's own ChatGPT Plus → `~/.codex/auth.json`,
  which seeds the `codex-auth` secret.
- **Verified (A2 Done):** the `kubectl exec` round-trip **in the deployed pod** wrote `BRAIN-OK` — the brain
  (gpt-5.5) executed a tool through the egress.
- **A3 (Telegram) DONE 2026-06-24:** a message from the owner's phone round-trips through the gateway to the Codex
  brain (gpt-5.5) and back ("17×23 = 391") — the harness is now **phone-driven** (PR #10). The fix was non-obvious:
  hermes's per-profile `os.environ` is isolated (multiplex), so the egress proxy + Telegram allowlist had to go in
  hermes's **managed scope** (`/etc/hermes/.env`, loaded last with override) — which also feeds the gateway-driven
  Codex brain (codex spawn = `os.environ.copy()`). See `runbooks/hermes-agent-codex-brain.md`. **Next: A4** (coding
  skills — `claude -p` / `codex exec` — the actual vibe-coding gate).
- **Caveat:** the seed shares the Codex CLI's single-use refresh-token lineage — see the runbook (rotate/re-seed if
  the brain starts 401-ing). Hardening follow-ups: non-root, pinned GHCR image, autonomous-run permission policy.
- **Config-ownership hybrid DONE 2026-06-25 (PR #16, merged):** GitOps owns only the brain via a **managed config
  overlay** (`/etc/hermes/config.yaml`, ConfigMap key `managed-config`) that deep-merges per-leaf over the PVC config
  and WINS — `hermes config` now reports `Managed config keys: model.{provider,openai_runtime,model}` and refuses
  dashboard/CLI edits to them ("managed by your administrator"). The initContainer no longer clobbers the PVC every
  boot: `config.yaml` + codex `config.toml` are **seed-if-absent** and the bot token is **replaced in-place**
  (preserving dashboard-written `.env` lines — Discord/MCP tokens, `/sethome` chat-IDs — across restarts). A
  fail-closed guard aborts boot if the managed brain overlay is missing/malformed. So the **dashboard is now a
  durable self-serve surface** for soft config while the brain stays reproducible. Independently reviewed; pod rolled
  once to `v5-config-hybrid`, healthy. See the "Config ownership" section in `runbooks/hermes-agent-codex-brain.md`.
- **PVC DR backup DONE 2026-06-25 (PR #17, merged):** the node-local `hermes-agent-data` PVC (NOT in the etcd→R2
  snapshots) now has a daily **`CronJob hermes-agent-backup`** — FULL `hermes backup` (consistent sqlite snapshot,
  incl. the `.codex` brain DBs) → `r2:uap-k3s-snapshots/hermes-agent-backup/`, keep-7, direct to R2 (so it works
  while the egress is down). Fail-loud integrity guards (non-empty + valid zip + `.codex` present). PV flipped to
  `reclaimPolicy: Retain`. **Verified:** a manual job shipped a 40MB zip to R2. Restore + hardening follow-ups
  (client-side encryption; current shared R2 credential scope is an owner-accepted risk) in
  `runbooks/hermes-agent-dr.md`.
- **Egress outage RESOLVED 2026-06-25 (PR #19, merged) — HA failover egress.** The single German VLESS+REALITY exit
  had died server-side (`singbox-egress` logged `EOF` to chatgpt.com/api.telegram.org/ipify/dns alike), taking the
  Codex brain + Telegram offline. Fix: a **separate `singbox-egress-ha`** (Deployment + Service + SOPS config) running
  sing-box with a **`urltest`** outbound that auto-fails-over across the owner's **6-server** subscription (3 VLESS+REALITY
  + 3 WS+TLS `*.ninitux.top`, the WS exits more DPI-resistant; PR #21, verified 6/6 + `BRAIN-OK-6`) —
  probe every 30s, route the fastest LIVE server, migrate in-flight connections off a dead one; **no `direct` outbound**
  (no RU-origin leak). hermes-agent (brain + Telegram) is repointed at it (config-rev `v6-egress-ha`). **subfleet stays
  on the single-fixed `singbox-egress` (untouched)** — its OAuth is IP-pinned and must NOT sit behind a rotating egress.
  Regenerate the server list with `infra/sops/gen-singbox-failover.py` (see `runbooks/llm-egress-vless.md`). **Verified:**
  `sing-box check` valid + 12/12 live reachability (telegram 302 / chatgpt 403) pre-deploy; in-cluster the **brain
  round-trip wrote `BRAIN-OK`** and Telegram reconnected. Per-server probe: Iceland rock-solid, Germany good, Netherlands
  dead (urltest excludes it). Independently reviewed (the split fixed a subfleet IP-pin blocker).
- **subfleet egress note (updated 2026-07-09):** subfleet is **LIVE + healthy** (v0.3.1; bridge + token pods 1/1
  Running; served `claude-opus-4-8` on 2026-07-09 through the pinned `singbox-egress`). Its dead German exit was
  **rotated to a live ninitux server** (#103/#104). subfleet stays on the **single-fixed `singbox-egress`** (NOT the
  rotating HA egress) because its Claude OAuth is IP-pinned. **Only genuinely-open caveat:** the exit-IP change means the
  IP-pinned OAuth pin may need re-validation (re-run `claude setup-token` from the new exit IP) if it starts failing —
  verify on the next auth error rather than pre-emptively. Do NOT fold subfleet onto the rotating HA egress.
- **A4 (claude -p coding worker) DONE 2026-06-26 (PR #23):** Anthropic's `claude` CLI runs as an autonomous
  `claude -p` worker INSIDE the hermes-agent pod, alongside the Codex brain. Claude Max OAuth (a portable 1-year
  `claude setup-token`) was obtained via a **server-side device-flow** (run in the pod under a PTY through the egress;
  owner clicked the URL + pasted the code), stored in the SOPS secret `hermes-agent-claude`, injected as env
  `CLAUDE_CODE_OAUTH_TOKEN`. The claude CLI installs in the initContainer (seed-if-absent, mirrors codex); deny-first
  `/opt/data/.claude/settings.json` is defense-in-depth (the pod is the real boundary, Bash is unconstrained).
  **Verified in-cluster:** `claude -p` returns a result through the egress with the secret-injected token, and the
  deny rule blocks a decoy secret read. Recipe + gotchas in memory `uap-claude-worker`; config-rev `v7-claude-worker`.
  **Historical commercial checkpoint (owner update 2026-07-13):** the Claude subscription was no longer Max and its
  usage was exhausted. Since ADR-031, current Flow v2 automatic coding/review is OpenAI-only Luna/Sol/Terra; Claude is
  retained separate legacy capacity and requires an explicit owner decision.
- **A5 coding engines + worktree isolation — verified 2026-06-26:** BOTH coding engines work in-cluster —
  `codex exec "<task>"` (the 2nd engine, via the Codex auth + egress) edits files autonomously, and `claude -p -w <name>`
  runs in an **isolated git worktree** (`.claude/worktrees/<name>`, its own branch) so a coding task never touches the
  main checkout.
- **NORTH-STAR MILESTONE — A4 demo PASSED 2026-06-26 (PR #25):** the hermes-agent `claude -p` worker autonomously
  shipped a real change (a kustomization-orphan check in `validate_iac.py` + its test, 10 turns / $0.63) in an isolated
  git worktree, **self-verified** (its own test + `validate_iac` green), and it landed in `master` via the required
  `static-checks` CI — **with NO human diff review**. The thesis is proven: the worker's self-test + the enforced CI
  is the quality gate, not human review. (This run was orchestrated — task chosen + worker invoked via `kubectl exec`
  + the patch bridged to ops-1 for the push. The remaining AUTOMATION is wiring a phone message → hermes → worker →
  ops-1 push so the whole loop runs unattended from the phone.)

## Build-1 track (post-2026-06-30)

`uap-build-1` (VMID 102, `pve-ninitux3`, Ubuntu 22.04, 8c/16 GB/100 GB, LAN `192.168.0.99`, tailnet `100.85.56.31`) is
an **always-on dev/build VM** running a stack of agent services as **systemd units — NOT k3s, NOT in GitOps**, so they
are absent from the cluster sections above. Landed after the 2026-06-30 hardening pass:

- **local-models-router (#71)** — the ops-1 router that served `qwen-35b`/`ornith-9b` as the live brain from
  2026-07-06 through 2026-07-11 and remains the manual fallback (see "Brain reality" in Phase);
  `runbooks/local-models-router.md` + `docs/local-qwen-hermes-handoff.md`.
- **Knowledge system (#95/#96/#97)** — SQLite `knowledge.db` engineering-knowledge registry + local e5-large
  embeddings + a 12-status lifecycle with `--approve` gates; `runbooks/knowledge-system.md`.
- **Hermes Kanban swarm pilot (#94/#98/#99)** — native multi-agent orchestration (KB → swarm → artifacts → verify →
  synth → KB write-back, retrieval-first); `runbooks/hermes-kanban-swarm-pilot.md`.
- **hermes-workspace webcenter (#101)** — the user-facing web center on `build-1:3000` (tailnet-only).
- **A7.3 automation boundary after acceptance:** the installed profile-bound timer has now proved intake, activation,
  authoring, tests, exact-SHA read-only review, durable crash recovery, PR/CI, exact-head merge, fresh-main post-verify,
  Central/Workspace/Telegram terminal convergence and cleanup in one corrected-runtime canary. Owner answer/resume and
  the bounded lifecycle baseline are installed. Rejected projections still expose only a generic error/stage, and
  complete Workspace/Telegram chat-session history is not unified. No generic arbitrary-repository timer is enabled;
  only exact owner-approved profiles run.
- **Registered Workspace and Telegram intake/delivery accepted (2026-07-18):** PRs #248-#253 installed ordinary-message
  intake and serialized exact Central session creation; a normal Workspace goal then created
  `mission-intake-9c00cff752112583d629c1f144abadb9` and the standing timer delivered non-toy Rust code through Sol
  author, exact-SHA Terra review, multi-platform CI, PR #6, exact merge, fresh-main verification and cleanup without
  manual poll/tick/coordinator steps. That first mission exposed a real truth gap: README was requested but excluded
  by the profile and the platform still declared completion. PR #254 added only the missing approved path. A second
  normal Workspace goal created `mission-intake-f53871c022ce187501a0e9d9021b8823`; its first README candidate was
  rejected by the independent reviewer, automatically corrected, re-reviewed, merged as target PR #7 and completed
  with one terminal event and cleanup. A later normal Telegram goal created
  `mission-intake-0c72cde02b5ef62972a30bc998f316b9`, recovered from a controlled exact pre-turn capacity failure,
  completed target PR #8 and produced terminal sequence 27 plus a verified canonical bundle. That campaign installed
  three corrections while preserving the same mission, so it is strong recovery evidence rather than a clean
  frozen-runtime canary. This accepts both ordinary input channels only for the exact registered profile, not arbitrary
  repositories, full cross-channel history or a self-diagnosing single-mission repair of the first goal. Exact
  evidence: `docs/evidence/ordinary-workspace-autonomous-delivery-2026-07-18.md` and
  `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
- **Workspace durable mission replay accepted live (2026-07-18).** PR #256 replaced selected-mission snapshot-only
  observation with authenticated Central cursor replay and a sequence-validated timeline. Its first live rollout
  exposed a null first-render race; the failure is preserved, PR #257 fixed it and added an exact vulnerable-asset
  upgrade regression. After the exact hotfix merge was built and restarted on build-1, mission
  `mission-intake-f53871c022ce187501a0e9d9021b8823` rendered the same ordered 20 events, cursor 20 and single terminal
  event before and after a browser reload. That run closes Workspace mission-event reconnect; the later live
  cross-channel owner question/answer leg passed separately, while complete cross-channel chat/session history remains
  outside the claim. Exact evidence: `docs/evidence/workspace-mission-cursor-replay-2026-07-18.md` and
  `docs/evidence/cross-channel-owner-answer-live-canary-2026-07-19.md`.
- **A6 live boundary:** the canonical event contract, central-only fail-closed overlays, central runtime and build-1
  adapter are installed. Synchronized Workspace/Telegram projection and deterministic producer replay passed one
  controlled canary. This is not a soak, HA proof or approval for automatic model/GPU/swarm selection.
- **ai-search (#105)** — zero-key web-search CLI (DuckDuckGo via the VLESS proxy; exa/tavily/brave opt-in from a key
  file); `runbooks/ai-search.md`.
- **Controlled owner research (Central live-proven, channel canary pending, 2026-07-20)** — PR #323 / ADR-033
  installed the bounded, idempotent `research_session` MCP facade over a separate read-only Codex native-search run.
  Exact-domain live search, durable replay and the Central MCP call passed. A later build-1 HTTP probe exposed the API
  bearer in process diagnostics because of incorrect shell quoting; rotation revision `v65-api-credential-rotation`
  replaces every copy before Workspace/Telegram projection is claimed. Evidence:
  `docs/evidence/controlled-research-rollout-2026-07-20.md`.
- **Egress ops hardening (#108/#109/#110)** — SNI pre-flight gate + decrypt-verify guard + first gated rotation through
  the new pipeline (also summarised in the "Egress ops hardening — DONE 2026-07-10" bullet under Phase).
- **Proxy-mode spec (#112)** — the vpnrouter-gateway proxy-mode handoff spec (`docs/research/`).

## Repeatable Bootstrap

- OpenTofu/Terraform-compatible provisioning skeleton added under `infra/tofu`.
- Local Proxmox environment described at `infra/tofu/environments/local-proxmox`.
- Proxmox VM module added at `infra/tofu/modules/proxmox-vm`.
- Ansible bootstrap skeleton added under `infra/ansible`.
- Current local inventory: `infra/ansible/inventories/local.yml` uses tailnet IPs for SSH and keeps LAN IPs as metadata.
- Future 3-server template inventory: `infra/ansible/inventories/prod.example.yml`.
- Parameterized smoke-test config: `tests/smoke/uap-smoke-config.ps1`.
- Static IaC validation: `tests/static/validate-iac.ps1`.
- Unified local gate: `tests/verify-local.ps1`.
- Secret scan: `tests/static/secret-scan.ps1`.
- Validation matrix: `runbooks/validation-matrix.md`.
- Local FC brain runbook (Track A1): `runbooks/local-fc-model.md`.
- Local FC tool-call smoke test (opportunistic, GPU desktop): `tests/smoke/local-fc-toolcall.ps1`.
- Restore drill runbook: `runbooks/restore-drill.md`.
- Offsite backup runbook: `runbooks/offsite-backups.md`.
- Flux remote Git runbook: `runbooks/flux-remote-git.md`.
- Cloudflare R2 setup runbook: `runbooks/cloudflare-r2-k3s-snapshots.md`.
- Git remote readiness helper: `tests/git/check-git-remote.ps1`.
- S3 env readiness helper: `tests/s3/check-s3-env.ps1`.
- Operator node runbook: `runbooks/uap-ops-node.md`.
- Operator node bootstrap script: `infra/ops/bootstrap-ops-node.sh`.
- GitHub + Flux sync helper for the operator node: `infra/ops/configure-github-flux.sh`.
- Operator node readiness helper: `tests/ops/check-ops-node.ps1`.
- Operator deploy-path helper: `tests/ops/check-ops-deploy-path.ps1`.
- `uap-ops-1` deploy tools installed and verified:
  - `git`
  - `ansible-playbook`
  - `tofu`
  - `kubectl`
  - `flux`
  - `sops`
  - `age`
  - `gh`
  - `tailscale`
  - `jq`
- `uap-ops-1` SSH key generated on the VM and authorized on `uap-home-1` and `uap-home-2`.
  - public key fingerprint: `SHA256:fJ6yGmMjF6Mk7NC3OXqmcRu5u5h0Tp88DhglVqLJmDU`
- `uap-ops-1` is authenticated in Tailscale as `100.82.241.121`.
- LAN SSH to `uap-ops-1` is verified. Tailnet SSH to `uap-ops-1` was intermittently timing out immediately after
  enrollment, so `tests/ops/check-ops-node.ps1` still defaults to LAN until tailnet SSH is stable.
- `uap-ops-1` has a node-local kubeconfig at `~/.kube/config` with mode `0600`. The kubeconfig is not stored in git.
- `kubectl` from `uap-ops-1` can read k3s nodes and Flux deployments through the tailnet API endpoint.
- `uap-ops-1` can SSH to `uap-home-1` and `uap-home-2` over tailnet, so it is usable as the deploy/control machine.
- The ops-node git copy now has the GitHub `origin` (set up via `configure-github-flux.sh`); `master` is pushed and Flux syncs from it.
- Local workstation currently does not have `tofu`, `terraform`, or `ansible` installed, so static validation skips
  those CLI-specific checks unless the tools are installed.

## Git Remote Readiness

- GitHub `origin` configured (**public** repo `PavelLizunov/unified-agent-platform`; read-only SSH deploy key for Flux,
  plus a repo-scoped read-WRITE deploy key for pushes — both live on `uap-ops-1`); `master` pushed; `gh` authed on
  `uap-ops-1`. Direct push to `master` is blocked by the `protect-master` ruleset — deploys are PR-based (see Phase).
- The Windows workstation has a **read-only** `origin` (the public GitHub URL, added when the repo went public) for
  `git fetch`/sync only; pushes still route via `uap-ops-1` (the write deploy key lives there).
- `infra/ops/configure-github-flux.sh` was run on `uap-ops-1` to create the repo, push, add the deploy key, and create the Flux git-auth secret.
- Local Windows SSH public key exists:
  - fingerprint: `SHA256:YLFbDMRbeUldpLQW8dmMihAQbRgCVBhmQGTW98rgm9c`
  - comment: `windows`
- GitHub and Bitbucket did not accept that key during the last SSH probe.
- Windows tailnet IP `100.114.172.40` responded to ping, but TCP `22` was not listening during the last check.
- Flux Git sync is enabled and reconciling (see GitOps section).

## Pending

Canonical list: `BACKLOG.md`. The highest-impact open DR item under the current single-control-plane strategy is
off-homelab age-key escrow. Proxmox VM backup/restore is proven. The third k3s server / HA failover path is deferred indefinitely
for budget and is not an active owner action. R2 credential scope/lifecycle are accepted as-is by owner decision.

## Plan Fact-Check (2026-06-18)

BUILD-PLAN / ARCHITECTURE / DECISIONS were fact-checked against current (June 2026) reality. Corrections applied
to the design docs only (no infra change yet):

- **Object storage:** MinIO community edition was archived (Feb 2026, no patches) -> replaced by **Garage** (ADR-019).
- **Restate storage:** the "durable journal -> Postgres" mapping was wrong -> Restate uses an embedded log + local
  RocksDB + async S3 snapshots (Garage), not Postgres (ADR-020).
- **RU egress:** Anthropic/OpenAI/OpenRouter are unreachable from Russia -> new egress ADR (ADR-018; VLESS+REALITY
  or a non-RU LiteLLM node). New risks RISKS #15/#16.
- **k3s-over-Tailscale:** flannel-over-`tailscale0` confirmed (native `--vpn-auth` still experimental) -> ADR-021;
  `--advertise-address` added to the Stage-1 command.
- **Budget VPS:** 1 vCPU / 1 GB is half the k3s server minimum; etcd idles ~1.4-1.6 GB (RISKS #9 hardened).
- Confirmed current/healthy: k3s v1.35.5, Flux v2.8.8 (CNCF Graduated), SOPS v3.13.1, OpenTofu 1.12.2,
  CloudNativePG (pin >=1.29.1), Restate v1.6.x (runtime BSL / SDK MIT), Hermes Agent, Mission Control v2.0.1.

## Offsite Backups (2026-06-19)

- k3s etcd-s3 enabled on uap-home-1 -> Cloudflare R2 (EU jurisdiction), bucket uap-k3s-snapshots, folder prod.
- S3 creds: SOPS secret clusters/prod/infra/k3s-etcd-snapshot-s3-config.sops.yaml, applied to kube-system by Flux.
- Verified: snapshot uploaded to R2 (prod/uap-r2-verify-...); scheduled snapshots auto-upload. Retention: the
  `etcd-snapshot-retention` value (7) is LOCAL-disk; k3s prunes SCHEDULED S3 snapshots too, but MANUAL/on-demand R2
  snapshots are NOT auto-pruned. Owner accepted the current no-lifecycle policy on 2026-07-12; the prior
  "retention 7" claim for all R2 objects was inaccurate.
- Verified 2026-07-12: the canary cross-node drill restored from an R2-fetched snapshot on a clean host and read
  back the encrypted Secret value using only the snapshot + original server token. A separate
  `encryption-config.json` was not required. The test namespace, snapshot and disposable k3s state were removed.
- R2 reachable directly from RU via the EU endpoint (no proxy needed for backups).
- Operator-node services (ad-hoc on uap-ops-1, NOT yet in GitOps): sing-box VLESS egress, Vaultwarden. Flagged as a
  blast-radius/SPOF + secrets-at-rest concern in REVIEW-CODEX.md; migrate into the cluster (Stage 3) or back up +
  document with a recovery runbook.

## Cross-Review Remediation (REVIEW-CODEX.md, 2026-06-19)

Done:
- ops-1 live secrets perms tightened (Vaultwarden `rsa_key.pem` 0644->0600, `~/.config/gh` 0755->0700).
- Stale handoff docs corrected (CLAUDE.md Git Remote Readiness; restore-drill encryption-config theory softened to a
  canary TODO; R2-retention wording).
- Ansible k3s playbooks now converge: notify-restart on config/token change + version-aware install (not binary-only).
- BUILD-PLAN Stage 2: honest HA milestone (node-loss test vs pod-delete) + version-pin requirements.
- ops-1 services backup LIVE: `ops-backup.timer` (systemd --user) daily age-encrypted archive of Vaultwarden +
  `~/.secrets` + units -> `r2:uap-k3s-snapshots/ops-backup/`; first run verified. See
  `runbooks/uap-ops-services-backup.md`.
- #3 GitHub least-privilege: broad `gh` OAuth token removed from ops-1; pushes now use a repo-scoped read-WRITE SSH
  deploy key (origin = SSH), push/fetch verified. Branch protection is now **APPLIED**: the repo was made **public**,
  the ruleset `protect-master` is **active** (PR required + the `static-checks` CI check required/strict), and direct
  push to `master` is **blocked**. The CI gate (`.github/workflows/ci.yml`) is therefore an **enforced required check**,
  not just a signal (see `docs/next-steps.md` → Platform hardening). DONE.
- #4 Vaultwarden rotated: admin token regenerated and stored as an Argon2 PHC hash in `.env` (no longer plaintext);
  RSA identity key regenerated (0600). Owner saved the new token in a password manager on 2026-07-12, its admin
  login was verified, and the staging file `~/vaultwarden/admin-token.NEW.txt` was deleted.
- #9 cross-node Secret restore passed on 2026-07-12; snapshot + original token restored the exact canary value.
- Owner accepted the current R2 credential scope and lifecycle as-is on 2026-07-12; do not rotate automatically.
- #11 kubeconfig permissions hardened on 2026-07-12: the live unquoted `0644` value had been interpreted as mode
  `0420`; the authoritative config is now the quoted string `"0600"`, the live kubeconfig is `root:root` mode `0600`,
  and k3s plus both nodes remained healthy without a service restart. Static validation prevents regression.
- #11 LAN firewall hardened on 2026-07-12: the boot-persistent `uap-k3s-lan-firewall.service` drops LAN ingress to
  `6443/tcp`, `10250/tcp`, and `8472/udp`. A timed-rollback canary and the durable deployment both kept tailnet API
  and kubelet access open; both nodes, metrics, and workloads remained healthy. LAN DROP counters were observed.

Pending (owner action): independent off-homelab age-key escrow (verify decrypt); optional — revoke the old
"GitHub CLI" OAuth grant in GitHub settings. HA/VPS work is deferred indefinitely for budget and resumes only after
a new owner decision.
