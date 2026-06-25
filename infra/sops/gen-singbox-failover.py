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
Prints a SECRET-MASKED summary to stdout for review.
"""
import json, base64, sys, re, urllib.parse as up

sub_path, out_path = sys.argv[1], sys.argv[2]
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
