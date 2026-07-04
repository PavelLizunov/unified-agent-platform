#!/usr/bin/env python3
"""V3 soak-eval, Track B: local model writes Rust code; grader = MY hidden assertions via `cargo test`
on build-1 (deterministic, mutation-proof — the model never sees my test, so it cannot game it).

Prereq: local server up + reachable build-1 (via ops-1). Run from repo root. See V3_SOAK_GOAL.md.
"""
import sys, os, subprocess, base64, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _llm  # noqa: E402

OPS = os.environ.get("OPS_SSH", "uap@192.168.0.203")
B1 = os.environ.get("BUILD1_SSH", "uap@192.168.0.99")

# (name, signature, behavior spec, MY independent test body — hidden from the model)
SPECS = [
    ("add", "pub fn add(a: i64, b: i64) -> i64", "returns a + b",
     'assert_eq!(add(2,3),5); assert_eq!(add(-4,4),0); assert_eq!(add(0,0),0);'),
    ("is_prime", "pub fn is_prime(n: u64) -> bool", "returns true iff n is prime (treat n<2 as not prime)",
     'assert!(is_prime(2)); assert!(is_prime(13)); assert!(!is_prime(1)); assert!(!is_prime(9)); assert!(!is_prime(0));'),
    ("reverse", "pub fn reverse(s: &str) -> String", "returns the input string reversed",
     r'assert_eq!(reverse("abc"), "cba"); assert_eq!(reverse(""), ""); assert_eq!(reverse("ab"), "ba");'),
    ("gcd", "pub fn gcd(a: u64, b: u64) -> u64", "returns the greatest common divisor",
     'assert_eq!(gcd(12,8),4); assert_eq!(gcd(17,5),1); assert_eq!(gcd(0,7),7);'),
]


def build1(cmd, timeout=200):
    b = base64.b64encode(cmd.encode()).decode()
    full = ("ssh -o ConnectTimeout=20 %s \"ssh -o ConnectTimeout=15 %s 'echo %s | base64 -d | bash'\""
            % (OPS, B1, b))
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def extract_rust(text):
    blocks = re.findall(r"```(?:rust)?\s*(.*?)```", text, re.S)
    return "\n\n".join(blocks).strip() if blocks else text.strip()


def run_spec(name, sig, behavior, my_assert):
    t0 = time.time()
    resp = _llm.chat([
        {"role": "system", "content": "You are a Rust expert. Output ONLY one ```rust code block with the requested function (public). No prose, no tests, no main."},
        {"role": "user", "content": "Write `%s`. Behavior: %s." % (sig, behavior)},
    ], max_tokens=1000)
    code = extract_rust(resp)
    crate = "sbtest_%s" % name
    script = "\n".join([
        "set -e",
        "rm -rf ~/%s && cargo new %s --lib -q" % (crate, crate),
        "cat > ~/%s/src/lib.rs <<'RUSTEOF'" % crate,
        code,
        "",
        "#[cfg(test)] mod indep_grader { use super::*; #[test] fn hidden() { %s } }" % my_assert,
        "RUSTEOF",
        "cd ~/%s && cargo test -q 2>&1 | grep -E 'test result|error\\[|cannot find' | head -4" % crate,
    ])
    rc, out, err = build1(script)
    build1("rm -rf ~/%s" % crate, timeout=30)
    ok = ("test result: ok" in out) and ("0 failed" in out or "; 0 failed" in out)
    # a compile error or a failed hidden assertion both => FAIL (deterministic)
    return {"spec": name, "pass": ok, "dt": round(time.time() - t0, 1), "signal": (out or err)[:180].replace("\n", " ")}


def main():
    if not _llm.health():
        print("SERVER DOWN — start serve-llm.ps1 first"); return 4
    # smoke: can we reach build-1 cargo at all?
    rc, out, _ = build1("cargo --version 2>&1 | head -1")
    if "cargo" not in out:
        print("BUILD-1 cargo unreachable via %s->%s: %s" % (OPS, B1, out[:120])); return 4
    results = []
    for name, sig, beh, ta in SPECS:
        r = run_spec(name, sig, beh, ta)
        results.append(r); print("  %-9s pass=%s (%.0fs)  %s" % (name, r["pass"], r["dt"], r["signal"]))
    p = sum(1 for r in results if r["pass"])
    print("\n=== TRACK B SUMMARY ===")
    print("coding: %d/%d specs pass MY hidden cargo assertions (mutation-proof)" % (p, len(results)))
    print("PASS heuristic: >= %d/%d (V2 new-code baseline ~96%%)" % (len(results) - 1, len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
