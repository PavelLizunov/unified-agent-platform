#!/usr/bin/env python3
"""Hermes ReAct POC — prompt-based function-calling against the live LiteLLM stack.

Proves the design from ../README.md: the model emits a fenced ```tool_call``` block, this loop
executes the tool out-of-band and feeds back a ```tool_result```, repeating until a final answer.
Zero subfleet changes; rides on plain chat.completions. stdlib only.

Env: LITELLM_BASE (e.g. https://uap-home-1.tail9fd337.ts.net/v1), LITELLM_KEY, MODEL (default smart-cloud).
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

BASE = os.environ["LITELLM_BASE"].rstrip("/")
KEY = os.environ["LITELLM_KEY"]
MODEL = os.environ.get("MODEL", "smart-cloud")

SYSTEM = (
    "You are an agent that can call tools. To call a tool, output ONLY this and nothing else:\n"
    '```tool_call\n{"name":"<tool>","arguments":{...}}\n```\n'
    "Available tools:\n"
    '- calc(expression: string): evaluate an arithmetic expression, e.g. "48271*99173".\n'
    "- kube_pods(namespace: string): list pods and their status in a Kubernetes namespace. "
    "You CANNOT know live cluster state without calling this.\n"
    "Use a tool whenever the answer depends on live data or non-trivial arithmetic, instead of guessing. "
    "When you have the final answer, reply normally in prose WITHOUT a tool_call block."
)


def calc(args):
    expr = str(args.get("expression", ""))
    if not re.fullmatch(r"[0-9+\-*/(). ]+", expr):
        return "error: expression has invalid characters"
    try:
        return str(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 (charset-restricted; POC only)
    except Exception as e:  # noqa: BLE001
        return "error: " + str(e)


def kube_pods(args):
    ns = str(args.get("namespace", "default"))
    if not re.fullmatch(r"[a-z0-9-]+", ns):
        return "error: invalid namespace"
    try:
        r = subprocess.run(
            ["kubectl", "-n", ns, "get", "pods", "--no-headers",
             "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase,READY:.status.containerStatuses[*].ready"],
            capture_output=True, text=True, timeout=15,
        )
        return (r.stdout.strip() or "(no pods)") if r.returncode == 0 else "error: " + r.stderr.strip()
    except Exception as e:  # noqa: BLE001
        return "error: " + str(e)


TOOLS = {"calc": calc, "kube_pods": kube_pods}


def llm(messages):
    body = json.dumps({"model": MODEL, "messages": messages}).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def extract_tool_call(text):
    m = re.search(r"```tool_call\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def react(user, max_steps=6):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    for step in range(1, max_steps + 1):
        out = llm(messages)
        tc = extract_tool_call(out)
        if not tc:
            print("\n[final answer]\n" + out.strip())
            return out
        name = tc.get("name")
        args = tc.get("arguments", {})
        result = TOOLS[name](args) if name in TOOLS else "error: unknown tool " + str(name)
        print("[step %d] tool_call %s(%s)" % (step, name, json.dumps(args)))
        print("          -> " + result.replace("\n", "\n             "))
        messages.append({"role": "assistant", "content": out})
        messages.append(
            {"role": "user", "content": '```tool_result\n%s\n```' % json.dumps({"name": name, "result": result})}
        )
    print("\n[stopped: max steps reached]")
    return None


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else (
        "How many pods are running in the uap-system namespace, and what are their names? "
        "Also: what is 48271 * 99173?"
    )
    print("[user] " + q + "\n")
    react(q)
