#!/usr/bin/env python3
"""Hermes reliability harness — representative measurement of how faithfully the MODEL reads/uses what
Hermes feeds it. Runs each scenario TRIALS times (default 20) against the live model via run_agent
(ReWOO by default), with ONE retry on transient errors so a 429/network hiccup doesn't count as a model
failure. Covers every tool type and single/multi-tool/recall/net. Reports per-scenario pass rate.

  export LITELLM_BASE=https://uap-home-1.tail9fd337.ts.net/v1
  export LITELLM_KEY=<litellm master key>
  export HERMES_DEVMODE=1                 # kube_* ground truth via kubectl on ops-1
  export TRIALS=20                        # trials per scenario
  export HERMES_TEST_MODEL=smart-cloud    # model under test (optional)
  export HERMES_AGENT_MODE=rewoo          # rewoo (default) | react
  python3 tests/reliability.py
"""
import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hermes  # noqa: E402

N = int(os.environ.get("TRIALS", "20"))
WORKERS = int(os.environ.get("RELIABILITY_WORKERS", "5"))
_MODEL = os.environ.get("HERMES_TEST_MODEL") or None


def _nums(text):
    return re.sub(r"[^0-9]", " ", (text or "").replace(",", "")).split()


def _seg(name):
    return name.split("-")[0]


def _lines(s):
    return [ln for ln in (s or "").splitlines() if ln.strip() and not ln.lower().startswith("error")]


# ---- ground truth (computed locally via the tools; DEVMODE kubectl fallback on ops-1) ----
_pods = _lines(hermes.tool_kube_pods({"namespace": "uap-system"}))
POD_COUNT = len(_pods)
POD_NAMES = [ln.split()[0] for ln in _pods]
_deps = _lines(hermes.tool_kube_get({"kind": "deployments", "namespace": "uap-system"}))
DEP_COUNT = len(_deps)
_nodes = _lines(hermes.tool_kube_get({"kind": "nodes"}))
NODE_NAMES = [ln.split()[0] for ln in _nodes]
PROD = 89234 * 77123
PROD2 = 1234 * 5678

SCENARIOS = [
    ("count_pods", "How many pods are running in the uap-system namespace? Reply with ONLY the integer.",
     lambda f, t: str(POD_COUNT) in _nums(f) and len(f) < 150),
    ("list_pods", "List the names of all pods in the uap-system namespace.",
     lambda f, t: sum(1 for n in POD_NAMES if _seg(n) in f) >= max(1, POD_COUNT - 1)),
    ("count_deployments", "How many deployments are in the uap-system namespace? Reply with ONLY the integer.",
     lambda f, t: str(DEP_COUNT) in _nums(f) and len(f) < 150),
    ("node_names", "What are the names of the Kubernetes cluster nodes?",
     lambda f, t: bool(NODE_NAMES) and all(n in f for n in NODE_NAMES)),
    ("multi_time_count", "Tell me the current UTC time AND how many pods run in uap-system. One line.",
     lambda f, t: bool(re.search(r"\d{2}:\d{2}", f)) and str(POD_COUNT) in _nums(f)),
    ("multi_three_facts",
     "In one line give: the current UTC time, the number of pods in uap-system, and the value of 1234*5678.",
     lambda f, t: bool(re.search(r"\d{2}:\d{2}", f)) and str(POD_COUNT) in _nums(f) and str(PROD2) in _nums(f)),
    ("arithmetic", "Compute 89234 * 77123 exactly and give the resulting number.",
     lambda f, t: str(PROD) in _nums(f)),
    ("recall_no_tool", "What is the capital of France? Reply with one word.",
     lambda f, t: "paris" in f.lower() and not t),
    ("http_fetch", "Fetch http://example.com and tell me the exact title of the page.",
     lambda f, t: "example domain" in f.lower()),
]


def _trial(prompt):
    err = None
    for _attempt in range(2):  # one retry on transient (429/network) so it doesn't count as a model failure
        try:
            f, t = hermes.run_agent(prompt, model=_MODEL)
            return f, t, None
        except Exception as e:  # noqa: BLE001
            err = str(e)
    return "", [], err


def main():
    if not os.environ.get("LITELLM_BASE") or not os.environ.get("LITELLM_KEY"):
        print("set LITELLM_BASE and LITELLM_KEY"); sys.exit(2)
    print("ground truth: pods=%d deployments=%d nodes=%s | mode=%s model=%s trials=%d\n"
          % (POD_COUNT, DEP_COUNT, NODE_NAMES, os.environ.get("HERMES_AGENT_MODE", "rewoo"),
             _MODEL or hermes.DEFAULT_MODEL, N))
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
            agg[label].append((ok, (err or f).replace("\n", " ")[:70]))
    total = passed = 0
    for label, _, _ in SCENARIOS:
        rows = agg[label]
        p = sum(1 for ok, _ in rows if ok)
        passed += p
        total += len(rows)
        bar = "#" * round(10 * p / len(rows))
        print("[%2d/%2d] %-18s %s" % (p, len(rows), label, bar))
        for ok, sample in [r for r in rows if not r[0]][:2]:  # up to 2 failure samples
            print("        FAIL: %s" % sample)
    print("\nOVERALL: %d/%d (%.0f%%)  [model=%s mode=%s]"
          % (passed, total, 100.0 * passed / total, _MODEL or hermes.DEFAULT_MODEL,
             os.environ.get("HERMES_AGENT_MODE", "rewoo")))
    sys.exit(0 if passed >= 0.9 * total else 1)


if __name__ == "__main__":
    main()
