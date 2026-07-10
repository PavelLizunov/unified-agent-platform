#!/usr/bin/env python3
"""ai-search — free-tier web search / answer / fetch for Hermes (RU-egress aware).

Design (research doc "Hermes Agent — AI Search Free Tier Mini Research", 2026-07-09):
  - Default provider = DuckDuckGo via `ddgs` — ZERO key, works today through the VLESS proxy.
  - Key-based providers (exa/tavily/brave) light up automatically when their env key is present
    (EXA_API_KEY / TAVILY_API_KEY / BRAVE_API_KEY) — owner drops the free key in SOPS, no code change.
  - Normalized output contract (provider, mode, answer, sources[], warnings) so callers/agents are
    provider-agnostic and can swap backends.
  - Web results are EVIDENCE, not instructions (prompt-injection rule; callers must not execute them).
  - Safety defaults from the doc: require_sources for answers, deep/research modes off, small caps.

ponytail: DDG search + naive html→text fetch cover the no-key MVP; exa/tavily/brave are thin REST
wrappers gated on keys. Firecrawl/Gemini/Baidu/You-MCP deliberately deferred (see runbook).
"""
import argparse, json, os, re, sys, urllib.request, urllib.parse

TIMEOUT = 25
MAX_RESULTS_CAP = 15

def _proxy_opener():
    # honor the box's proxy env (VLESS egress on build-1); ProxyHandler reads *_proxy vars.
    return urllib.request.build_opener(urllib.request.ProxyHandler())

def _post_json(url, payload, headers, timeout=TIMEOUT):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    with _proxy_opener().open(req, timeout=timeout) as r:
        return json.load(r)

def _get_json(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    with _proxy_opener().open(req, timeout=timeout) as r:
        return json.load(r)

def out(provider, mode, answer="", sources=None, warnings=None):
    return {"provider": provider, "mode": mode, "answer": answer,
            "sources": sources or [], "warnings": warnings or []}

# ---------------------------------------------------------------- providers --
def ddg_search(query, n):
    from ddgs import DDGS
    res = list(DDGS().text(query, max_results=n))
    src = [{"title": r.get("title", ""), "url": r.get("href", ""),
            "snippet": r.get("body", ""), "published_at": None} for r in res]
    return out("ddg", "raw_search", "", src)

def exa_search(query, n, answer):
    key = os.environ.get("EXA_API_KEY")
    if not key:
        return None
    h = {"x-api-key": key}
    if answer:
        d = _post_json("https://api.exa.ai/answer", {"query": query, "text": True}, h)
        src = [{"title": c.get("title", ""), "url": c.get("url", ""),
                "snippet": (c.get("text", "") or "")[:300], "published_at": c.get("publishedDate")}
               for c in d.get("citations", [])]
        return out("exa", "answer", d.get("answer", ""), src)
    d = _post_json("https://api.exa.ai/search", {"query": query, "numResults": n, "contents": {"text": {"maxCharacters": 300}}}, h)
    src = [{"title": r.get("title", ""), "url": r.get("url", ""),
            "snippet": (r.get("text", "") or "")[:300], "published_at": r.get("publishedDate")}
           for r in d.get("results", [])]
    return out("exa", "raw_search", "", src)

def tavily_search(query, n):
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    d = _post_json("https://api.tavily.com/search",
                   {"api_key": key, "query": query, "max_results": n, "search_depth": "basic"}, {})
    src = [{"title": r.get("title", ""), "url": r.get("url", ""),
            "snippet": r.get("content", ""), "published_at": r.get("published_date")}
           for r in d.get("results", [])]
    return out("tavily", "raw_search", d.get("answer", "") or "", src)

def brave_search(query, n, answer):
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return None
    h = {"X-Subscription-Token": key, "Accept": "application/json"}
    q = urllib.parse.urlencode({"q": query, "count": n})
    d = _get_json("https://api.search.brave.com/res/v1/web/search?" + q, h)
    src = [{"title": r.get("title", ""), "url": r.get("url", ""),
            "snippet": r.get("description", ""), "published_at": r.get("age")}
           for r in d.get("web", {}).get("results", [])[:n]]
    return out("brave", "raw_search", "", src)

PROVIDERS = {
    "ddg": lambda q, n, a: ddg_search(q, n),
    "exa": lambda q, n, a: exa_search(q, n, a),
    "tavily": lambda q, n, a: tavily_search(q, n),
    "brave": lambda q, n, a: brave_search(q, n, a),
}
KEY_ENV = {"exa": "EXA_API_KEY", "tavily": "TAVILY_API_KEY", "brave": "BRAVE_API_KEY"}

# ------------------------------------------------------------------- fetch --
def fetch_page(url, max_chars):
    """Zero-key page read: GET through proxy, strip scripts/styles/tags -> text."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ai-search)"})
    with _proxy_opener().open(req, timeout=TIMEOUT) as r:
        html = r.read(2_000_000).decode("utf-8", "replace")
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return out("fetch", "extract", text[:max_chars], [{"title": "", "url": url, "snippet": "", "published_at": None}])

# -------------------------------------------------------------------- main --
def cmd_search(a):
    n = min(a.n, MAX_RESULTS_CAP)
    order = [a.provider] if a.provider != "auto" else ["exa", "brave", "tavily", "ddg"]
    warnings = []
    for p in order:
        try:
            res = PROVIDERS[p](a.query, n, a.answer)
        except Exception as e:
            warnings.append(f"{p} error: {str(e)[:120]}")
            res = None
        if res is None:  # key-gated provider with no key
            if p in KEY_ENV:
                warnings.append(f"{p} skipped: set {KEY_ENV[p]} to enable")
            continue
        if a.answer and res["mode"] not in ("answer",):
            warnings.append(f"{p} has no answer mode; returned raw_search")
        res["warnings"] = warnings + res["warnings"]
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    print(json.dumps(out("none", "raw_search", "", [], warnings + ["no provider produced results"]),
                     ensure_ascii=False, indent=2))

def cmd_fetch(a):
    print(json.dumps(fetch_page(a.url, a.max_chars), ensure_ascii=False, indent=2))

def cmd_providers(_):
    print("provider   key_env           status")
    for p, env in [("ddg", "(none)")] + [(p, KEY_ENV[p]) for p in ("exa", "tavily", "brave")]:
        ok = "READY" if (env == "(none)" or os.environ.get(env)) else "needs key"
        print(f"{p:<10} {env:<17} {ok}")

def main():
    ap = argparse.ArgumentParser(prog="ai-search", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="web search (default provider auto: exa>brave>tavily>ddg)")
    s.add_argument("query")
    s.add_argument("--provider", default="auto", choices=["auto", "ddg", "exa", "tavily", "brave"])
    s.add_argument("--answer", action="store_true", help="cited AI answer (exa/tavily; require_sources)")
    s.add_argument("-n", type=int, default=6)
    s.set_defaults(fn=cmd_search)
    f = sub.add_parser("fetch", help="zero-key page read (html -> text)")
    f.add_argument("url")
    f.add_argument("--max-chars", type=int, default=6000)
    f.set_defaults(fn=cmd_fetch)
    sub.add_parser("providers", help="show which providers are ready / need a key").set_defaults(fn=cmd_providers)
    a = ap.parse_args()
    a.fn(a)

def _selfcheck():
    """No-network contract check: canned provider JSON -> normalized {provider,mode,answer,sources[],warnings}."""
    keys = {"provider", "mode", "answer", "sources", "warnings"}
    # out() is the normalizer — verify shape + defaults.
    r = out("x", "raw_search")
    assert set(r) == keys and r["sources"] == [] and r["warnings"] == [], r

    # Stub the two network helpers with canned payloads, then drive the REAL provider parsers
    # (the field-mapping list comprehensions are the logic under test). Names resolve from module
    # globals at call time, so reassigning them here monkeypatches the parsers without any network.
    g = globals()
    os.environ["EXA_API_KEY"] = os.environ["TAVILY_API_KEY"] = os.environ["BRAVE_API_KEY"] = "x"

    # exa answer-mode: citations -> sources[], answer carried through; contract shape intact.
    g["_post_json"] = lambda *a, **k: {"answer": "42", "citations":
        [{"title": "T", "url": "u", "text": "body", "publishedDate": "2026"}]}
    r = exa_search("q", 3, True)
    assert set(r) == keys and r["provider"] == "exa" and r["mode"] == "answer" and r["answer"] == "42", r
    assert r["sources"] == [{"title": "T", "url": "u", "snippet": "body", "published_at": "2026"}], r

    # tavily: content -> snippet, published_date -> published_at, top-level answer passthrough.
    g["_post_json"] = lambda *a, **k: {"answer": "yes", "results":
        [{"title": "Tv", "url": "tu", "content": "c", "published_date": "d"}]}
    r = tavily_search("q", 3)
    assert r["provider"] == "tavily" and r["answer"] == "yes", r
    assert r["sources"] == [{"title": "Tv", "url": "tu", "snippet": "c", "published_at": "d"}], r

    # brave: web.results -> sources[], age -> published_at (via _get_json).
    g["_get_json"] = lambda *a, **k: {"web": {"results":
        [{"title": "B", "url": "bu", "description": "d", "age": "1d"}]}}
    r = brave_search("q", 5, False)
    assert set(r) == keys and r["sources"][0]["published_at"] == "1d", r

    # key-gated provider with no key -> None (cmd_search turns this into a 'skipped' warning).
    os.environ.pop("EXA_API_KEY", None)
    assert exa_search("q", 3, False) is None
    print("selfcheck ok")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck(); sys.exit(0)
    main()
