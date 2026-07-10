# GOAL — Adopt `vpnrouter-gateway` as UAP's managed VLESS egress

Date: 2026-07-09
Status: research draft for staged execution. No secrets/subscription tokens stored here.
Scope: evaluate + pilot the owner's own `vpnrouter-gateway` (github.com/PavelLizunov/vpnrouter-gateway) as a
replacement for UAP's hand-managed in-cluster sing-box egress, with a dual benefit — better egress ops for the
platform AND real-world dogfooding of the product on always-on infra under RU-DPI.

## 1. Executive summary

**Goal:** replace UAP's ad-hoc egress config lifecycle (`infra/sops/gen-singbox-failover.py` → SOPS → Flux →
pod roll, with **no plan/rollback/doctor**) with `vpnrouter-gateway`'s declarative `gateway.toml → validate →
render → plan → apply --yes → doctor → rollback` — **staged**, never big-bang on the load-bearing egress.

**Why now (evidence):** on 2026-07-09 a pinned German VLESS exit silently changed its REALITY target
(`www.microsoft.com`→`yahoo.com`) → subfleet down (ECONNRESET on every request). Fixing it required: manual
config regen, a SOPS secret that **got corrupted by a hand-copied base64** (Flux "no identity matched"), and an
isolated temp-pod test to prove the new config wouldn't brick the egress. Every one of those steps is a
first-class feature of `vpnrouter-gateway`: `plan` (preview), `doctor` (diagnose cert/target drift), `rollback`
(undo), and the invariant "a bad config/subscription cannot brick the gateway (proven live)". So the tool
directly targets pain we just paid for.

**Decision:** worth adopting, but the topology differs (see §3), so adoption is two-level and pilot-first.

## 2. Evidence basis / current state

- **UAP egress today (two in-cluster sing-box Services in `uap-system`):**
  - `singbox-egress` — **single fixed** VLESS+REALITY exit, HTTP proxy on `:12080`. Consumed by **subfleet**
    (Claude-subscription bridge). Its OAuth is **IP-pinned** → this exit must NOT rotate/urltest.
  - `singbox-egress-ha` — sing-box with a **`urltest`** outbound (auto-failover across the ninitux subscription,
    30s probes, `interrupt_exist_connections`), HTTP proxy on `:12080` (+ NodePort `:30880`). Consumed by
    hermes-agent (brain + Telegram) + build-1 (cargo/knowledge/ai-search) + the whole RU-DPI-throttled path.
  - Config = SOPS-encrypted sing-box JSON, authored by `infra/sops/gen-singbox-failover.py` from the ninitux
    subscription (`https://ninitux.com/api/v1/app/config/<token>`, base64 list of `vless://` URIs). No
    plan/rollback/doctor; changes = regen + SOPS + PR + Flux + roll. Diagnosis is by hand.
  - **Model = per-service HTTP CONNECT proxy** (`HTTPS_PROXY=…:12080`). We do NOT route the LAN at L3.
- **`vpnrouter-gateway` (the candidate):** headless Linux-first, one Rust binary (5 deps), strict-JSON CLI.
  `gateway.toml` → sing-box 1.13 JSON + nftables. Invariants: byte-deterministic render (golden tests), own
  nft table `inet vpnrouter` only (no `flush ruleset`), mutations only in `apply`/`rollback` with `--yes`,
  **SSH-guard** (apply refuses if it would cut the SSH session), `nft -c` + `sing-box check` **before** applying.
  Status: v1 CLI done, 45 tests, clippy/fmt clean, blocking pre-commit hook, live-validated on Proxmox
  (Debian 12 / Alpine 3.23) + a real subscription (VLESS/Reality, Hysteria2, TUIC).

## 3. The fit — and the gap

**Fit (high):** same domain (VLESS egress on Linux), owner's own tool (full control, no supply-chain risk,
dogfood synergy), directly solves demonstrated ops pain.

**Gap (the crux): topology.** Our egress is an **in-cluster HTTP-proxy** (pods set `HTTPS_PROXY`);
`vpnrouter-gateway` is a **host gateway** (nftables/NAT/L3 for a LAN). Not a drop-in. Two adoption levels:

- **Level 1 — config tooling only (low risk):** use `vpnrouter-gateway`'s `render`/`validate`/`plan` to author
  the sing-box config, keep the k8s Deployment + SOPS + Flux exactly as now. Replaces `gen-singbox-failover.py`
  with a golden-tested, validated, plan-previewable renderer. No re-architecture. **Requires** its render to
  emit a sing-box config with the **HTTP/mixed inbound on `:12080`** our pods consume, AND to support a
  **single-pinned outbound** (subfleet) as well as **urltest failover** (HA) — see §4.
- **Level 2 — full host gateway (higher value, higher risk):** egress moves to a host (ops-1 or a dedicated
  egress VM) running `vpnrouter-gateway`; the cluster reaches the internet through it. Gains apply/rollback/
  doctor/SSH-guard on the real thing. **Re-architects a load-bearing component** — if it breaks, the whole
  platform loses internet. Only after Level 1 proves the render + a pilot proves the runtime.

## 4. Key technical questions to resolve in Phase 0 (repo recon — gates everything)

1. **HTTP/mixed inbound:** can `gateway.toml` produce a sing-box **`mixed`/`http` inbound on `:12080`** (what our
   pods use as `HTTPS_PROXY`), or is it L3/NAT-only? If L3-only, Level 1 is impossible and Level 2 means also
   switching the cluster from proxy-mode to routed egress (much bigger).
2. **Single-pinned outbound:** does it support pinning to **ONE fixed server** (no urltest) for the subfleet
   OAuth-pin path? (Our `singbox-egress` must never rotate — rotating the exit IP breaks the pin; see
   `docs`/memory. The 2026-07-09 fix worked only because the IP stayed the same, sni changed.)
3. **urltest failover:** does it support the **auto-failover** outbound (our `singbox-egress-ha` urltest) with
   `interrupt_exist_connections` semantics?
4. **`no direct` invariant:** can we guarantee **no `direct` outbound is ever emitted** (so a misconfig can never
   leak from the RU origin IP)? Our current generator enforces this deliberately.
5. **Subscription ingestion:** does it read the ninitux subscription format (base64 `vless://` list, REALITY
   pbk/sid/sni/fp, flow xtls-rprx-vision, + WS+TLS variants), or do we feed it a rendered `gateway.toml`?
6. **Secret handling:** where do server UUIDs/keys live? Must stay SOPS-managed / never in git plaintext; how
   does that compose with `gateway.toml`?
7. **JSON contract:** is the strict-JSON output stable enough to drive from our pipeline / a Hermes tool?

## 5. Phased plan

### Phase 0 — Repo recon + decision gate (no infra change)
- Read `vpnrouter-gateway` source: `gateway.toml` schema, the sing-box render (inbound types, outbound
  pinning + urltest, `no direct`), subscription ingestion, secret model, JSON CLI.
- Answer all of §4. **Exit gate:** decide Level 1 feasible? Level 2 feasible? If HTTP-inbound unsupported →
  Level 1 blocked, reconsider.

### Phase 1 — Pilot on non-critical infra (dual: product dogfood)
- Install `vpnrouter-gateway` on a **spare box** (VPNRouter test-lab VM `debian-xfce`, or a throwaway VM) —
  NOT ops-1/cluster.
- Author `gateway.toml` from the real ninitux subscription; exercise `validate → render → plan → apply --yes →
  status → doctor → rollback` on a live subscription. Deliberately feed a **broken config** (dead server / bad
  sni) and confirm `doctor` catches it + `apply` refuses + the gateway is not bricked (the exact 2026-07-09
  scenario).
- Confirm it exposes a working **HTTP proxy on :12080** (curl `api.anthropic.com` through it → 401/reachable,
  not 000) and can **pin one server** + **urltest-failover** as separate profiles.
- **Exit gate:** render + runtime behave; the 2026-07-09 incident would have been a `plan`+`rollback` non-event.

### Phase 2 — Level 1 adoption (config tooling; low risk, reversible)
- Replace `infra/sops/gen-singbox-failover.py` with a `vpnrouter-gateway render` step in the egress config
  pipeline (still SOPS-encrypt the rendered sing-box JSON → PR → Flux → roll, unchanged).
- Keep BOTH Services (pinned `singbox-egress` + urltest `singbox-egress-ha`) — render each from its own
  `gateway.toml` profile. Gain: deterministic render + `validate` (sing-box check) + `plan` preview in CI.
- **Exit gate:** a subscription/server rotation is now render→plan→PR (previewed, validated) instead of
  hand-editing; rollback = git revert of the previewed change.

### Phase 3 — Level 2 (optional, later): host gateway
- Stand up `vpnrouter-gateway` as the egress on a dedicated always-on Linux box (candidate: a small VM, NOT
  ops-1 which already holds the router + SOPS + git — keep blast radius split).
- Point the cluster's proxy consumers at it; keep the in-cluster egress Deployments running as **instant
  rollback** until the host gateway is proven over days.
- Gains: real `apply`/`rollback`/`doctor`/SSH-guard/`nft -c` on the live egress; the "bad config can't brick"
  invariant on the actual thing.
- **Exit gate:** N days green (brain round-trips, subfleet, build-1 cargo all through the host gateway), then
  retire the in-cluster egress.

## 6. Invariants to preserve (non-negotiable)

- **subfleet OAuth pin:** its exit must be a **single fixed server** (no urltest); rotating the exit IP breaks
  the credential. `vpnrouter-gateway` must support pinning that path.
- **HA failover:** hermes/build-1 path keeps **urltest auto-failover** across the ninitux servers.
- **No `direct` outbound, ever** — a misconfig must not leak from the RU origin IP.
- **Secrets stay SOPS** — server UUIDs/keys/subscription token never in git plaintext.
- **Load-bearing = staged + instant-rollback** — never cut the live egress without a running fallback.

## 7. Risks

- **Blast radius:** egress down = the whole platform loses internet (brain, subfleet, cargo, ai-search). Level
  2 touches this directly → staged + fallback mandatory.
- **v1 maturity:** young (45 tests, single dev). Level 1 (render only) de-risks by keeping the proven k8s deploy.
- **Upstream servers:** the ninitux servers flap under RU-DPI (documented); the tool makes our *response*
  robust (plan/doctor/rollback) but does NOT fix bad upstream servers — that's still subscription/provider.
- **Topology mismatch:** if HTTP-inbound is unsupported, Level 1 dies and Level 2 balloons (proxy→L3 switch).

## 8. Open questions (owner)

1. First target: pilot on `debian-xfce` (test-lab) or a fresh throwaway VM?
2. Level 1 only (config tooling) for now, or aim at Level 2 (host gateway) as the end state?
3. If Level 2: which host — a new small egress VM (keeps ops-1 blast radius split) vs ops-1 itself?
4. Should the pinned-subfleet path and the urltest-HA path be TWO `vpnrouter-gateway` profiles, or keep
   subfleet's pin on the current hand-config and only move the HA path first?
5. Is dogfooding the product on UAP infra an explicit goal (affects how much we invest in Phase 1 depth)?

## 9. Success criteria

- Phase 0: §4 answered; go/no-go per level.
- Phase 1: `plan`/`doctor`/`rollback` demonstrably turn the 2026-07-09 incident into a non-event on a pilot box;
  HTTP-proxy `:12080` reachable through it.
- Phase 2: egress config changes are previewed + validated (no more blind SOPS edits / corrupted-transport class).
- Phase 3: live egress on the host gateway, N days green, in-cluster egress retired.
