# vpnrouter-gateway — Proxy-mode feature spec (handoff)

Date: 2026-07-10. Author: UAP agent session (Phase 0 evaluation, see
`docs/research/vpnrouter-gateway-egress-goal.md` §10). Target repo: `github.com/PavelLizunov/vpnrouter-gateway`.
This document is self-contained — paste it into the gateway repo (or its Claude session) as-is.

**TL;DR (RU):** добавить в vpnrouter-gateway «proxy mode» — рендер sing-box конфига с `mixed`-инбаундом
(`:12080`), явной urltest-группой ИЛИ одним запиненным сервером, и БЕЗ `direct`-аутбаунда/nftables. Только
authoring-пайплайн (check/resolve/render/plan); apply/doctor хостовые остаются gateway-only. Это делает тул
пригодным для контейнерных/headless egress-потребителей (первый — UAP), не трогая ни байта в gateway-режиме.

## 0. Context — who needs this and why

The consumer (UAP, the owner's k8s homelab) evaluated the tool as the manager for its load-bearing LLM egress
(2026-07-10, full evidence in the consumer repo). The evaluation **passed** on subscription ingestion, JSON
contract, plan/doctor/rollback discipline and redaction — but adoption was blocked by exactly three render
gaps. Its egress consumers are **HTTP CONNECT proxy clients** (`HTTPS_PROXY=http://…:12080`) inside
Kubernetes pods, not LAN hosts behind a NIC:

1. Render emits only a `tun` inbound — consumers need a **`mixed` inbound on a configurable ip:port**.
2. Render emits exactly one selected outbound — the HA consumer needs an **explicit `urltest` failover group**
   over all resolved subscription nodes.
3. Render always emits a `direct` outbound (+ `ip_is_private` → direct) — the consumer's invariant is
   **no `direct`, ever** (a misconfig must not leak from the origin IP); its pods also run with all Linux caps
   dropped, so nftables/TUN are unavailable there anyway.

Product value beyond this consumer: docker/k8s sidecars and headless VPS proxies are a wider audience than
LAN gateways; proxy mode reuses the existing subscription/validate/plan/redaction machinery unchanged.
The deep-review stance ("no hidden auto-failover") is respected: urltest is **explicit opt-in**
(`strategy = "urltest"`), never a default, and stays proxy-mode-only in this iteration — the
UDP/voice concerns that motivated deferring `pinned_outbound`/`no_failover` do not apply to an HTTP proxy.

## 1. Scope

**Phase A (this spec): authoring pipeline only.**
`check`, `resolve-subscription`, `render` (new command), `plan` work in proxy mode. **No host-mutation
changes**: `apply`/`rollback`/`doctor` remain gateway-only and must refuse loudly in proxy mode. The consumer
deploys the rendered artifact through its own pipeline (SOPS → GitOps → k8s Secret → pod).

**Phase B (later, NOT this spec):** host runtime for proxy mode (systemd unit serving the proxy on a box;
nft-less apply/doctor). Do not build it now.

**Non-goals:** hysteria2/tuic parsing (separate roadmap item), health-probe daemon, any behavior change in
gateway mode (existing goldens must stay byte-identical), destination-based routing.

## 2. TOML surface (additive; absent `mode` = gateway → zero behavior change)

```toml
mode = "proxy"                     # NEW top-level enum: "gateway" (default) | "proxy"

[proxy]                            # NEW section, required iff mode = "proxy"
listen = "::"                      # default "::"
port = 12080                       # required; 1..=65535

[subscription]                     # existing section
url = "https://…"                  # as today (the URL is the secret; redaction unchanged)
strategy = "urltest"               # NEW: "pinned" (default, = today's semantics) | "urltest"
active = "Germany VLESS"           # required iff strategy = "pinned"; forbidden iff "urltest"

[subscription.urltest]             # NEW, optional; defaults as shown (proven in production by the consumer)
probe_url = "https://www.gstatic.com/generate_204"
interval = "30s"
tolerance = 100
idle_timeout = "30m"
interrupt_existing = true          # maps to sing-box interrupt_exist_connections
```

Validation matrix (all load/validate-time, loud, stable codes):

| Condition | New error code |
|---|---|
| `mode = "proxy"` and `[proxy]` absent | `PROXY_SECTION_REQUIRED` |
| `mode = "proxy"` and any of `[interfaces] [routing] [tun] [[policies]] [dns] [killswitch] [management]` present | `PROXY_MODE_SECTION_CONFLICT` (name the section) |
| `mode = "proxy"` and `[subscription]` absent | `PROXY_SUBSCRIPTION_REQUIRED` |
| `strategy = "pinned"` and `active` empty/absent | `SUBSCRIPTION_ACTIVE_EMPTY` (existing code, reuse) |
| `strategy = "urltest"` and `active` set | `URLTEST_ACTIVE_CONFLICT` |
| `strategy = "urltest"` and `mode = "gateway"` | `URLTEST_GATEWAY_UNSUPPORTED` (keep urltest proxy-only for now) |
| `proxy.port` = 0 | `PORT_INVALID` (existing code, reuse) |

Implementation note: `interfaces`/`routing` are currently required struct fields — make them `Option<…>` and
enforce per-mode in `validate()` (gateway: required; proxy: must be `None`). `deny_unknown_fields` stays.

## 3. Render targets (the contract)

Proxy + **urltest** (synthetic values; this is the golden-fixture shape):

```json
{
  "inbounds": [
    { "type": "mixed", "tag": "in", "listen": "::", "listen_port": 12080 }
  ],
  "log": { "level": "warn" },
  "outbounds": [
    { "type": "vless", "tag": "Node A", "server": "…", "server_port": 443, "uuid": "…", "…": "…" },
    { "type": "vless", "tag": "Node B", "server": "…", "server_port": 443, "uuid": "…", "…": "…" },
    { "type": "urltest", "tag": "auto", "outbounds": ["Node A", "Node B"],
      "url": "https://www.gstatic.com/generate_204", "interval": "30s", "tolerance": 100,
      "idle_timeout": "30m", "interrupt_exist_connections": true }
  ],
  "route": { "final": "auto" }
}
```

Proxy + **pinned**: same shape, exactly one vless outbound, **no** urltest group,
`route.final` = the active outbound's tag.

Rules:
- **No `direct` outbound. No `dns` block. No `route.rules`.** `log.level = "warn"` in proxy mode.
- Outbound tags = subscription display names, deduplicated deterministically (`-1`, `-2` suffix in input
  order — duplicate names DO occur in real panels).
- Determinism: byte-identical output for identical (config, cache) inputs — extend the golden tests.
- Byte-parity with the consumer's legacy python generator is NOT a goal; the contract is: `sing-box check`
  green + the shape above. (e.g. `packet_encoding: "xudp"` from the existing parser is a fine superset.)

## 4. Subscription changes

- **Cache v2**: the current cache stores ONE chosen outbound; urltest needs ALL. New shape:
  `{"v": 2, "source": <redacted>, "active": <optional>, "outbounds": [<all parsed>]}`.
  Keep v1 files readable (v1 == the pinned case); anything else → loud "re-run resolve-subscription".
- **`resolve-subscription --active NAME`** (new flag): select + cache without a `[subscription]` block in the
  config. Today `active` comes only from the config file; with `--url` + `--active` a consumer can keep the
  secret URL entirely out of committed files (pass it from its secret store at regen time).
- **Node safety (both modes):** a node whose `security` is neither `tls` nor `reality` (would render a
  plaintext outbound), or `reality` without `pbk`, must NOT be emitted — surface it in `skipped_unsupported`
  with a `reason` field. Error only if zero usable nodes remain. (Today such a node renders silently; that
  violates the consumer's no-clear-egress invariant and the tool's own killswitch spirit.)

## 5. CLI additions

- **`render --config PATH [--state-dir DIR] --out DIR [--json]`** (new command, both modes): pure render of
  the artifacts (proxy: `sing-box.json`; gateway: `sing-box.json` + `nft.rules`) into `--out`, files `0600`.
  The JSON envelope reports **paths + byte sizes only — never config content** (it contains uuids; the
  existing redaction discipline applies to stdout).
- **`plan`** works in proxy mode: diff rendered vs `state-dir/current`, risks = `OUTBOUND_UNRESOLVED` etc.;
  the SSH-risk check is skipped (no routing changes in proxy mode).
- **`apply` / `rollback` / `doctor` in proxy mode** → error `PROXY_MODE_NOT_APPLYABLE` (exit 2) with a
  suggestion pointing at `render --out`. (Phase B lifts this.)

## 6. Implementation sketch (repo-specific)

- `config.rs`: `mode: Mode` (serde default = Gateway), `proxy: Option<Proxy>`, `strategy`/`urltest` knobs on
  `Subscription`; `interfaces`/`routing` → `Option`; the validation matrix above; keep `deny_unknown_fields`.
- `render.rs`: new `render_proxy_sing_box(cfg, outbounds: &[Value]) -> String` beside the existing function —
  two distinct shapes, do not force premature sharing.
- `subscription.rs`: cache v2 + strict node filter (+ `reason` on `Skipped`).
- `main.rs`: mode dispatch, `render` command, `--active`/`--out` flags.
- Tests: 2 new goldens (proxy pinned / proxy urltest), determinism, the validation matrix, cache v1→v2
  compat, plaintext-node skip, tag dedup. All 45 existing tests + gateway goldens must pass unmodified.
- Estimated ~400–500 lines incl. tests. **No new dependencies** (stays at the current 6);
  clippy `-D warnings` + fmt + the blocking pre-commit hook as usual.

Suggested order (one session): config+validation (tests first) → subscription cache v2+filter → render_proxy
+ goldens → `render` command + envelope → proxy-mode `plan` + refusal errors → docs (architecture deferred
list, HANDOFF next-work, `examples/gateway-proxy.toml`).

## 7. Acceptance criteria (the consumer will verify against these)

1. `resolve-subscription --url $SUB_URL --active "X"` + a pinned proxy config → `render` → `sing-box check`
   green; artifact = `mixed` on `:12080`, exactly ONE vless outbound, `final` = its tag, **no `direct`**.
2. An urltest proxy config against a real multi-node subscription → one vless outbound per usable node + the
   `auto` group with exactly `interval 30s / tolerance 100 / idle_timeout 30m /
   interrupt_exist_connections true / gstatic probe_url`, **no `direct`**, `final = "auto"`.
3. The consumer's existing SNI pre-flight (diffs any sing-box JSON keyed by `(server, server_port)`) runs
   against the rendered artifact **with zero changes on the consumer side**.
4. Rendering twice from identical inputs → byte-identical files.
5. stdout of every command remains secret-free (uuid/short_id/url redaction unchanged).
6. Gateway mode untouched: existing goldens byte-identical, all existing tests green.

## 8. Why this is worth doing (product framing)

The consumer's platform already replaced its ad-hoc python generator with a gated pipeline (SNI drift
pre-flight, decrypt-verify, PR-previewed rotations) — proxy mode lets `vpnrouter-gateway` subsume that
generator entirely (Level 1 adoption), with the same binary later graduating to the host-runtime path
(Phase B / Level 2) if wanted. First real external consumer, real dogfood, and a genuinely wider product
surface (containers, not just LAN gateways).
