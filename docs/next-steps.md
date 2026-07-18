# Next Steps

> Two parallel tracks. **Track A** is the new north star: pilot the external **hermes-agent** as the
> vibe-coding harness. **Track B** is the **foundation work that does not go away** under the current
> single-control-plane strategy — `uap-ops-1` is an over-concentrated SPOF, DR must stay proven, and the
> cluster is explicitly NOT HA. VPS/HA work is deferred indefinitely for budget and is not active work.
>
> Context: [docs/infrastructure.md](infrastructure.md). Decisions: [DECISIONS.md](../DECISIONS.md).
> This doc **references** [BUILD-PLAN.md](../BUILD-PLAN.md) and [REVIEW-CODEX.md](../REVIEW-CODEX.md)
> rather than restating their detail. Product contract: [product-operating-contract.md](product-operating-contract.md).
> Last reviewed: 2026-07-17.

---

## Status banner

- **NOT HA; HA/VPS deferred indefinitely for budget (owner decision 2026-07-12).** One k3s server/control-plane
  (`uap-home-1`, single embedded-etcd member) + one agent (`uap-home-2`). The active strategy is one
  control-plane, R2 backups, and the verified 2026-07-12 restore drill. A 3rd independent k3s server is a future
  HA prerequisite, not an active owner action. Do **not** turn `uap-home-2` into a second server (2-member etcd is
  not HA) — see [CLAUDE.md → Important Boundaries](../CLAUDE.md).
- **The quality gate is ENFORCED.** The repo is public, the ruleset `protect-master` is active (PR
  required + `static-checks` CI a required/strict check), and direct push to master is blocked. The
  "agent ships unreviewed code" model is now backed by an enforced CI gate (human review stays absent by
  design) — see Track A4 (DONE) and the platform-hardening items.
- **Model+agent backend is fully in GitOps** (Track B0 DONE).
- **Product workflow convergence Phase A6 passed its controlled live canary.** Hermes remains the harness; central
  mission state, Workspace/Telegram observation and build-1 Flow evidence were exercised under one `mission_id`.
  Automatic intake-to-dispatch for arbitrary future missions remains a later product milestone.
- **Brain reality (2026-07-11):** Codex `gpt-5.6-luna` via `codex_app_server` is live after owner re-auth and an
  explicit in-pod `LUNA-PROBE-OK`. The local `qwen-35b`/`ornith-9b` router remains the manual fallback; coding work stays on build-1.

---

## Track A — hermes-agent vibe-coding pilot

**Goal:** drive autonomous, self-verified coding from a phone, with a native-FC brain and Claude/Codex
subscriptions doing the actual edits. **Decisive constraint:** hermes-agent **requires native
function-calling** — the subfleet/Claude chat path cannot be its brain (it would connect and chat but
every tool goes dark). Detail + citations in the two research docs.

### Phase A1 — Local function-calling brain on the RTX (proof of FC) — ✅ DONE (2026-06-23)

*Why first:* cheapest way to prove the hermes-agent tool loop end-to-end with **no** cloud egress and
**no** subscription risk, on hardware we already own.

- On `desktop-m922ij2` (RTX 5060 Ti 16 GB), serve a Hermes/Qwen-family FC model via **vLLM**
  (`--enable-auto-tool-choice --tool-call-parser hermes`) or **llama.cpp** (`--jinja`).
- Raise context to **>= 64k** (hermes-agent rejects smaller at startup; Ollama defaults are far too low).
- **Done when:** a trivial hermes-agent run actually **invokes a tool** (file write / shell) against the
  local model — structured `tool_calls`, not text.
- *Caveat:* the desktop is **not always-on**. Codex is the durable brain; the local
  `qwen-35b`/`ornith-9b` router is the manual fallback (see A5).

> **Result (2026-06-23):** proven via **Ollama 0.16.1 + `gpt-oss:20b`** (native Windows; already on disk → no model
> download over the RU network). `/v1/chat/completions` with a `tools` array returns a **structured `tool_calls`**
> (`get_weather({"city":"Paris"})`, `finish_reason=tool_calls`), the tool-result round-trip yields a final answer, and
> a greeting yields no tool call. Served `context_length=65536`, **100% GPU**, ~14.7 GB VRAM. WSL2/Docker absent, so
> vLLM-in-WSL2 deferred; `gpt-oss` chosen over a fresh Hermes/Qwen pull for the no-download reason. Proof:
> `tests/smoke/local-fc-toolcall.ps1` → `local-fc-toolcall-ok`. Runbook: `runbooks/local-fc-model.md`. STATUS.md →
> "Local FC Brain". **The strict A1 wording ("a *hermes-agent* run invokes a tool") completes in A2** — A1 proved the
> exact endpoint contract hermes-agent requires; pointing hermes-agent at it (tailnet bind + `allow_private_urls`) is A2.

### Phase A2 — hermes-agent on an always-on Linux node, behind the egress — ✅ DONE (2026-06-24)

- Run the **prebuilt `nousresearch/hermes-agent`** image (not `curl|bash` — the installer pulls
  PyPI/npm/GitHub, awkward on RU egress) on an always-on Linux node that can reach the egress proxy.
- Persist `~/.hermes` (config, keys, SQLite state, skills, memory) on a volume; run as **non-root** with
  `terminal.backend: docker`; keep the default deny-by-default permission model; set
  `security.allow_private_urls: true` only as needed to reach LAN models (e.g. the RTX over tailnet).
- **Placement:** `uap-home-2` (2 vCPU / 4 GB, no GPU) is the most plausible always-on host;
  `uap-ops-1` (2 GB, no swap, already overloaded) should **not** take it. Decide bare-container-on-node
  vs eventual k3s workload (a community Helm chart exists; not official).
- **Done when:** the gateway runs persistently, survives a node reboot, and a CLI chat round-trips
  through it to the A1 brain.

> **In progress (2026-06-24):** owner chose **k3s via Flux** (not bare Docker) and to wire the **Codex brain
> directly** (pulling A5's brain forward) rather than the opportunistic RTX brain. The full recipe was **proven
> in the real image in-cluster** (`hermes chat -q` → `codex_app_server` → gpt-5.5 → tool executed, `BRAIN-OK`).
> Manifests merged (PR #8) and **deployed via Flux** — `hermes-agent` is **1/1 Running** on uap-home-2; the
> `kubectl exec` round-trip **in the deployed pod** wrote `BRAIN-OK` (brain executed a tool through the egress).
> **A2 DONE.** The 4 non-obvious knobs + verify/rotate steps: `runbooks/hermes-agent-codex-brain.md`. The brain is
> the always-on Codex subscription through the egress, so this workload does **not** depend on the GPU desktop.
> Chosen k3s/Flux over bare Docker, and the Codex brain (pulled forward from A5) over the opportunistic RTX brain.

### Phase A3 — Telegram gateway (phone control) — ✅ DONE (2026-06-24)

- BotFather `/newbot` → `TELEGRAM_BOT_TOKEN` in `~/.hermes/.env`; lock down with
  `TELEGRAM_ALLOWED_USERS` / DM pairing (deny-by-default).
- Use **outbound long-poll** (default) — no inbound port, NAT/RU-friendly. If NAT idle timeouts kill the
  poll, shorten `messaging.telegram.poll_timeout`.
- **Done when:** a phone message reaches the agent and a tool-using reply comes back.

> **Done (2026-06-24):** a phone message round-trips through the gateway to the Codex brain (gpt-5.5) and back
> ("17×23 = 391"), verified end-to-end (PR #10). Non-obvious fix: api.telegram.org is **blocked direct** from the
> cluster, and hermes's per-profile `os.environ` is **isolated** (multiplex) — so the proxy + `TELEGRAM_ALLOWED_USERS`
> had to go in hermes's **managed scope** (`/etc/hermes/.env`, loaded last with override into `os.environ`,
> authoritative for every profile + subprocess). The same fix gives the **gateway-driven Codex brain** the egress
> (codex spawn = `os.environ.copy()`). Token via SOPS; details in `runbooks/hermes-agent-codex-brain.md`.

### Phase A4 — First `claude -p` coding worker (the vibe-coding gate) — ✅ DONE (PR #23; north-star demo PASSED, PR #25)

- Install the **Claude Code** bundled skill; it shells `claude -p '<task>'` in print mode and reads back
  the JSON result (session id, turns, cost, tokens). Auth uses the owner's current Claude subscription OAuth;
  as of 2026-07-13 that plan is non-Max and quota-aware,
  reusing the carried-forward headless-auth + egress know-how. **LIVE (PR #23).**
- Drive a **real, small change in this repo** end-to-end: idea (phone) → hermes-agent plans → `claude -p`
  edits in a **git worktree** → **the change's own tests pass (the enforced gate from the hardening
  work)** → commit/push via `uap-ops-1`.
- **Done:** a verified change landed **without the owner reviewing the diff** — the worker autonomously
  shipped it through the enforced CI gate (**north-star demo PASSED, PR #25**). The agent's self-test +
  the now-enforced CI was the gate.

### Phase A5 — Codex brain + redundancy — ✅ DONE (PR #24; brain restored 2026-07-11 in #119)

- Switch the durable brain to the **ChatGPT/Codex** subscription via the **`codex_app_server`** runtime
  (`model.openai_runtime: codex_app_server`, provider `openai-codex`) — native FC, **no API key**, OAuth
  (`~/.codex/auth.json`). Codex CLI must reach OpenAI **through the egress proxy**. Two Plus accounts give
  rate-limit headroom. **DONE** (brain live, A2/A3).
- Add **`codex exec`** as a second coding skill alongside `claude -p` to **split coding load**, with
  per-worker git worktree isolation. **DONE (PR #24).**
- **Redundancy:** the local router combines RTX `qwen-35b` with always-on Mac `ornith-9b`; both the Codex
  and local brain paths are proven. Switching between them is documented but manual; no automatic brain failover claim.

> **Current state (2026-07-11):** Codex `gpt-5.6-luna` is the live brain after owner device-auth restored
> the ChatGPT-Plus OAuth lineage (#119). From 2026-07-06 through 2026-07-11 the local
> `qwen-35b`/`ornith-9b` router served as the brain; that path remains available as a manual fallback.
> See [runbooks/hermes-agent-codex-brain.md](../runbooks/hermes-agent-codex-brain.md) and
> [runbooks/local-models-router.md](../runbooks/local-models-router.md).

> **Do NOT** point hermes-agent's brain at the subfleet endpoint at any phase — it is FC-less. subfleet
> stays the backend for the owner's **other** projects (Telegram bot + web sessions), not the coding path.

### Phase A6 — One Hermes mission plane — ✅ CONTROLLED CANARY COMPLETE (2026-07-14)

**Goal:** Workspace and Telegram are synchronized views of one central Hermes mission. Build-1, Kanban, swarms,
coding agents and test VMs execute that mission and publish correlated progress/results under the same `mission_id`.
The owner supplies the goal and material product trade-offs; the platform performs the delivery loop.

The normative behaviour is [Product Operating Contract](product-operating-contract.md); architecture is ADR-030.
This phase does **not** replace Hermes and does not create a new control plane.

1. **A6.0 — Contract and current-state map — ✅ DONE (2026-07-14).** The
   [repo-backed state map](hermes-mission-state-map.md) records every current session, task, job, Kanban, Conductor,
   browser and Flow store, plus the active fallback paths and identifiers. It traces Workspace chat to central
   sessions and direct build-1 delegation, and explicitly proves the missing Telegram-session and
   central-mission-to-Flow links. No service/model/GPU action was used. **Gate: PASS for the map; the product contract
   remains unmet.**
2. **A6.1 — Central mission contract — ✅ DONE offline (2026-07-14).** The
   [v1 contract](hermes-mission-contract-v1.md) defines the stable `mission_id`, lifecycle, ordered event envelope and
   cursor/replay rules. Its fake central backend proves Workspace/Telegram convergence after refresh/reconnect. The
   pinned Workspace overlay makes central-only authority selection fail closed for sessions, profiles, tasks, Kanban,
   jobs and Conductor. **Gate: PASS offline.** No live Workspace restart/deploy or model execution was performed.
3. **A6.2 — Build-1 execution adapter — ✅ DONE offline (2026-07-14).** The stdlib-only adapter reuses native Hermes
   Kanban with a central mission tenant and idempotent root-card key, then projects task/worker/terminal/file/test/
   review/PR/deploy evidence into deterministic producer events. It is blocked/unassigned by default and cannot forge
   central mission completion. **Gate: PASS offline:** an injected post-create crash plus backend restart completes one
   fake mission without duplicate work/events. At this A6.2 checkpoint the adapter had not been installed live; A6.4
   later installed and exercised it once, without adding automatic intake-to-dispatch.
4. **A6.3 — Compact synchronized observation — ✅ DONE offline (2026-07-14).** A stdlib-only module inside the pinned
   central Hermes source owns one SQLite event log/reducer. The existing gateway API exposes its structured view;
   Workspace adds one compact Dashboard card with bounded two-second polling and expandable tasks, workers, terminal,
   changes, gates and delivery links. Telegram `/mission` plus automatic owner-relevant notifications render the same
   projection hash. **Gate: PASS offline:** the fixture survives store restart/cursor reconnect with identical
   Workspace/Telegram state; producer events deduplicate and notifications deduplicate after their cursor checkpoint.
   Delivery is at-least-once, so a crash after send and before checkpoint may repeat a notification. Pinned overlay
   tamper checks, the patched Workspace production build and an aiohttp API smoke all pass. At this A6.3 checkpoint the
   overlays were not installed live; A6.4 later installed them.
5. **A6.4 — Controlled one-shot canary — ✅ DONE (2026-07-14).** With the owner's explicit approval of the
   model/runtime and test target, one disposable goal ran through implementation, tests, separate review, PR/CI,
   merge and fresh-main verification. The exact route was central
   `openai-codex`/`codex_app_server`, recorded author label `gpt-5.6-luna`, recorded exact-SHA reviewer label
   `gpt-5.6-sol`, and private target `PavelLizunov/hermes-flow-v2-pilot`. The current artifacts do not derive either
   model ID from runtime events or prove an OS-enforced read-only reviewer. Qwen/local inference, GPU, Claude, swarm and
   Spark were not used. **Gate: PASS:** [evidence](evidence/a6-4-controlled-canary-2026-07-14.md) links rollout,
   implementation, 4/4 tests, exact-SHA review, PR/CI/merge, fresh-main post-verify, idempotent event replay, equal
   Central/Workspace projection and the caught-up Telegram cursor. No human operator step is hidden.

Each numbered item was delivered as a separate small PR or an explicitly recorded live canary. A6 is complete at the
controlled-canary boundary. Phase A7 subsequently proved repeatable automatic intake/delivery for exact configured
profiles. Generic arbitrary-mission routing remains outside that boundary and does not inherit approval for local
inference/GPU, swarm, Spark, destructive-test expansion or a new provider.

### Phase A7 — Automatic mission intake to build-1

**Goal:** a central mission with an exact build-1-configured routing selector reaches one native Kanban root task
without a Codex operator wiring the transition. This extends the existing modular monolith and Flow adapter; it does
not add an application service, workflow engine or mission database.

1. **A7.1 — Pull handoff and bounded retry — ✅ MERGED (2026-07-15).** Central `mission.accepted` carries an immutable optional
   `dispatch_profile`. The build-1 adapter performs one bounded poll, exact-matches the locally configured profile,
   creates/reuses one atomically sticky-blocked native Kanban root and publishes its deterministic task event. A fault after Kanban create
   but before central publish must converge after restart to one task/root ID and one producer event. No model runner
   is invoked by the hermetic test, and blocked is the default live-safe behavior.
2. **A7.2 — Owner-approved live blocked-task canary — ✅ DONE (2026-07-15).** Flux applied exact master, Central and
   build-1 installed the pinned atomic Kanban overlay, and one exact-profile poll without `--activate` produced exactly
   one blocked/unassigned native root and one Central `task.upsert`. The repeated poll returned null; runs and
   worker/model processes stayed empty. See
   [the exact evidence](evidence/a7-2-live-blocked-handoff-2026-07-15.md).
3. **A7.3 — Automatic activation and delivery — ✅ FIXED-PROFILE ACCEPTANCE CANARY PASS (2026-07-17).**
   PRs #199-#238 provide the bounded coordinator, durable crash/quality recovery, lifecycle controls and
   standing-approved `openai-autonomy-v2` routing. The earlier VPNRouter mission proved recoverable delivery while four
   harness fixes landed between durable ticks. On the fully corrected runtime, Telegram-bound mission
   `a7-clean-ledger-list-20260717-a0fc5a` then ran from the systemd timer with no manual coordinator tick or mid-run
   repair. It selected runtime-attested Sol author and distinct exact-SHA read-only Terra reviewer sessions at `xhigh`,
   recovered the planned post-author-commit crash without another author or candidate, passed Rust repository gates,
   opened and merged hermes-flow-v2-pilot PR #5 after Python/Linux/macOS/Windows CI, and passed fresh-main verification.
   The native task/run was archived, disposable branch/worktrees were removed, Central and Workspace returned the same
   sequence-22 terminal projection, and the bound Telegram cursor reached 22. Cross-channel owner answer/resume and the
   bounded 30-day lifecycle remain deployed. See the [A7.3 contract](a7-real-project-canary.md), the exact
   [acceptance evidence](evidence/a7-3-clean-telegram-canary-2026-07-17.md), the earlier
   [recovery evidence](evidence/a7-3-activation-delivery-canary-2026-07-15.md), and the
   [lifecycle rollout evidence](evidence/a7-lifecycle-rollout-2026-07-17.md).
4. **Registered reusable profile — ✅ ORDINARY WORKSPACE + TELEGRAM DELIVERY PASS (2026-07-18).** The standing schema-v4
   `hermes-flow-v2-pilot` consumer now accepts a normal Workspace message through a server-owned exact route. The first
   non-toy mission delivered the requested Rust API/CLI/tests through runtime-attested Sol/Terra sessions,
   multi-platform CI, exact merge, fresh-main verification and cleanup, but truthfully missed requested README work
   because the profile excluded that path. PR #254 narrowed the correction to adding `README.md`; a second ordinary
   Workspace mission then exercised a real review rejection, automatic correction, re-review, PR #7 merge, terminal
   convergence and cleanup without manual delivery commands. A later ordinary Telegram goal used the same registered
   profile, recovered from a controlled exact pre-turn capacity failure without an owner question, and completed
   Sol/Terra execution, target PR #8, multi-platform CI, merge, post-verify, cleanup, terminal sequence 27 and a verified
   canonical completion bundle. The latter was an adversarial correction campaign rather than a clean frozen-runtime
   run: reviewer recovery and Central historical-worker completion defects were fixed through PRs #271–#273 while the
   same durable mission was preserved. See the
   [installation evidence](evidence/registered-flow-profile-v4-rollout-2026-07-18.md) and
   [Workspace campaign evidence](evidence/ordinary-workspace-autonomous-delivery-2026-07-18.md) and
   [Telegram capacity campaign evidence](evidence/ordinary-telegram-capacity-recovery-2026-07-18.md).
5. **Workspace cursor replay — ✅ LIVE RECONNECT PASS (2026-07-18).** PR #256 added selected-mission cursor replay,
   strict sequence/cursor validation and a compact ordered timeline. Its first live render found a null race; PR #257
   fixed it and added an exact vulnerable-asset upgrade regression. The corrected live Dashboard reconstructed the
   same 20-event mission history and cursor 20 after full reload. Ordinary Telegram intake later passed for the same
   registered profile; the next channel gate is a live cross-channel question/answer, not another fixed-profile
   delivery canary. See the
   [reconnect evidence](evidence/workspace-mission-cursor-replay-2026-07-18.md).
6. **Capacity observation — ✅ CONTROLLED LIVE RECOVERY PASS (2026-07-18).** PR #259 added a closed
   `mission.notice` projection for capacity wait/recovery, stable coordinator event identities and the same explicit
   no-owner-action state in Workspace and Telegram. The first Flux reconciliation retained the stale ConfigMap
   `subPath` mount; PR #260 bumped only the existing pod-template revision and rolled the exact runtime. Central,
   build-1 and Workspace source/install hashes and health checks then matched. An ordinary Telegram mission later fired
   the pre-announced wrapper's exact trusted pre-turn capacity phrase, recovered on the first same-model Sol retry,
   projected `capacity_recovered` with `owner_action_required=false` and completed without a quality-failure increment
   or owner question. This does not prove a naturally occurring provider envelope, `capacity_wait`, burst exhaustion or
   whole-route fallback. See the [rollout evidence](evidence/automatic-capacity-observation-rollout-2026-07-18.md) and
   [live campaign](evidence/ordinary-telegram-capacity-recovery-2026-07-18.md).
7. **Delivery applicability — EXPLICIT `none`; DEPLOY/RELEASE STILL FAIL-CLOSED (2026-07-18).** The registered pilot's
   server-owned route and schema-v4 profile carry immutable `delivery_mode: none`; Central requires the coordinator's
   `delivery: not_applicable` event before terminal completion. Legacy missions remain compatible. A configured
   `deploy` or `release` mode is rejected until exact artifact, environment, deployed-revision and health evidence is
   implemented, so fresh-main verification is no longer allowed to imply deployment for the registered target.
   Exact rollout evidence:
   [registered delivery applicability](evidence/registered-delivery-applicability-rollout-2026-07-18.md).
8. **Ordinary bound Telegram answer — ✅ DEPLOYED COMPONENT PASS; LIVE QUESTION/ANSWER CANARY PENDING (2026-07-18).** A normal
   Telegram message on the chat/topic bound to a `waiting_owner` mission now answers that mission's exact open
   question instead of accepting another goal. The Telegram message ID is persisted in `mission.answer`; restart and
   lost-response replay converge on the same event, while changed text under the same ID fails closed. This reuses
   `MissionStore`, the existing binding and the existing answer state machine. PR #264 passed CI, Flux rolled the
   exact runtime and a temporary-store scenario passed inside the Ready pod. It does not claim a real owner-channel
   question/answer canary, ordinary Workspace chat answers or complete cross-channel transcript synchronization. See
   the [rollout evidence](evidence/ordinary-bound-telegram-answer-rollout-2026-07-18.md).
9. **Canonical completion evidence — ✅ FIRST LIVE BUNDLE VERIFIED (2026-07-18).** The existing
   coordinator can now write one closed, self-digesting `completion-evidence.json` after terminal convergence,
   cleanup and task archive. The bundle joins mission/goal, canonical profile/policy/runtime hashes, a bounded-size
   systemd invocation chain, exact Git/PR/CI/review/post-verify identities, cleanup and the Central projection. The
   stdlib verifier checks both canonical SHA-256 and semantic lineage, so recomputing the digest after weakening
   review, CI, cleanup or Git ancestry still fails. Restart verifies an already completed bundle instead of silently
   replacing it. PR #268 passed required CI; exact merged source is installed on build-1, source/installed hashes
   match. Ordinary Telegram mission `mission-intake-0c72cde02b5ef62972a30bc998f316b9` produced the first private live
   bundle after terminal sequence 27; the installed verifier accepted semantic digest `d05c16b7...`. A systemd service
   identity is not proof of timer origin; channel origin/source message, channel cursors and signed artifact
   attestation remain later evidence fields. See the
   [rollout evidence](evidence/canonical-completion-evidence-rollout-2026-07-18.md) and
   [live campaign](evidence/ordinary-telegram-capacity-recovery-2026-07-18.md).
   PR #275 deploys backward-compatible closed schema v2: new registered ordinary missions bind the server-owned
   input platform and hashed source key/message to deterministic `mission-intake-*`, while existing v1 bundles still
   verify. Exact Central/build-1 rollout, in-pod replay and installed v1/v2 verifier checks passed. One v2 live artifact
   remains the next evidence gate; channel delivery cursors, timer-origin proof and signing are still separate. See the
   [input-lineage rollout](evidence/completion-input-lineage-rollout-2026-07-18.md).
10. **Ordinary Workspace answer — ✅ DEPLOYED COMPONENT PASS; LIVE CROSS-CHANNEL CANARY PENDING (2026-07-18).** The exact Central session
    that accepted a Workspace mission now routes a later ordinary message to its one open mission question through
    the same `MissionStore.ingest_owner_turn()` path. The source message ID is persisted in `mission.answer`; restart,
    delayed replay and changed-text collision are deterministic, and multiple open questions fail closed. The
    structured answer action remains compatible. PR #270 passed CI, Flux applied exact merge `5d95eada...`, mounted
    runtime/overlay hashes matched and an in-pod temporary-store scenario passed. This closes the deployed
    implementation asymmetry with Telegram without a new service; one real cross-channel question/answer canary remains
    required. See the
    [rollout evidence](evidence/ordinary-workspace-owner-answer-rollout-2026-07-18.md).
11. **Concrete owner terminal result — ✅ DEPLOYED COMPONENT PASS; LIVE PROOF PENDING.** The first ordinary Telegram delivery completed correctly,
    but its terminal notification only said `Delivery completed, merged, and verified`. Build a bounded redacted result
    from already projected canonical facts. Current source does this at Central's existing `complete_if_ready()`
    boundary: accepted goal, changed paths, PR, verified revision, passed gates and delivery applicability become the
    one terminal result consumed by both Workspace and Telegram. It adds no schema, service or model call. PR #277,
    required CI, exact Flux rollout, mounted-runtime hash and an in-pod byte-for-byte Central/Telegram assertion passed.
    A later real terminal message remains the evidence gate. See the
    [rollout evidence](evidence/concrete-terminal-result-rollout-2026-07-19.md).
12. **Author OS isolation — SOURCE GATE PASS; BUILD-1 PROOF PENDING.** Reuse the reviewer transient user-systemd
    boundary for author Codex turns. The author may write only its deterministic disposable worktree and the existing
    mission-local model/Codex homes; source checkout, sibling worktrees and mission state stay read-only, while common
    credentials, control-plane environment, unrelated processes and the user runtime stay inaccessible. The existing
    route, prompt, capacity/retry and exact runtime-attestation contracts do not change. Coordinator tests cover both
    actor variants. Required next evidence is an installed exact-wrapper write/credential/process probe followed by
    one real runtime-attested author turn through the boundary.

No generic shell command, arbitrary repository path, model ID or credential is accepted from mission payload. A
mission without an exact configured profile remains unclaimed and visible rather than falling back. Workspace and
Telegram now share authoritative mission status and owner question/resume. A bound Telegram chat and the exact
accepting Workspace session can answer the open question with an ordinary message;
complete cross-channel chat/session history remains a separate Product
Operating Contract gap.

---

## Track B — Foundation work (independent of the pilot)

Open infrastructure debt from [STATUS.md](../STATUS.md) and the 2026-06-19 cross-review
[REVIEW-CODEX.md](../REVIEW-CODEX.md). Progresses regardless of Track A. (owner) = owner action,
(agent) = agent action.

### B0 — Bring the model+agent layer fully into GitOps (quick, do early) (agent) — ✅ DONE

- `clusters/prod/infra/litellm.yaml`, `hermes.yaml`, `litellm-keys.sops.yaml`, and `hermes-keys.sops.yaml`
  are **now committed and referenced** by `clusters/prod/infra/kustomization.yaml`, along with the
  `hermes-code-configmap.yaml` and every hermes-agent manifest — so Flux reconciles all of them. **DONE.**
- The `hermes-keys` Secret (`LITELLM_KEY`, `HERMES_KEY`, optional `HERMES_KEYS_JSON`) is **authored as a
  SOPS file and in the kustomization** — Flux can reconcile Hermes. **DONE.**
- `sops-smoke.sops.yaml` is likewise committed but intentionally **left out** (a decrypt smoke fixture) —
  keep it that way.
- `validate_iac.py` now rejects orphaned prod manifests; CI and the local gate enforce it. **DONE.**
- Hermes-legacy is explicitly parked; the external hermes-agent is the active harness.

### B1 — Real HA path — DEFERRED (owner decision 2026-07-12)

VPS provisioning and the HA build are deferred indefinitely because of budget. Do not carry a third k3s server as an
active owner action, and do not start join/failover work without a new owner decision.

- Current operating mode: one k3s control-plane/server (`uap-home-1`, single embedded-etcd member) + one agent
  (`uap-home-2`).
- Current risk control: R2 backups plus the verified 2026-07-12 cross-node canary Secret restore drill.
- Future prerequisite before any HA claim: a 3rd independent k3s server in a separate failure domain, followed by
  an owner-approved destructive failover drill with 3x Ready and API/workload survival after one server loss.

### B2 — Reduce the `uap-ops-1` blast radius (owner+agent)

`uap-ops-1` (2 GiB, no swap) simultaneously holds sing-box egress, Vaultwarden, plaintext R2 creds, the
GitHub push key, a cluster-admin kubeconfig, and an SSH key authorized on **both** k3s nodes — and sits
on the **same Proxmox host** as `uap-home-1`. Already DONE: secret perms tightened, Vaultwarden token +
RSA key rotated, broad `gh` OAuth removed → repo-scoped SSH deploy key, daily `ops-backup` timer.
Remaining:

- **R2 scope/lifecycle: accepted as-is by owner 2026-07-12.** Do not rotate credentials or change bucket policy
  without a new owner decision. The broader delete/overwrite blast radius is understood.
- **GitHub→cluster takeover path: DONE.** `protect-master` requires PR + green `static-checks`; direct
  master pushes are blocked.
- (agent) **Prove recovery for ops-1 services.** Daily age-encrypted backup and health alerts are live
  (#117), but restores for egress + Vaultwarden still need a tested runbook execution (or migrate them).
- **Done when:** ops-1 no longer holds an unscoped R2 key and egress+Vaultwarden restores are proven.

### B3 — Finish and prove DR (owner+agent)

- (owner) **Independent age-key escrow:** the age **private** key was found **only** on `uap-home-1`. Put
  a copy in a verified **off-homelab, owner-controlled** escrow and **prove a decrypt**. Never put the key
  value in git/markdown/prompts/logs.
- **Canary cross-node Secret restore: DONE 2026-07-12.** A clean disposable host restored the R2-fetched snapshot
  with only the original server token and read back the exact canary Secret value; no separate encryption config
  was required. Test state was fully removed.
- **Proxmox VM backups: DONE 2026-07-13.** Critical VMIDs `102/201/202/203` run daily to a separate
  `pve-ninitux2` disk; VM203 passed archive integrity plus an isolated, never-started restore check.
- **Done when:** an off-homelab escrow decrypt succeeds. Proxmox VM backup/restore is already proven.

---

## Platform hardening (cross-cutting, do alongside Track A4)

These make "the agent ships unreviewed code" actually safe; they gate A4.

- **Enforce the gate:** ✅ DONE — GitHub Actions CI (`static-checks`) runs on every push/PR, the repo is
  public, and the `protect-master` ruleset requires a PR + the `static-checks` check (strict), so direct
  push to master is blocked. (A PreToolUse commit secret-scan hook remains a nice-to-have defense-in-depth.)
- **Hermes tests in CI: DONE.** The local `verify-local.ps1` wrapper still requires the documented explicit
  unittest command for `hermes/` changes.
- **Isolate coding workers:** docker backend (`--cap-drop ALL`, `no-new-privileges`, `--pids-limit`,
  capped tmpfs, repo bind-mounted, NO host secrets in env); deny-first `.claude/settings.json`
  (`**/*.sops.yaml`, `age-key.txt`, `~/.codex/auth.json`); `--max-turns` + `--max-budget-usd` per run.
- **Per-worker git worktrees: DONE** for coding engines; AGENTS.md requires separate worktrees for parallel workers.
- **Attribution: PARTIAL.** Canonical identity + trailers are enforced; SSH commit signing remains optional debt.
- **Reproducible toolchain: DONE.** `requirements-dev.txt` is pinned and Python bytecode is ignored.

---

## Sequencing

- **B0** and the **gate-enforcement** hardening are ✅ DONE — both removed live risk.
- **Track A** (the pilot) proceeded **in parallel**: it uses subscriptions and one
  always-on Linux node, none of which block on HA work. A4 landed **after** gate enforcement, so
  "self-test passed" is real (north-star demo PASSED, PR #25). **A6 passed its controlled canary:** A6.0 mapped the
  split state plane; A6.1-A6.3 built and tested the contract, adapter and synchronized projections; A6.4 installed the
  exact pinned runtime and completed one explicitly approved Luna/Sol mission through PR/CI/merge/post-verify. A7 then
  passed the Telegram-bound fixed-profile delivery canary through automatic OpenAI routing, recovery,
  multi-platform CI, merge, post-verify and cleanup. Automatic intake-to-dispatch for arbitrary missions remains a
  separate product gap. It has no inherited approval for local inference/GPU, swarm, Spark, destructive tests or a
  different provider route.
  The source coordinator also has hermetic restart-safe capacity retry and author whole-route fallback across only
  the ADR-031 OpenAI tuples; capacity cooldown parks the Kanban task without a ticking claim lease and automatically
  claims a new run when due. An ordinary Telegram campaign fired a controlled exact pre-turn compatibility error and
  proved automatic same-model recovery without an owner question or quality-failure increment. A naturally occurring
  provider envelope, `capacity_wait`, exhausted burst and whole-route fallback remain outside live proof. PR #273 also
  corrected Central terminal admission for the valid capacity history of scheduled predecessors followed by one
  successful worker; the same mission then reached exactly one terminal event.
  Reviewer process hardening is implemented in the source coordinator without another service: a transient
  user-systemd unit is bound to the active coordinator, uses a strict read-only mount/proc namespace, exposes only
  mission-local model/Codex runtime write paths, and masks common delivery/host credential stores and control-plane
  environment names. PR #266 passed required CI, exact merge `a0d8f391...` is installed, and the installed
  exact-wrapper probe proved write denial plus credential/proc/user-runtime isolation while preserving only the two
  approved write roots. The first real attempt found that `After=` deadlocked the transient reviewer against its
  still-activating Type=oneshot parent; the minimal correction keeps `BindsTo=` and removes only that ordering edge.
  PR #271 is merged and installed. Its crash recovery then exposed a second narrow gap: the interrupted reviewer was
  safely quarantined but remained in `reconciling` forever. PR #272 now retries only a reviewer whose old transient
  unit is unloaded and whose read-only exact-SHA checkout and draft PR are unchanged; author ambiguity stays
  fail-closed. Exact merge `ea597a9...` is installed, and the same mission completed a runtime-attested Terra review of
  the exact candidate inside the corrected boundary before green CI/merge. Evidence:
  `docs/evidence/reviewer-os-isolation-rollout-2026-07-18.md` and
  `docs/evidence/ordinary-telegram-capacity-recovery-2026-07-18.md`.
  PR #279 then applied the same installed namespace to author turns with only the disposable author worktree added to
  the writable set. Source/installed hashes matched, the installed adversarial probe passed, all five timers resumed,
  and a controlled real Sol `xhigh` author completed with rollout-derived OpenAI/workspace-write attestation after
  changing only its allowed file. This closes the installed real-actor gate, but not a complete ordinary mission on the
  exact combined revision. Evidence: `docs/evidence/author-os-isolation-rollout-2026-07-19.md`.
  Central source now also serializes accepted missions per exact profile: an existing nonterminal projected task
  blocks admission of later candidates, and a restart-safe component test releases the oldest successor only after
  the predecessor is terminal. A live two-mission run is still required before claiming operational queue proof.
- **B1 (3rd node + failover)** is deferred indefinitely for budget; do not treat it as active owner work.
- **B3 remaining DR proof** now centers on off-homelab age-key escrow; Proxmox VM backup/restore and the R2 canary Secret
  restore drill is already green.
- **B2** hardening should land before the platform takes on more load or secrets.

## Owner inputs needed

- Off-homelab age-key escrow location.
- Approval for destructive tests against non-disposable state (restore over an existing VM, production k3s reset).
  Repo-defined hermetic/disposable drills do not need per-run approval. HA node-shutdown tests resume only after a new
  owner decision funds a third server.
