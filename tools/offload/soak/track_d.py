#!/usr/bin/env python3
"""V3 soak-eval, Track D: self-contained function-calling eval (BFCL-style, no external dataset).

Presents tool schemas + a request; the model must emit a JSON tool call {name, arguments}. Grader =
deterministic exact-match of name + arguments (dict compare, no LLM judgement). Covers single-call,
parallel, distractor-tools, and no-call-needed. Complements V2's real BFCL numbers. See V3_SOAK_GOAL.md.
"""
import sys, os, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _llm  # noqa: E402

TOOLS = [
    {"name": "get_weather", "params": {"city": "string", "unit": "celsius|fahrenheit"}},
    {"name": "send_email", "params": {"to": "string", "subject": "string", "body": "string"}},
    {"name": "add_numbers", "params": {"a": "number", "b": "number"}},
    {"name": "search_web", "params": {"query": "string"}},
]

# (request, expected calls list). expected = [] means NO tool call should be emitted.
CASES = [
    ("What's the weather in Paris in celsius?", [{"name": "get_weather", "arguments": {"city": "Paris", "unit": "celsius"}}]),
    ("Add 17 and 25.", [{"name": "add_numbers", "arguments": {"a": 17, "b": 25}}]),
    ("Search the web for the capital of Japan.", [{"name": "search_web", "arguments": {"query": "capital of Japan"}}]),
    ("Get the weather in Tokyo (fahrenheit) AND add 3 and 4.",
     [{"name": "get_weather", "arguments": {"city": "Tokyo", "unit": "fahrenheit"}},
      {"name": "add_numbers", "arguments": {"a": 3, "b": 4}}]),
    ("Thanks, that's all I needed!", []),  # no-call: must not hallucinate a tool
]

SYS = ("You are a function-calling agent. Available tools (JSON): %s\n"
       "For the user's request, output ONLY a JSON array of the tool calls to make, each "
       '{"name": <tool>, "arguments": {<params>}}. If NO tool is needed, output []. No prose.'
       % json.dumps(TOOLS))


def parse_calls(text):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else None
    except Exception:
        return None


def norm(call):
    return (call.get("name"), json.dumps(call.get("arguments", {}), sort_keys=True))


def grade(expected, got):
    if got is None:
        return False
    exp = sorted(norm(c) for c in expected)
    gt = sorted(norm(c) for c in got)
    return exp == gt


def main():
    if not _llm.health():
        print("SERVER DOWN — start serve-llm.ps1 first"); return 4
    results = []
    for req, expected in CASES:
        t0 = time.time()
        resp = _llm.chat([{"role": "system", "content": SYS}, {"role": "user", "content": req}], max_tokens=500)
        got = parse_calls(resp)
        ok = grade(expected, got)
        results.append(ok)
        kind = "no-call" if not expected else ("parallel" if len(expected) > 1 else "single")
        print("  [%-8s] pass=%s (%.0fs)  got=%s" % (kind, ok, time.time() - t0, json.dumps(got)[:90] if got is not None else "UNPARSEABLE"))
    p = sum(1 for r in results if r)
    print("\n=== TRACK D SUMMARY ===")
    print("function-calling: %d/%d exact-match (name+args). V2 BFCL single-call ~90%%, parallel ~75%%." % (p, len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
