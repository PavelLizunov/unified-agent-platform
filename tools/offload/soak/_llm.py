#!/usr/bin/env python3
"""Shared local-model chat helper for the V3 soak-eval tracks. stdlib only.
Endpoint = OFFLOAD_URL (default http://127.0.0.1:8080/v1). Server is desktop-only."""
import json, os, urllib.request

URL = os.environ.get("OFFLOAD_URL", "http://127.0.0.1:8080/v1").rstrip("/")


def health():
    try:
        urllib.request.urlopen(URL + "/models", timeout=5).read()
        return True
    except Exception:
        try:
            urllib.request.urlopen(URL.replace("/v1", "") + "/health", timeout=5).read()
            return True
        except Exception:
            return False


def chat(messages, temperature=0.0, max_tokens=2000, timeout=600):
    body = {"model": "local", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(URL + "/chat/completions", data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    m = d["choices"][0]["message"]
    # thinking model: answer is usually in content; fall back to reasoning_content
    return (m.get("content") or "").strip() or (m.get("reasoning_content") or "").strip()
