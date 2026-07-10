# Harvest from the sister Hermes node (`ninitux` / Настя) into UAP

Curated adopt-list distilled from a **read-only** snapshot of the sister node's full
NousResearch hermes-agent install (v0.18.2), analyzed 2026-07-10. The snapshot contains
**live secrets** and was never copied into the repo; every feature below is referenced by
**name and shape only**. Full context + reach path: memory `uap-sister-hermes-node.md`.

Stance is **FEDERATE, not consolidate** (she is a strong peer node, not a broken client).
This doc harvests *patterns* worth re-implementing as repo-tracked UAP artifacts. Each item
is **rebuilt from the description here** against UAP infra — never lifted from her profile
dirs, never pointed at her models, never carrying her corporate coupling or her secrets.

UAP rebind target for every model reference below:
- **local-models-router** `http://100.82.241.121:8090/v1` (pick `qwen-35b` desktop-RTX or
  `ornith-9b` always-on-mac by model name) — the durable local tier; OR
- **Codex** as a *coding engine only* (the cloud brain tier is off — paid limits exhausted;
  revert path noted in the hermes-agent ConfigMap).
Never rebind to her Codex/Nous/Ollama endpoints.

---

## ADOPT

### 1. Multi-agent orchestration verification discipline
- **WHAT** — a hard rule: before asking a human to retry a large swarm mission, prove the
  *actual dispatch path* with a tiny local one-shot smoke mission through the same API, and
  assert a structured checkpoint (HTTP success, exit code 0, checkpoint status,
  `FILES_CHANGED: none`). A green compile/build is **not** proof that worker-spawning works.
  Keep every specialist lane **read-only** until the plan + approvals exist.
- **WHY** — this is exactly the self-test-IS-the-gate thesis, applied to the swarm layer.
  Her own node shipped a workspace on a green build alone while lint + tests were red for two
  days (the precise bypass our thesis warns against). Adopting the *discipline* while
  rejecting *her practice* is the point.
- **HOW (UAP)** — fold the smoke-first contract into
  `runbooks/hermes-kanban-swarm-pilot.md` (done: see the "Дисциплина верификации" section).
  Our dispatcher already lives in the gateway with the Kanban DAG; the pre-dispatch endpoint
  healthcheck (`curl -m 90 <router>/v1/chat/completions ... max_tokens:1 → 200`) is our
  equivalent of her checkpoint smoke. On Windows-without-tmux the swarm may fall back to
  one-shot dispatch — verify the real path, don't assume persistent workers.

### 2. DevOps/SRE specialist-roster taxonomy
- **WHAT** — a five-lane role taxonomy for platform work, each an isolated agent profile
  with its own SOUL identity + a kanban-routing description:
  `devops-ci-cd` (pipelines, Actions/GitLab CI, Docker build, release automation),
  `sre-incident` (incident response, RCA, postmortems, error budgets/MTTR),
  `k8s-platform` (Kubernetes, Helm, GitOps Argo/Flux, RBAC, scaling, ingress),
  `cloud-infra` (Terraform/Pulumi IaC, cloud networking, IAM, cost),
  `observability` (Prometheus/Grafana/Loki/Tempo, metrics/logs/traces, SLOs, alerting).
- **WHY** — a clean, UAP-shaped division of platform labor for the Kanban swarm; `k8s-platform`
  and `observability` map straight onto our k3s + Flux + SOPS stack.
- **HOW (UAP)** — **REBUILD from this description**, do not copy her profile dirs (they carry
  her model/auth/skills and corporate SOUL). Create each with `hermes profile create <name>`,
  set a UAP-specific routing description, point `model.provider: custom` at the
  local-models-router (§rebind above). Drop her `tencent/hy3:free` brain and her 72 inherited
  skills; provision only skills that exist in UAP. This roster is a *template*, not a payload.

### 3. Vuln-findings → remediation workflow (the generic core)
- **WHAT** — turn a scanner findings export into a plan by grouping on the **remediation
  ACTION, not the host**: ~1258 findings collapse into <10 idempotent workstreams. Phases:
  read-only export profiling → compute the working set (active AND NOT mitigated/risk_accepted/
  false_p/duplicate/out_of_scope) → classify into workstreams → aggregate → emit a matrix +
  phased plan → verify (assert matrix sums == raw source counts) → **collect actual-state facts
  read-only** (one Windows PowerShell collector + one Linux Bash collector, `bash -n` / AST
  parse before use, output is the *only* write) → **reconcile before execute** (compare scanner
  evidence vs current package/kernel versions with distro-aware ordering; a small candidate
  count does NOT prove findings are stale) → only then stage changes behind maintenance windows.
- **WHY** — generic, reusable engineering discipline that matches UAP's "verify before you act,
  reconcile against real state" posture and our IaC/Ansible remediation stack. The group-by-action
  insight alone is worth keeping.
- **HOW (UAP)** — adopt only the **generic, corporate-free** parts: the group-by-action framing,
  the read-only fact-collection contract, and the reconcile-before-execute gate. **Strip** the
  corporate specifics (Exasol-PROD, DefectDojo-as-SSoT assumptions, АльфаСтрахование ACLs). Map
  automation onto our stack: Ansible roles for Linux package/kernel/SNMP/TLS, Flux/GitOps for
  cluster-side, re-scan to verify idempotence. Keep every collector read-only (no install/update/
  restart/reboot/secret-read).

### 4. Final RU-copyedit rule: em-dash forbidden
- **WHAT** — her `mike/ru-text` skill: a final Russian copyedit pass. Its one load-bearing
  typographic rule — **the em-dash `—` is forbidden; use a hyphen `-` or restructure the
  sentence** — plus Russian `«»` quotes, junk-phrase removal, ≤4-line paragraphs.
- **WHY** — a durable house style for UAP's Russian runbooks/status/comms (owner prefers concise
  Russian). It also sidesteps a real UAP gotcha: PowerShell 5.1 reads UTF-8-no-BOM `.ps1` as
  CP1252, so an em-dash injects a stray byte and breaks parsing (memory `uap-ps51-ascii-scripts`).
  Hyphen-only Russian is both her style rule and our encoding safety rule.
- **HOW (UAP)** — apply the em-dash-forbidden rule to **new** Russian prose in runbooks/docs/
  commit messages (the added swarm-runbook section here already follows it). Additive: do not
  rewrite existing em-dash-heavy files just to comply.

### 5. `suflyor` plugin as a NATIVE-PLUGIN TEMPLATE (adopt the shape, not the feature)
- **WHAT** — a self-contained Hermes plugin: `plugin.yaml` manifest (`kind: standalone`,
  `provides_tools:` list) + an `__init__.py` that registers N tools + one `/slash` command via a
  `register(ctx)` entrypoint. It talks to a local bridge over **stdlib `urllib` only** (zero
  third-party deps), reads config from **env at call time** (so toggling needs no Hermes
  restart), routes localhost calls through an **empty ProxyHandler** (never send a loopback call
  through the VLESS proxy), and **never raises** from a handler (every failure — bridge off, 401,
  timeout, bad JSON — collapses to a returned message string).
- **WHY** — the cleanest reference for writing UAP's own native Hermes plugins. We already ship
  native adapters (ponytail) and stdlib CLIs (ai-search, knowledge, local-models-router); this is
  the canonical skeleton for the *plugin* packaging of one. The four discipline points (stdlib-only,
  env-at-call-time, no-proxy-on-loopback, handlers-never-raise) are exactly UAP's own conventions.
- **HOW (UAP)** — keep it as a **template skeleton only**. The suflyor *feature* (a personal
  call-interview overlay) is not a UAP need — do not deploy the bridge. When we need a new native
  plugin (e.g. a thin wrapper exposing knowledge.db or ai-search as tools), copy the *shape*:
  manifest + `register(ctx)` + stdlib client + the empty-ProxyHandler + never-raise handlers. The
  loopback-no-proxy rule maps directly onto our `NO_PROXY` exact-IP gotcha for tailnet endpoints.

### 6. Profile / gateway setup gotchas
- **WHAT** — three hard-won gateway lessons: (a) all profiles default to the **same
  `api_server` port 8642**, so a second gateway dies with `Port 8642 already in use` — give each
  profile its **own api_server port**; (b) put the **Telegram token + allowlist in the
  profile-local scope**, not shared; (c) **never run two gateways on one Telegram bot token** (a
  second poller silently steals updates). A single install-wide dispatcher lock across profile
  gateways is *by design*, not a bug — do not "fix" it with hardcoded-PID restart scripts.
- **WHY** — UAP already runs multiple gateway surfaces (the webcenter uses gateway API on
  **:8642** on build-1); standing up a second profile/gateway would collide on exactly this port.
  Cheap to avoid up front, painful to diagnose later (she wrote three hard-restart scripts around
  it, one with hardcoded PIDs).
- **HOW (UAP)** — when adding any second gateway/profile on a host that already runs one, assign a
  distinct `api_server` port in that profile's `config.yaml`, scope its Telegram token/allowlist
  to the profile, and rely on the built-in singleton lock (`--replace` / the existing
  gateway.lock) instead of PID-killer scripts. Document the chosen port next to the webcenter's
  :8642 so the map stays collision-free.

### 7. `tool_loop_guardrails` config block — but with `hard_stop` ON
- **WHAT** — a Hermes config block that detects stuck tool loops (exact-failure repeats,
  same-tool failures, idempotent-no-progress) with two tiers: `warn_after` and `hard_stop_after`.
  She ships `warnings_enabled: true` but **`hard_stop_enabled: false`** — warnings only, the loop
  can grind forever.
- **WHY** — this is the deterministic stop-condition our loop-engineering rule demands (every
  agent loop needs an explicit stop + budget; on failure DIAGNOSE, don't blind-retry). It directly
  addresses the SIM-1 finding where a heartbeat masked 55+ minutes of no-progress with no
  max-runtime guard in Hermes.
- **HOW (UAP)** — enable the block in our swarm/agent profiles and set **`hard_stop_enabled: true`**
  (the one delta from her config). Suggested thresholds (hers, kept): `warn_after` exact 2 /
  same-tool 3 / idempotent 2; `hard_stop_after` exact 5 / same-tool 8 / idempotent 5. It layers
  *under* our external `tools/swarm/watchdog.sh` (which kills orphans by wall-clock) — config-level
  hard-stop catches the tight loop, the watchdog catches the wandering orphan.

### 8. Daily EOD-digest cron pattern
- **WHAT** — a deterministic Python gatherer run by cron that writes a **UTF-8 Markdown digest
  file** and prints an **ASCII-only pointer** to stdout. Key design choices, all defensively
  correct: cron captures stdout in the system code page (cp1251 on RU Windows) which mangles
  Cyrillic → so real (Cyrillic) content goes in the UTF-8 *file*, stdout stays ASCII; it does
  **not** trust file mtime to find work (OneDrive resync bumps mtimes) → it parses the timestamp
  *inside* each record; it prints the date it used (the system clock has drifted before).
- **WHY** — a clean template for any UAP scheduled reporter (deterministic gatherer, not an
  LLM-narrated one) and it encodes two gotchas we share: RU-Windows encoding hazards and
  don't-trust-mtime. Deterministic-verifier-over-LLM-judgement is our loop-engineering rule.
- **HOW (UAP)** — reuse the *pattern*, not her paths (her digest scrapes `C:\Users\ninin` Desktop
  + Claude session JSONL). For UAP, point a gatherer at repo/cluster state we actually own, write
  a UTF-8 digest file, keep stdout ASCII-only, print the date used, parse in-record timestamps
  rather than mtimes. Schedule via Hermes cron or a systemd timer on build-1/ops-1.

---

## REJECT (do NOT harvest)

| Item | Why rejected |
|---|---|
| **JetKVM / `jetkvm_visible` plugin + corporate laptop automation** | Bound to her physical LAN + her АльфаСтрахование work laptop (Outlook, unlock macros). Corporate-coupled, prompt-injection → host-RCE-with-corporate-reach surface. Must stay on her node only. |
| **Exasol-PROD / DefectDojo-SSoT / corporate ACL specifics** | Corporate infra facts inside the vuln workflow. Keep only the *generic* group-by-action + reconcile core (item 3); strip these. |
| **Corporate `linux-infra-facts` / Windows-facts host inventories** | The concrete collector field-lists are tuned to her fleet; adopt the read-only-collection *contract*, not her host lists. |
| **Persona/personality blocks** (kawaii, catgirl, pirate, uwu, noir, hype, …) | Cosmetic role-play prompts. No UAP value; drop entirely. |
| **`hermes-achievements` gamification plugin** | Achievement/gamification layer. Noise for a vibe-coding platform. |
| **Cleartext-secrets posture** (Telegram/OAuth tokens in `.env` + pasted into chat + FTS-indexed in state.db; `API_SERVER_KEY` reused everywhere) | Direct violation of UAP's no-committed-secrets + SOPS rules. Reference by location only; never replicate. |
| **`HERMES_YOLO_MODE=1` + `HERMES_IGNORE_RULES=1`** | Unattended, unsandboxed shell/code-exec on a Telegram-reachable host. The opposite of UAP's deny-first, human-in-the-loop, gated posture. Never adopt. |

---

## See also
- `runbooks/hermes-kanban-swarm-pilot.md` — where items 1, 6, 7 are folded into the live pilot.
- memory `uap-sister-hermes-node.md` — full snapshot audit, reach path, federate-don't-consolidate stance.
- memory `uap-local-models-router.md` — the rebind target endpoint + models.
