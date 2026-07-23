# Security Remediation Pass — Hermes Agent (2026-07-24)

**Base (exact):** `6dbe224606154db05ef877cea6f3beebcce761e5` (this worktree HEAD)
**Executor:** qwen3.8-max-preview (isolated worktree `uap-security-remediation-safe-20260724`)
**Source of findings:** `ADVERSARIAL-AUDIT-CLAUDE-2026-07-23-HERMES-DOCS-COMPLIANCE.md` (Fable; audited base
`9c2437a0`). Every verdict below was **re-verified against code/manifests/tests**, not trusted.
**Scope:** the four reported areas only — **F2** NodePort LAN exposure vs "tailnet-only"; **F3** inert
Tirith / fail-open vs the real Codex `danger-full-access` exec path; **F4** all-secrets env inheritance +
terminal-snapshot risk; **F5** legacy Hermes deployment/ClusterRole. (F1 backup, F6 overlay duplication,
F7 Telegram dedup, F8 version lag are out of scope here — see §Out-of-scope.)

**Port provenance:** the reviewed PASS remediation was authored in the isolated worktree
`uap-security-remediation-plan-20260724` at base `0932d705b0a7a2bddf4e858087c5921c2e569d89` and is ported
here by semantic re-application (not cherry-pick/reset). The only commit between that base and this one
(`6dbe224`, "fix(backup): strip raw MissionStore sidecars (#435)") touches exclusively backup files
(`hermes-agent-backup.yaml`, `hermes-mission-runtime.yaml`, `runbooks/hermes-agent-dr.md`,
`tests/static/test_hermes_backup.py`, `tools/hermes-mission/backup_validate.py`) — none of which overlap any
finding anchor below — so every verdict carries over unchanged. Only the **non-owner-gated** fixes are carried:
honest NodePort LAN+tailnet documentation, the extracted/tested `_scrubbed_child_env`, the honest
Codex/Tirith/MCP trust-boundary documentation, the terminal-cache emptyDir, this document, and
`tests/static/test_hermes_security_boundary.py`. The owner-gated NetworkPolicy/`externalTrafficPolicy`,
`allowPrivilegeEscalation:false`, legacy deletion and any credential change are **NOT** applied here (they
remain proposals below).

**Hard constraints honored:** no credential rotation, no external-authority change, no live-component
deletion, no topology change, no secret value printed, no live/cluster/GitHub mutation, no commit/push.
Implemented fixes are **file edits only** (take effect on the owner's PR-gated Flux deploy). Owner-gated
items are given as exact patches + blast radius + validation + an explicit decision to make.

---

## Экспресс-вердикт (RU)

- **P0 нет** — открытых дверей нет; app-auth (basic auth / bearer keys) держится, SA без k8s-токена,
  research-ребёнок (отдельный Codex child для untrusted-контента) scrubbed, overlay drift fails closed.
  MCP-серверы и мозг — в одном pod trust domain и отдельно НЕ scrubbed (см. §F4).
- **3 × P1 (F2, F3, F4)** — заявленная защита не совпадает с фактом. В этом проходе:
  - **F2:** ложные "tailnet-only" утверждения **убраны** из DECISIONS/манифестов/README (правда: NodePort
    bind `0.0.0.0` → доступно и в tailnet, и в home LAN; гейт только app-auth). NetworkPolicy — **owner-gated**
    (требует решения + live canary из-за SNAT/externalTrafficPolicy на NodePort).
  - **F3:** честно задокументировано, что Tirith **inert** (`HERMES_DISABLE_LAZY_INSTALLS=1` → бинарь не
    установлен; путь Codex не сканирует), а approval/scan/write-safe стек Hermes **не на пути** исполнения
    Codex (`danger-full-access`, `approval_policy=never`); pod = единственная граница.
    `allowPrivilegeEscalation:false` — **owner-gated** (нужен suid-helper canary).
  - **F4:** честно задокументирована ко-локация всех секретов в env gateway + наследование мозгом через
    `os.environ.copy()`; terminal-snapshot кэш (#62336) **затенён emptyDir** (не попадает на PVC/backup);
    allowlist research-ребёнка **зафиксирован детерминированным тестом** (required proxy vars proven).
    **ВАЖНО:** рекомендация Fable "удалить `CLAUDE_CODE_OAUTH_TOKEN` из pod" **ОПРОВЕРГНУТА** — он используется
    встроенным hermes claude-code скиллом в поде (см. §F4); НЕ удалять.
- **F5 (P2):** legacy Hermes (ClusterRole + NodePort 30890 + token-mounted SA) всё ещё в kustomization.
  Удаление — **owner-gated** (точный патч + canary ниже); в этом проходе НЕ удалён (запрет на delete live component).
- **Статический гейт зелёный:** `verify-local-ok` (static), все `tests/static/test_*.py`, `kubectl kustomize
  clusters/prod`, hermes unit tests. Новый тест `test_hermes_security_boundary.py` добавлен и проходит.

---

## Findings (verified @ 0932d70; re-confirmed @ 6dbe224 — see Port provenance)

| # | Sev | Verdict | Finding | Anchor (this base) | Action this pass |
|---|---|---|---|---|---|
| F2 | **P1** | Confirmed | NodePort `30911/30642/30890` bind `0.0.0.0` → LAN-reachable; **no NetworkPolicy** in `clusters/prod/infra`; docs claimed "tailnet-only" | `hermes-agent.yaml` Services; `hermes.yaml` Service; no netpol (only Flux's own in `flux-system/`); `DECISIONS.md` ADR-029 | false claims **removed**; netpol **owner-gated** |
| F3 | **P1** | Confirmed | Tirith not installed (lazy installs disabled) ⇒ does not scan the Codex brain path; Codex brain owns the loop with `danger-full-access`/`approval_policy=never`; Hermes approval/scan/write-safe stack is off that path | `hermes-agent-config.yaml` `codex-config.toml`; `HERMES_DISABLE_LAZY_INSTALLS=1` in `hermes-agent.yaml` | honest boundary **documented**; `allowPrivilegeEscalation:false` **owner-gated** |
| F4 | **P1** | Confirmed (mechanism) / not materialized | All app secrets co-located in one gateway env; brain inherits via `os.environ.copy()`; #62336 snapshot path exists in pinned image (not currently exercised) | `hermes-agent.yaml` gateway env; `hermes-agent-config.yaml` managed-env; `files/hermes_research_session.py` | co-location **documented**; terminal cache **emptyDir**; research allowlist **test-locked**; `CLAUDE_CODE_OAUTH_TOKEN` **kept** (refutes Fable) |
| F5 | **P2** | Confirmed | Legacy bespoke Hermes live: ClusterRole `hermes-pods-read` (cluster-wide get/list), token-mounted SA, NodePort `30890`, PARKED, no consumer | `hermes.yaml`; `kustomization.yaml` (`hermes.yaml`, `hermes-code-configmap.yaml`, `hermes-keys.sops.yaml`) | deletion **owner-gated** (patch below) |

---

## F2 — NodePort LAN exposure vs "tailnet-only"

### Verified facts
- `hermes-agent-dashboard` `:30911→9119` and `hermes-agent-api` `:30642→8642` are `type: NodePort`
  (`hermes-agent.yaml`); legacy `hermes` `:30890→8900` (`hermes.yaml`). A k3s NodePort binds `0.0.0.0` on
  **every** node interface ⇒ reachable on the tailnet **and** the home LAN (`192.168.0.0/24`). Fable's live
  probe from ops-1 confirmed OPEN on `192.168.0.201/.202`.
- **No NetworkPolicy** selects `app: hermes-agent` (the only netpols in the repo are Flux's own in
  `clusters/prod/flux-system/gotk-components.yaml`). The only gate is app-layer auth: dashboard basic auth,
  API/mission bearer keys, `/terminal` local-only. ⇒ defense-in-depth + false-claim gap, **not** an open door.

### Implemented (this pass)
Removed the false "tailnet-only" framing (now states: reachable on tailnet **and** home LAN, app-auth-gated,
no NetworkPolicy yet):
- `DECISIONS.md` ADR-029 "Последствия" — was "exposed only on the tailnet NodePort".
- `clusters/prod/infra/hermes-agent.yaml` — dashboard Service comment.
- `clusters/prod/infra/hermes.yaml` — legacy Service comment.
- `hermes/README.md` — the two factual "tailnet-only" claims + the "Live" section.

### Owner-gated: namespace NetworkPolicy (needs a decision + live canary)
**Why owner-gated:** a netpol on a **NodePort** service is subtle — by default NodePort traffic is SNAT'd to
the node IP, so the pod sees the *node* source, not the client's tailnet IP; an `ipBlock` allowlist may not
match unless `externalTrafficPolicy: Local` is set (which then only answers on nodes running the pod). This
can break the dashboard/API/build-1 poll if misconfigured ⇒ behavior-changing, live-validated only.

**Proposed file** `clusters/prod/infra/hermes-agent-netpol.yaml` (NOT created here — would trip the
kustomization-orphan static check until wired in):
```yaml
# Restrict hermes-agent ingress to the tailnet CIDR. k3s ships a NetworkPolicy controller (no CNI change).
# REQUIRES externalTrafficPolicy: Local on the two Services below, else NodePort traffic is SNAT'd to the
# node IP and this ipBlock will NOT match (=> locked out). Apply together, then run the canary.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-agent-tailnet-only
  namespace: uap-system
spec:
  podSelector:
    matchLabels:
      app: hermes-agent
  policyTypes: [Ingress]
  ingress:
    - from:
        - ipBlock: { cidr: 100.64.0.0/10 }   # tailnet CGNAT: ops-1, build-1 (mission poller), owner devices
      ports:
        - { protocol: TCP, port: 9119 }       # dashboard
        - { protocol: TCP, port: 8642 }       # mission/central API
```
Plus, on both Services in `hermes-agent.yaml`:
```yaml
spec:
  type: NodePort
  externalTrafficPolicy: Local   # preserve client tailnet source IP so the netpol ipBlock matches
```
**Blast radius:** dashboard + mission API become reachable **only** from `100.64.0.0/10`. With
`externalTrafficPolicy: Local`, `:30911/:30642` answer **only on `uap-home-2`** (the node the pod is pinned
to) — the other node stops serving them. Telegram is unaffected (it is egress long-poll, not ingress). The
build-1 dispatcher poll (`100.85.56.31`) and Workspace are inside the CIDR ⇒ allowed.
**Validation:** `kubectl kustomize clusters/prod` builds; then the live canary below.
**Owner decision:** _"Approve adding the NetworkPolicy + `externalTrafficPolicy: Local` to restrict
hermes-agent ingress to the tailnet CIDR, accepting that the NodePorts then answer only on uap-home-2."_
**Alternative (host firewall):** the repo already ships `infra/k3s/uap-k3s-lan-firewall.service` (drops
`6443/10250/8472` on the LAN iface). The NodePorts could be restricted there instead (ansible-managed) — a
host-level change, also owner-gated.

---

## F3 — inert Tirith / fail-open vs the Codex `danger-full-access` exec path

### Verified facts
- `codex-config.toml` (`hermes-agent-config.yaml`): `sandbox_mode = "danger-full-access"`,
  `approval_policy = "never"`. The Codex subprocess **owns the inner tool loop**; Hermes' approvals,
  dangerous-command checks, Tirith scanner and `HERMES_WRITE_SAFE_ROOT` gate **Hermes' own** terminal tool —
  not the brain's shell.
- `HERMES_DISABLE_LAZY_INSTALLS=1` (`hermes-agent.yaml`) disables lazy install ⇒ the Tirith binary is **not
  installed**, and it does **not scan the Codex brain path** regardless (the brain's shell is the Codex
  subprocess, not Hermes' terminal tool) ⇒ **inert**. (The upstream `tirith_fail_open` default is not
  re-verified against the pinned image here, so no claim is made about fail-open/silent behavior.)
- The ADR-027 loop-guardrail patch is a genuine runaway-loop circuit-breaker (failure-count halts), **not** a
  content/command safety scanner. The pod is the **sole** boundary.
- Precedent: `singbox-egress-ha.yaml` already sets `allowPrivilegeEscalation: false`; the gateway does not
  (manifest comment: "safe future add … pending a check for any suid helper").

### Implemented (this pass)
- `hermes-agent-config.yaml` `codex-config.toml` — added an explicit **HONEST SECURITY BOUNDARY** note: the
  approval/scan/write-safe stack is off the Codex path; Tirith is not installed and does not scan the brain
  path; the brain inherits the full secret env and can read `/proc/self/environ`/`.env`/`auth.json`; the pod
  is the sole boundary; MCP server processes and the brain share the pod trust domain and are NOT proven
  separately scrubbed — only the research Codex child is scrubbed (`_scrubbed_child_env`).
- `docs/research/nousresearch-hermes-agent.md` — annotated the upstream Tirith description as **upstream
  capability, not UAP's deployed state** (Tirith inert here).

### Owner-gated: `allowPrivilegeEscalation: false` on the gateway container
**Why owner-gated:** sets `no_new_privs`; it does **not** block root→uid-10000 `setuid()` *drop* (s6 still
works), but it **would** break any suid helper the brain/shell relies on. The manifest itself flags "pending a
check for any suid helper" ⇒ needs a live roll canary, not a blind apply.
**Proposed patch** (`hermes-agent.yaml`, gateway container — add alongside the existing pod-level
`securityContext`; note this is a *container*-level block):
```yaml
        - name: gateway
          image: nousresearch/hermes-agent@sha256:b6c0192278…d6cc0f
          args: ["gateway", "run"]
          securityContext:
            allowPrivilegeEscalation: false   # blocks gaining privs, not the s6 setuid() DROP to uid 10000
```
**Blast radius:** if any in-pod suid helper is used by the brain/shell, that call fails after the roll.
**Validation:** roll a single pod; confirm s6 drops to uid-10000 (services Ready), one Telegram round-trip,
one mission end-to-end, and a `build1 "echo ok"` shell round-trip.
**Owner decision:** _"Approve `allowPrivilegeEscalation: false` on the gateway container after the suid-helper
canary passes."_

---

## F4 — all-secrets env inheritance + terminal-snapshot risk

### Verified facts
- Gateway container env co-locates **all** app authorities: `API_SERVER_KEY`, `HERMES_MISSION_OWNER_KEY`,
  `HERMES_MISSION_PRODUCER_KEY`, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`, `CLAUDE_CODE_OAUTH_TOKEN`, plus
  `auth.json`/`.env` on the PVC. The brain is spawned with `os.environ.copy()` and runs `danger-full-access`
  ⇒ it inherits the full set and can also read `/proc/self/environ`. The pod is the only boundary.
- **Research child IS correctly scrubbed** (`files/hermes_research_session.py`): env rebuilt to
  `{PATH, HTTPS_PROXY, HTTP_PROXY, NO_PROXY}` + per-request `HOME`/`CODEX_HOME`, proxy vars proven via
  `setdefault`, child runs `--sandbox read-only --disable shell_tool --ignore-user-config` with only
  `auth.json` copied into an ephemeral `CODEX_HOME`. This is the **only** separately-scrubbed child (the
  untrusted-content boundary). **MCP server processes are NOT proven separately scrubbed:** the
  `[mcp_servers.build1]` stdio server is spawned by the Codex brain inside the same pod; whether the codex
  CLI strips its env is not verified here, so it is treated as sharing the pod trust domain with the brain.
- **#62336** ("terminal env snapshots capture credential-bearing env to disk") precondition (secrets in env)
  holds and the terminal backend is `local`; the path exists in the pinned image but is **not currently
  exercised** (Fable live `find` = 0 snapshots, because the Codex loop, not Hermes' terminal tool, drives
  execution). If any skill ever invokes Hermes' local terminal tool, snapshots would land on the PVC → R2.

### ⚠ Key verification — refutes Fable PR-1 sub-fix (b)
Fable recommended **dropping `CLAUDE_CODE_OAUTH_TOKEN` from the gateway env**, claiming "the pod never calls
`claude` locally; it is only needed on build-1." **This is contradicted by UAP's own runbook:**
`runbooks/claude-routing-goal.md` (R3 result) states pod-local `claude` was deliberately **kept** because
removing/shimming it "рискует сломать встроенный hermes claude-code скилл (использует
`CLAUDE_CODE_OAUTH_TOKEN` в поде)". The `claude` CLI is installed in the initContainer
(`@anthropic-ai/claude-code@2.1.193`) and `runbooks/hermes-agent-codex-brain.md` documents the in-pod token.
**Decision: do NOT remove `CLAUDE_CODE_OAUTH_TOKEN`.** Its removal is not "required variables proven" — the
required variable is documented as in-use. Removing it risks breaking the built-in claude-code skill ⇒
violates "do not break children". The correct F4 action is **honest documentation + boundary hardening**, not
token removal. (If the owner later confirms the in-pod claude-code skill is fully retired, removal becomes a
one-line manifest deletion + a static negative test.)

### Implemented (this pass)
1. **Honest co-location documentation** — `codex-config.toml` note (see F3) states the brain inherits the full
   secret env and the pod is the sole boundary; no gateway↔brain credential separation is claimed.
2. **Terminal-snapshot mitigation (#62336)** — `hermes-agent.yaml`: added an emptyDir `terminal-cache` volume
   mounted at `/opt/data/cache/terminal` (HERMES_HOME-relative snapshot location per upstream
   `tools/environments/base.py`). Any future local-terminal snapshot lands on the ephemeral emptyDir (gone on
   roll, never in the PVC/backup) instead of the durable PVC. Non-destructive: the dir is disposable and
   currently absent; if the path differs the mount is harmless. **Canary below** to confirm the path before
   relying on it.
3. **Behavior-preserving refactor + deterministic negative test** — `files/hermes_research_session.py`:
   extracted the child-env allowlist into `_CHILD_ENV_ALLOWLIST` + a pure `_scrubbed_child_env()` (identical
   output). `tests/static/test_hermes_security_boundary.py` proves: NO gateway secret
   (`API_SERVER_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `HERMES_MISSION_*_KEY`, dashboard pw, `TELEGRAM_BOT_TOKEN`)
   inherits into the research child; the required egress proxy vars are present even when absent from the base
   environ; an explicit proxy is preserved (not overridden).

### Owner-gated
- **Confirm the terminal-cache path** (canary below) — if Hermes resolves the snapshot cache elsewhere, adjust
  the emptyDir `mountPath`.
- **(Deferred, NOT recommended now)** `CLAUDE_CODE_OAUTH_TOKEN` removal — only after the owner confirms the
  in-pod claude-code skill is retired.

---

## F5 — legacy Hermes deployment/ClusterRole (owner-gated deletion)

### Verified facts
- `hermes.yaml` is still in `kustomization.yaml` (`hermes.yaml`, `hermes-code-configmap.yaml`,
  `hermes-keys.sops.yaml`). It carries a **ClusterRole** `hermes-pods-read` (cluster-wide get/list on
  pods, pods/log, services, events, namespaces, nodes, deployments) + ClusterRoleBinding, a ServiceAccount
  whose token **is** mounted (no `automountServiceAccountToken: false`, unlike hermes-agent), and NodePort
  `:30890` (LAN-reachable, F2). STATUS/CLAUDE/memory mark it **PARKED / superseded**; no mission/overlay/tools
  code references the legacy `hermes` Service.
- `hermes-keys` (`LITELLM_KEY`/`HERMES_KEY`/`HERMES_KEYS_JSON`) is referenced **only** by `hermes.yaml` +
  `hermes-code-configmap.yaml`; `litellm.yaml` uses its own `litellm-keys.sops.yaml`. ⇒ all three resources
  can be pruned together.

### Proposed patch (NOT applied — deletion of a live component is owner-gated)
`clusters/prod/infra/kustomization.yaml` — remove these three lines:
```diff
-  - hermes-keys.sops.yaml
-  - hermes-code-configmap.yaml
-  - hermes.yaml
```
Flux then prunes: Deployment `hermes`, Service `hermes` (:30890), ClusterRole/ClusterRoleBinding
`hermes-pods-read`, ServiceAccount `hermes`, ConfigMap `hermes-code`, Secret `hermes-keys`.
**Pre-check (required):** confirm no consumer hits `:30890` —
`kubectl -n uap-system logs deploy/hermes --tail=2000 | grep -iE 'GET|POST' | tail` (it has been up ~31d, so a
quick scan settles it). Optionally also remove the now-dead `hermes/` source tree + `hermes/tests` + docs in a
follow-up (repo cleanup, owner's call).
**Blast radius:** removes a PARKED, token-mounted, cluster-readable, LAN-exposed component with no job.
LiteLLM is unaffected (own keys). No other manifest references the legacy Service.
**Validation:** `kubectl kustomize clusters/prod` builds; after merge, `kubectl -n uap-system get
deploy,svc,clusterrole | grep -w hermes` shows the legacy objects gone and `flux reconcile` clean; hermes-agent
unaffected.
**Owner decision:** _"Approve removing legacy Hermes (`hermes.yaml`, `hermes-code-configmap.yaml`,
`hermes-keys.sops.yaml`) from the kustomization after the `:30890` no-consumer pre-check."_

---

## Changed files (this pass — edits only, no commit/push/deploy)

| File | Change | Finding |
|---|---|---|
| `clusters/prod/infra/files/hermes_research_session.py` | behavior-preserving refactor: `_CHILD_ENV_ALLOWLIST` + `_scrubbed_child_env()` | F4 |
| `clusters/prod/infra/hermes-agent.yaml` | emptyDir `terminal-cache` → `/opt/data/cache/terminal`; honest dashboard Service comment | F4, F2 |
| `clusters/prod/infra/hermes-agent-config.yaml` | `codex-config.toml` HONEST SECURITY BOUNDARY note (Tirith inert, brain inherits env, pod = sole boundary) | F3, F4 |
| `clusters/prod/infra/hermes.yaml` | honest legacy Service comment (not tailnet-only) | F2 |
| `DECISIONS.md` | ADR-029: removed "exposed only on the tailnet NodePort" false claim | F2 |
| `hermes/README.md` | removed factual "tailnet-only" claims; honest LAN-reachable note | F2 |
| `docs/research/nousresearch-hermes-agent.md` | annotated upstream Tirith as not UAP's deployed state (inert here) | F3 |
| `tests/static/test_hermes_security_boundary.py` | **new** deterministic gate (CI auto-discovers `tests/static/test_*.py`) | F2/F3/F4 |

**Not changed (deliberately):** `auth.json`/codex-auth (OpenAI/Codex auth intact), gateway env secret set
(`CLAUDE_CODE_OAUTH_TOKEN` kept), research child behavior (preserved by the behavior-identical refactor; MCP
server processes unchanged — they share the pod trust domain and are not separately scrubbed),
`kustomization.yaml` (no deletion), no NetworkPolicy/`allowPrivilegeEscalation` applied (owner-gated).

## Tests
- **New:** `tests/static/test_hermes_security_boundary.py` → `hermes-security-boundary-ok`. Locks: research
  child env allowlist (no secret inherits; proxy vars proven), terminal-cache emptyDir, honest co-location
  (gateway still carries the secret set by design), SA token not mounted, `HERMES_DISABLE_LAZY_INSTALLS=1`,
  `danger-full-access`/`approval=never` + honest boundary documented, NodePort Services, false "tailnet-only"
  claims absent. It also locks the precise trust-domain wording — MCP server processes and the brain share
  the pod trust domain and are NOT proven separately scrubbed; ONLY the research Codex child is scrubbed — and
  forbids the unverified claims (no `tirith_fail_open` default, no "MCP-stdio children are env-scrubbed").
- **Gate run (Windows, static):** `verify-local-ok`; all `tests/static/test_*.py` pass (incl. the existing
  `test_hermes_mission_deployment.py`); `secret-scan-ok`; `iac-static-ok`; `kubectl kustomize clusters/prod`
  builds; hermes unit tests pass.
- **CI parity:** `static-checks` runs `secret_scan.py`, `validate_iac.py`, `tests/static/test_*.py` (picks up
  the new test), `kustomize build clusters/prod`, gitleaks. The new test file uses only placeholder secret
  *names*/low-entropy values (`"api-secret"` etc.) — no real secret, no gitleaks/secret-scan trigger.

---

## Exact live canaries (owner runs post-deploy, from ops-1 / build-1)

```bash
# 0) Rollout healthy after the PR merges + Flux reconciles
kubectl -n uap-system rollout status deploy/hermes-agent
kubectl -n uap-system get pod -l app=hermes-agent -o wide

# F4 terminal-cache path confirmation (emptyDir, not PVC)
kubectl -n uap-system exec deploy/hermes-agent -c gateway -- mount | grep '/opt/data/cache/terminal'
kubectl -n uap-system exec deploy/hermes-agent -c gateway -- find /opt/data -name 'hermes-snap-*.sh' 2>/dev/null | wc -l   # expect 0

# F4 research child still scrubbed + brain auth intact (one research round-trip; then a trivial brain turn)
#   - research: ask the agent a bounded web-search question in Telegram -> durable result, no error
#   - brain:    ask "2+2" -> Codex answers (proves os.environ egress + auth.json still work)

# F2 exposure truth (from ops-1, on the LAN) — document, don't rely on tailnet-only
for hp in 192.168.0.201:30911 192.168.0.202:30642 192.168.0.201:30890; do
  timeout 3 bash -c "</dev/tcp/${hp%:*}/${hp#*:}" && echo "$hp OPEN" || echo "$hp closed"; done
# If the owner-gated NetworkPolicy + externalTrafficPolicy:Local is applied:
kubectl -n uap-system get netpol hermes-agent-tailnet-only
#   allowed path still works (dashboard basic-auth + a mission API poll from build-1), and a non-tailnet
#   source is refused.

# F3 (if allowPrivilegeEscalation:false applied): s6 still dropped to uid 10000 + shell works
kubectl -n uap-system exec deploy/hermes-agent -c gateway -- id -u hermes 2>/dev/null || true
#   one Telegram round-trip + one mission end-to-end + `build1 "echo ok"`.

# F5 (if legacy deletion applied): objects pruned, Flux clean, hermes-agent unaffected
kubectl -n uap-system get deploy,svc,clusterrole,clusterrolebinding | grep -w hermes || echo "legacy hermes gone"
kubectl -n uap-system get deploy hermes-agent   # still 1/1
```

## Owner decisions required (explicit)
1. **F2 NetworkPolicy** — approve `hermes-agent-tailnet-only` netpol + `externalTrafficPolicy: Local`
   (NodePorts then answer only on `uap-home-2`), with the live canary. _(or the host-firewall alternative)_
2. **F3 `allowPrivilegeEscalation: false`** — approve on the gateway container after the suid-helper canary.
3. **F5 legacy Hermes deletion** — approve removing `hermes.yaml` + `hermes-code-configmap.yaml` +
   `hermes-keys.sops.yaml` from the kustomization after the `:30890` no-consumer pre-check.
4. **F4 `CLAUDE_CODE_OAUTH_TOKEN`** — **no action recommended now** (in use by the in-pod claude-code skill).
   Only if the owner confirms that skill is retired: one-line env deletion + a static negative test.

## Out of scope (noted, not actioned here)
- **F1 backup:** already improved in this base vs the audit base — the dump image digest now **matches** the
  gateway (`b6c0192278…` v0.18.0) and `hermes-agent-backup.yaml` runs `backup_validate.py --replace-mission
  /opt/data/missions-v1.sqlite3` (explicit `sqlite3.backup()`). The *restore drill* is still unexercised
  (owner-gated, destructive) — track separately.
- **F6/F7/F8** (overlay duplication, Telegram dedup, v0.18→v0.19 lag) are upgrade-coupled; no change here.

---

_No files were deployed, committed, or pushed. No cluster/GitHub/live mutation. No secret value read or
emitted (env inspected by key name only). All changes are isolated-worktree file edits pending the owner's
PR-gated deploy._
