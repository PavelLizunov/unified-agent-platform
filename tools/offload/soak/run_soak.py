#!/usr/bin/env python3
"""V3 soak-eval master driver. Runs the built tracks (A offload, C retrieval+injection) in a loop until
a wall-clock budget, records timing + a scorecard. Deterministic graders live inside each track.

Usage:  python tools/offload/soak/run_soak.py [--hours 4]
Prereq: local llama.cpp server up. Tracks B (coding, verified on build-1) and D (BFCL) are added at
run-time against the live server; this driver covers the server-independent-to-build core (A+C+E-repeat).
See docs/model-eval/qwen-agentworld/V3_SOAK_GOAL.md.
"""
import subprocess, sys, os, time, argparse, json

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKS = [("A_offload", "track_a.py"), ("C_retrieval_injection", "track_c.py")]


def run_track(script):
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, script)], capture_output=True, text=True)
    return {"rc": r.returncode, "dt": round(time.time() - t0, 1),
            "tail": (r.stdout or "")[-1500:], "err": (r.stderr or "")[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=4.0)
    a = ap.parse_args()
    # health gate via the shared helper
    sys.path.insert(0, HERE)
    import _llm  # noqa
    if not _llm.health():
        print("SERVER DOWN — start serve-llm.ps1 first, then re-run"); return 4
    deadline = time.time() + a.hours * 3600
    log = []
    round_n = 0
    while time.time() < deadline:
        round_n += 1
        remaining = (deadline - time.time()) / 3600.0
        print("\n########## ROUND %d  (%.2f h left) ##########" % (round_n, remaining))
        for name, script in TRACKS:
            print("---- %s ----" % name)
            res = run_track(script)
            print(res["tail"])
            log.append({"round": round_n, "track": name, **{k: res[k] for k in ("rc", "dt")}})
            if time.time() >= deadline:
                break
    out = os.path.join(HERE, "soak_log.json")
    json.dump(log, open(out, "w"), ensure_ascii=False, indent=1)
    hrs = sum(x["dt"] for x in log) / 3600.0
    print("\n===== SOAK DONE: %d rounds, %.2f h of model time, log -> %s =====" % (round_n, hrs, out))
    print("Repeatability (E): each track ran %d times -> compute Wilson CI on the per-track PASS in the report." % round_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
