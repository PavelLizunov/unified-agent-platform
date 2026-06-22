#!/usr/bin/env python3
"""Hermes reliability harness — how reliably does the MODEL read/use what Hermes feeds it?

Runs each scenario TRIALS times against the LIVE model (via run_react, the real system prompt +
tool format + tool results) and reports pass rates. This measures the model-facing side: does Claude
call the right tool, faithfully read the tool result, and answer correctly — i.e. "can it read what
Hermes sends it". Network required.

  export LITELLM_BASE=https://uap-home-1.tail9fd337.ts.net/v1
  export LITELLM_KEY=<litellm master key>
  export HERMES_DEVMODE=1            # kube_pods ground-truth via kubectl on ops-1
  export TRIALS=5
  python3 tests/reliability.py
"""
import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hermes  # noqa: E402

N = int(os.environ.get("TRIALS", "5"))
WORKERS = int(os.environ.get("RELIABILITY_WORKERS", "5"))


def _nums(text):
    """integer tokens in text, commas stripped (so '4,787' -> 4787)."""
    return re.sub(r"[^0-9]", " ", (text or "").replace(",", "")).split()


# ---- ground truth (computed locally, deterministically) ----
_pods = [l for l in hermes.tool_kube_pods({"namespace": "uap-system"}).splitlines() if l.strip()]
POD_COUNT = len(_pods)
POD_NAMES = [l.split()[0] for l in _pods]
PRODUCT = 89234 * 77123

SCENARIOS = [
    ("tool_call_correct_count",
     "How many pods are running in the uap-system namespace? Reply with ONLY the integer.",
     lambda f, t: str(POD_COUNT) in _nums(f) and len(f) < 60),  # a short clean count, not a raw pod dump
    ("result_faithful_names",
     "List the names of all pods in the uap-system namespace.",
     lambda f, t: sum(1 for n in POD_NAMES if n.split("-")[0] in f) >= max(1, POD_COUNT - 1)),
    ("multi_tool_time_and_count",
     "Tell me the current UTC time AND how many pods run in uap-system. One line.",
     lambda f, t: bool(re.search(r"\d{2}:\d{2}", f)) and str(POD_COUNT) in _nums(f)),
    ("no_overcall_recall",
     "What is the capital of France? Reply with one word.",
     lambda f, t: "paris" in f.lower() and not t),
    ("arithmetic_correct",
     "Compute 89234 * 77123 exactly and give the resulting number.",
     lambda f, t: str(PRODUCT) in _nums(f)),
]


def _trial(prompt):
    try:
        f, t = hermes.run_react(prompt)
        return f, t, None
    except Exception as e:  # noqa: BLE001
        return "", [], str(e)


def main():
    if not os.environ.get("LITELLM_BASE") or not os.environ.get("LITELLM_KEY"):
        print("set LITELLM_BASE and LITELLM_KEY"); sys.exit(2)
    print("ground truth: pod_count=%d, names[:3]=%s, product=%d, trials=%d\n"
          % (POD_COUNT, POD_NAMES[:3], PRODUCT, N))
    agg = {label: [] for label, _, _ in SCENARIOS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for label, prompt, pred in SCENARIOS:
            for _ in range(N):
                futs[ex.submit(_trial, prompt)] = (label, pred)
        for fut in concurrent.futures.as_completed(futs):
            label, pred = futs[fut]
            f, t, err = fut.result()
            ok = False if err else bool(pred(f, t))
            agg[label].append((ok, len(t), (err or f).replace("\n", " ")[:75]))
    total = passed = 0
    for label, _, _ in SCENARIOS:
        rows = agg[label]
        p = sum(1 for ok, _, _ in rows if ok)
        passed += p
        total += len(rows)
        print("[%d/%d] %s" % (p, len(rows), label))
        for ok, ntools, sample in rows:
            print("    %s tools=%d  %s" % ("PASS" if ok else "FAIL", ntools, sample))
    print("\nOVERALL model-comprehension reliability: %d/%d (%.0f%%)" % (passed, total, 100.0 * passed / total))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
