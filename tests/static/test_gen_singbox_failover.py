#!/usr/bin/env python3
"""Regression guard for the SNI pre-flight gate in infra/sops/gen-singbox-failover.py.

Runs the REAL generator as a subprocess (no import, no third-party deps). A fresh
subscription whose server SNI differs from the deployed config MUST fail closed
(exit 3), MUST pass once acked, and a no-drift case MUST pass. This locks the
2026-07-09 lesson: a silent REALITY-target drift can never reach deploy again
without being surfaced and confirmed.

CI runs this via the `tests/static/test_*.py` loop in .github/workflows/ci.yml.
Standalone: python tests/static/test_gen_singbox_failover.py
"""
import base64, json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN = os.path.join(REPO, "infra", "sops", "gen-singbox-failover.py")


def sub_with_sni(sni):
    """A minimal ninitux-shaped subscription ({"config": base64(vless list)}) with one reality node."""
    uri = ("vless://11111111-1111-1111-1111-111111111111@203.0.113.7:443"
           f"?security=reality&sni={sni}&pbk=PUBKEY&sid=ab&fp=chrome"
           "&flow=xtls-rprx-vision#Test%20DE")
    return {"config": base64.b64encode(uri.encode()).decode()}


def deployed_with_sni(sni):
    return {"outbounds": [{"type": "vless", "tag": "Test DE", "server": "203.0.113.7",
                           "server_port": 443, "tls": {"server_name": sni}}]}


def run(sub, deployed, *flags, env=None):
    with tempfile.TemporaryDirectory() as d:
        sp, dp, op = (os.path.join(d, f) for f in ("sub.json", "dep.json", "out.json"))
        json.dump(sub, open(sp, "w"))
        json.dump(deployed, open(dp, "w"))
        return subprocess.run([sys.executable, GEN, sp, op, "--against", dp, *flags],
                              capture_output=True, text=True,
                              env={**os.environ, **(env or {})})


fresh = sub_with_sni("yahoo.com")  # the server now expects yahoo.com...

# 1. deployed still on the OLD sni -> drift MUST fail closed (exit 3)
r = run(fresh, deployed_with_sni("microsoft.com"))
assert r.returncode == 3, f"drift must exit 3, got {r.returncode}\nOUT:{r.stdout}\nERR:{r.stderr}"
assert "SNI DRIFT" in r.stdout, f"expected per-server drift line:\n{r.stdout}"
assert "microsoft.com -> yahoo.com" in r.stdout, f"expected old->new report:\n{r.stdout}"

# 2. same drift, acked by flag -> MUST pass and say so
r = run(fresh, deployed_with_sni("microsoft.com"), "--allow-sni-drift")
assert r.returncode == 0, f"acked drift must pass, got {r.returncode}\nERR:{r.stderr}"
assert "CONFIRMED DRIFT" in r.stdout

# 3. acked by env -> MUST pass
r = run(fresh, deployed_with_sni("microsoft.com"), env={"ALLOW_SNI_DRIFT": "1"})
assert r.returncode == 0, f"env ack must pass, got {r.returncode}\nERR:{r.stderr}"

# 4. deployed already on the new sni -> no drift, MUST pass without an ack
r = run(fresh, deployed_with_sni("yahoo.com"))
assert r.returncode == 0, f"no-drift must pass, got {r.returncode}\nERR:{r.stderr}"
assert "no drift vs deployed" in r.stdout

print("test_gen_singbox_failover: OK (drift->exit3, flag-ack->pass, env-ack->pass, no-drift->pass)")
