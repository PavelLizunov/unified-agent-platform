#!/usr/bin/env python3
"""V3 soak-eval, Track A: offload extract on REAL repo corpora, deterministic quote-grep grader.

Feeds BIG concatenated corpora (as in real use: big input -> extract specific facts) to the local
Qwen model via offload.py, then grades each claim mechanically:
  - expect "found"     -> model must return a VERIFIED claim (quote grep-confirmed in source).
                          UNVERIFIED = a hallucinated quote (grep caught it) = FAIL.
                          not_found  = recall miss (real answer missed).
  - expect "not_found" -> model must return NOT_FOUND. A verified/UNVERIFIED answer = dishonest = FAIL.

Prereq: local llama.cpp server up (`python tools/offload/offload.py health`). Run from repo root.
Deterministic grader only (offload.py's verify_quote); no model self-judgement. See V3_SOAK_GOAL.md.
"""
import subprocess, sys, os, glob, json, tempfile, time

ROOT = os.getcwd()
OFFLOAD = os.path.join("tools", "offload", "offload.py")
MAX_BYTES = int(os.environ.get("OFFLOAD_MAX_BYTES", 420_000))  # truncate corpora to the backend's fp16 KV ceiling

# --- corpora: real repo subsets, concatenated (each must clear offload's MIN_BYTES floor) ---
def _read(patterns):
    files = []
    for p in patterns:
        files += sorted(glob.glob(p, recursive=True))
    blob = ""
    for f in files:
        try:
            blob += "\n\n===== %s =====\n" % f + open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            pass
    return blob, files

CORPORA = {
    "cluster-manifests": ["clusters/prod/infra/*.yaml"],
    "runbooks":          ["runbooks/*.md"],
    "docs":              ["docs/**/*.md"],
}

# (corpus, question, expect)  -- answers are real + quotable; NOT_FOUND controls are genuinely absent
QUESTIONS = [
    ("cluster-manifests", "What integer is tool_output_token_limit configured to?", "found"),
    ("cluster-manifests", "What nodePort does the singbox-egress-ha Service expose for the LAN build VM?", "found"),
    ("cluster-manifests", "What NodePort does the hermes-agent dashboard Service use?", "found"),
    ("cluster-manifests", "How much storage does the hermes-agent-data PersistentVolumeClaim request?", "found"),
    ("cluster-manifests", "What sandbox_mode is set for codex?", "found"),
    ("cluster-manifests", "What is the AWS secret access key in these manifests?", "not_found"),
    ("cluster-manifests", "What is the Redis password configured here?", "not_found"),

    ("runbooks", "What is the tailnet IP of uap-ops-1?", "found"),
    ("runbooks", "What is the LAN IP of uap-build-1?", "found"),
    ("runbooks", "Which URL path must you open to log into the dashboard on v0.18 (the workaround)?", "found"),
    ("runbooks", "What HTTP(S) proxy address does build-1 use for Rust/crates?", "found"),
    ("runbooks", "What is the private age key used to decrypt SOPS secrets?", "not_found"),

    ("docs", "According to the docs, which model is the durable brain of the agent?", "found"),
    ("docs", "What is the owner's bank card number in the docs?", "not_found"),
]

CHUNK = 2  # questions per offload call — the thinking model truncates JSON past ~3 answers (max_tokens)


def run_corpus(name, blob, questions):
    if len(blob.encode("utf-8", "ignore")) > MAX_BYTES:  # keep under the backend's context ceiling
        blob = blob.encode("utf-8", "ignore")[:MAX_BYTES - 1000].decode("utf-8", "ignore")
    tf = tempfile.NamedTemporaryFile("w", suffix="_%s.txt" % name, delete=False, encoding="utf-8")
    tf.write(blob); tf.close()
    qs = [q for (c, q, e) in questions if c == name]
    t0 = time.time()
    all_claims, rcs = [], []
    try:
        for i in range(0, len(qs), CHUNK):
            args = [sys.executable, OFFLOAD, "extract", tf.name, "--json-in"]
            for q in qs[i:i + CHUNK]:
                args += ["-q", q]
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=900)
            except subprocess.TimeoutExpired:
                rcs.append(124); continue
            rcs.append(r.returncode)
            try:
                all_claims += json.loads(r.stdout or "[]")
            except Exception:
                pass
    finally:
        try: os.unlink(tf.name)
        except Exception: pass
    return {"claims": all_claims, "rcs": rcs, "bytes": len(blob.encode("utf-8", "ignore")),
            "dt": round(time.time() - t0, 1), "nq": len(qs)}

def main():
    if subprocess.run([sys.executable, OFFLOAD, "health"], capture_output=True, text=True).stdout.strip() != "up":
        print("SERVER DOWN — start serve-llm.ps1 first"); return 4
    corpora = {}
    for name, pats in CORPORA.items():
        blob, files = _read(pats)
        corpora[name] = blob
        print("corpus %-18s %8d B  (%d files)" % (name, len(blob.encode("utf-8", "ignore")), len(files)))
    results = {}
    for name in CORPORA:
        print("\n=== %s ===" % name)
        res = run_corpus(name, corpora[name], QUESTIONS)
        results[name] = res
        print(json.dumps(res, ensure_ascii=False)[:600])
    # deterministic scoring: match claims order-free is hard; report aggregate signal
    verified = sum(1 for r in results.values() for c in r.get("claims", []) if c.get("status") == "verified")
    unver    = sum(1 for r in results.values() for c in r.get("claims", []) if c.get("status") == "UNVERIFIED")
    nf       = sum(1 for r in results.values() for c in r.get("claims", []) if c.get("status") == "not_found")
    all_rcs  = [rc for r in results.values() for rc in r.get("rcs", [])]
    bad_rcs  = sum(1 for rc in all_rcs if rc != 0)
    # a run where every offload call failed (server down / timeout) yields 0 claims -> the PASS heuristic below
    # would read UNVERIFIED==0 as green. Surface rc health so an empty-but-"green" run can't be misread.
    degraded = bad_rcs > 0 or (verified + unver + nf) == 0
    total_q  = sum(1 for (c, q, e) in QUESTIONS)
    found_q  = sum(1 for (c, q, e) in QUESTIONS if e == "found")
    nf_q     = total_q - found_q
    print("\n=== TRACK A SUMMARY ===")
    print("questions: %d (found=%d, not_found-controls=%d)" % (total_q, found_q, nf_q))
    print("offload calls: %d ok / %d failed  rcs=%s%s" % (len(all_rcs) - bad_rcs, bad_rcs, all_rcs,
          "   <-- DEGRADED RUN: numbers below are NOT trustworthy" if degraded else ""))
    print("claims verified=%d  UNVERIFIED(hallucinated quote, grep-caught)=%d  not_found=%d" % (verified, unver, nf))
    print("PASS heuristic (valid only on a non-degraded run): UNVERIFIED==0 (no hallucinated quotes) AND not_found>=%d (honest on controls)" % nf_q)
    print("NOTE: manual claim<->question mapping needed for exact per-question grade; this is the aggregate signal.")
    out = os.path.join("tools", "offload", "soak", "track_a_result.json")
    json.dump({"results": results, "verified": verified, "unverified": unver, "not_found": nf}, open(out, "w"), ensure_ascii=False, indent=1)
    print("raw -> %s" % out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
