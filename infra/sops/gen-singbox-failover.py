#!/usr/bin/env python3
"""Generate a sing-box egress config with urltest auto-failover from a ninitux
subscription. Reads the subscription JSON (key `config` = base64 list of vless://
URIs), emits a sing-box config with: a mixed inbound on :12080, one vless outbound
per server, a `urltest` outbound that auto-selects the fastest LIVE server and
migrates in-flight connections off a dead one, and route.final -> urltest.

This is for the HA (hermes-agent) egress ONLY. Do NOT point subfleet's IP-pinned
OAuth traffic at a urltest selector — it rotates exits and breaks the pin (see
clusters/staging-stage3/singbox-egress.yaml). No `direct` outbound is emitted, so a
misconfiguration can never exit clear from the RU origin IP.

Usage: gen-singbox-failover.py <subscription.json> <out config.json>
           [--against <deployed-config.json>] [--allow-sni-drift]
Prints a SECRET-MASKED summary to stdout for review.

SNI pre-flight gate (--against): diff the freshly-rendered servers against the
CURRENTLY-DEPLOYED sing-box config (fetch it on ops-1 with
`kubectl get secret singbox-egress-ha-config -n uap-system -o jsonpath='{.data.config\\.json}' | base64 -d`).
A server whose REALITY/TLS `server_name` changed vs deployed is the 2026-07-09
class that silently bricked subfleet — the gate FAILS CLOSED (exit 3) before
writing output, so `set -e` stops the regen before sops/PR. Confirm a reviewed
drift with --allow-sni-drift (or env ALLOW_SNI_DRIFT=1), mirroring the gateway's
--allow-ssh-risk plan-before-apply ack. Servers are matched by (host, port), NOT
display name: the subscription renames nodes, so name-matching would false-alarm.
"""
import json, base64, sys, re, os, urllib.parse as up


def sni_index(outbounds):
    """(server, port) -> (tag, server_name) for every vless outbound. Keyed by
    host+port (stable server identity) so a renamed node isn't a false add/remove."""
    return {
        (o.get("server"), o.get("server_port")): (o.get("tag"), o.get("tls", {}).get("server_name"))
        for o in outbounds
        if o.get("type") == "vless"
    }


def mask_host(h):
    """Show enough to identify the network, hide the exit. 104.194.156.93 -> 104.*.*.*"""
    if not h:
        return "?"
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return parts[0] + ".*.*.*"
    return parts[0][:2] + "***." + parts[-1] if len(parts) > 1 else "***"


# minimal flag parse (stdlib only): two positionals + optional gate flags/env.
_args, _pos, against = sys.argv[1:], [], None
ack = os.environ.get("ALLOW_SNI_DRIFT") == "1"
_i = 0
while _i < len(_args):
    a = _args[_i]
    if a == "--against":
        _i += 1
        against = _args[_i] if _i < len(_args) else sys.exit("--against needs a path")
    elif a == "--allow-sni-drift":
        ack = True
    else:
        _pos.append(a)
    _i += 1
if len(_pos) != 2:
    sys.exit("usage: gen-singbox-failover.py <subscription.json> <out config.json> "
             "[--against <deployed-config.json>] [--allow-sni-drift]")
sub_path, out_path = _pos
d = json.load(open(sub_path))
raw = base64.b64decode(d["config"]).decode()
uris = [u.strip() for u in raw.splitlines() if u.strip().startswith("vless://")]
if not uris:
    sys.exit("FATAL: no vless:// URIs decoded from subscription")

outbounds, tags, summary, used = [], [], [], set()
for i, u in enumerate(uris):
    p = up.urlparse(u)
    q = dict(up.parse_qsl(p.query))
    uuid = up.unquote(p.username or "")
    host = p.hostname
    port = int(p.port or 443)
    name = re.sub(r"\s+", " ", (up.unquote(p.fragment) or "").strip()) or f"vless-{i}"
    tag, base, n = name, name, 1
    while tag in used:
        tag = f"{base}-{n}"; n += 1
    used.add(tag); tags.append(tag)

    if not uuid or not host:
        sys.exit(f"FATAL: server {tag!r} missing uuid/host")
    ob = {"type": "vless", "tag": tag, "server": host, "server_port": port, "uuid": uuid}
    if q.get("flow"):
        ob["flow"] = q["flow"]
    sec = q.get("security")
    if sec == "reality":
        if not (q.get("sni") and q.get("pbk") and q.get("sid")):
            sys.exit(f"FATAL: server {tag!r} security=reality but missing sni/pbk/sid -> refusing to emit a broken outbound")
        ob["tls"] = {
            "enabled": True,
            "server_name": q["sni"],
            "utls": {"enabled": True, "fingerprint": q.get("fp") or "chrome"},
            "reality": {"enabled": True, "public_key": q["pbk"], "short_id": q["sid"]},
        }
    elif sec == "tls":
        if not q.get("sni"):
            sys.exit(f"FATAL: server {tag!r} security=tls but missing sni")
        ob["tls"] = {"enabled": True, "server_name": q["sni"], "utls": {"enabled": True, "fingerprint": q.get("fp") or "chrome"}}
    else:
        sys.exit(f"FATAL: server {tag!r} has unknown/empty security={sec!r} -> refusing to emit a plaintext outbound")
    ttype = q.get("type", "tcp")
    if ttype == "ws":
        ob["transport"] = {"type": "ws", "path": up.unquote(q.get("path", "/")),
                           "headers": {"Host": q.get("host") or q["sni"]}}
    elif ttype == "grpc":
        ob["transport"] = {"type": "grpc", "service_name": q.get("serviceName", "")}
    elif ttype != "tcp":
        sys.exit(f"FATAL: server {tag!r} unsupported transport type={ttype!r}")
    outbounds.append(ob)
    summary.append({"tag": tag, "host": host, "port": port, "security": sec, "transport": ttype,
                    "flow": q.get("flow"), "sni_set": bool(q.get("sni")), "pbk": "pbk" in q, "sid": "sid" in q})

# urltest: auto-select the fastest LIVE server; interrupt_exist_connections migrates
# in-flight traffic off a server that goes down (hermes is NOT IP-pinned, so this is safe).
auto = {"type": "urltest", "tag": "auto", "outbounds": tags,
        "url": "https://www.gstatic.com/generate_204", "interval": "30s",
        "tolerance": 100, "idle_timeout": "30m", "interrupt_exist_connections": True}

config = {
    "log": {"level": "warn"},
    "inbounds": [{"type": "mixed", "tag": "in", "listen": "::", "listen_port": 12080}],
    "outbounds": outbounds + [auto],   # NO `direct` outbound: every byte must exit via a VLESS tunnel
    "route": {"final": "auto"},
}

# SNI pre-flight gate: diff the freshly-rendered servers against the deployed
# config. Fail closed (exit 3) on any SNI change / pool add / pool remove unless
# the drift is acked -- the exact 2026-07-09 review-before-deploy that was missing.
if against is not None:
    dep = json.load(open(against))
    new_idx, dep_idx = sni_index(config["outbounds"]), sni_index(dep.get("outbounds", []))
    changed = [(t, mask_host(k[0]), dep_idx[k][1], sni)
               for k, (t, sni) in new_idx.items() if k in dep_idx and dep_idx[k][1] != sni]
    added = [(t, mask_host(k[0])) for k, (t, _) in new_idx.items() if k not in dep_idx]
    removed = [(t, mask_host(k[0])) for k, (t, _) in dep_idx.items() if k not in new_idx]
    print("=== SNI pre-flight vs deployed (host masked; SNI shown -- it is the signal) ===")
    for t, h, old, new in changed:
        print(f"  SNI DRIFT [{t} @ {h}]: {old} -> {new}")
    for t, h in added:
        print(f"  pool +added [{t} @ {h}]")
    for t, h in removed:
        print(f"  pool -removed [{t} @ {h}]")
    print(f"  {len(new_idx) - len(changed) - len(added)} unchanged; "
          f"{len(changed)} drifted, {len(added)} added, {len(removed)} removed")
    if (changed or added or removed) and not ack:
        print("SNI/pool DRIFT vs deployed config (see above). Review it, then re-run with "
              "--allow-sni-drift (or ALLOW_SNI_DRIFT=1) to confirm and proceed.", file=sys.stderr)
        sys.exit(3)
    print("  CONFIRMED DRIFT (acked) -> proceeding" if (changed or added or removed)
          else "  no drift vs deployed -> proceeding")

json.dump(config, open(out_path, "w"), indent=2)

# secret-masked review output
print("servers parsed:", len(uris))
for s in summary:
    print("  ", s)
print(f"urltest 'auto' groups {len(tags)} outbounds; interval=30s interrupt_exist_connections=true; route.final=auto; NO direct outbound")
masked = json.loads(json.dumps(config))
for o in masked["outbounds"]:
    if o.get("type") == "vless":
        o["uuid"] = "<uuid>"; o["server"] = "<host>"
        if "tls" in o and "reality" in o["tls"]:
            o["tls"]["reality"]["public_key"] = "<pbk>"; o["tls"]["reality"]["short_id"] = "<sid>"
print("=== MASKED CONFIG ===")
print(json.dumps(masked, indent=1, ensure_ascii=False))
