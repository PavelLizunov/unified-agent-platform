#!/usr/bin/env python3
"""Minimal local-model router — ONE OpenAI-compatible endpoint in front of two backends on two boxes:

    qwen-35b  -> Qwen-AgentWorld-35B (llama.cpp, desktop RTX 5060 Ti)   general / reasoning / FC / retrieval
    ornith-9b -> Ornith-1.0-9B      (mlx_lm.server, Mac mini M4)        coding

Routes by the request's "model" field, rewrites it to each backend's expected id (mlx_lm.server needs the
EXACT repo id; llama.cpp ignores it), and streams the response back verbatim so native tool_calls (FC) pass
through untouched. stdlib only — runs on the 2 GB ops-1 VM. See runbooks/local-models-router.md.
"""
import json, os, sys, http.client, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# backend url + the model id to force on that backend (None = pass the caller's value through)
BACKENDS = {
    "qwen":   (os.environ.get("QWEN_URL",   "http://100.114.172.40:8080"), None),
    "ornith": (os.environ.get("ORNITH_URL", "http://100.116.97.112:8080"), "mlx-community/Ornith-1.0-9B-4bit"),
}
KEY = os.environ.get("ROUTER_KEY", "")  # if set, require "Authorization: Bearer <KEY>"
MODELS = [{"id": "qwen-35b", "object": "model", "owned_by": "local-desktop"},
          {"id": "ornith-9b", "object": "model", "owned_by": "local-mac"}]


def pick(model):
    """Route by name. 'ornith'->mac; everything else->qwen (the general/default model)."""
    return "ornith" if "ornith" in (model or "").lower() else "qwen"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # close-delimited: lets us stream SSE without manual chunked framing

    def _auth_ok(self):
        return (not KEY) or self.headers.get("Authorization", "") == "Bearer " + KEY

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps({"object": "list", "data": MODELS}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._auth_ok():
            self.send_error(401, "bad router key"); return
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        url = BACKENDS["qwen"][0]
        try:
            payload = json.loads(raw)
            target = pick(payload.get("model"))
            url, forced = BACKENDS[target]
            if forced:
                payload["model"] = forced          # mlx_lm.server needs its exact repo id
            raw = json.dumps(payload).encode()
        except Exception:
            pass  # not JSON -> forward as-is to the default backend
        try:
            conn = http.client.HTTPConnection(urllib.parse.urlparse(url).netloc, timeout=1200)
            conn.request("POST", self.path, body=raw,
                         headers={"Content-Type": "application/json", "Content-Length": str(len(raw))})
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length", "keep-alive"):
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                self.wfile.write(chunk); self.wfile.flush()   # stream tokens as they arrive
            conn.close()
        except Exception as e:
            try: self.send_error(502, "backend error: %s" % e)
            except Exception: pass

    def log_message(self, *a):
        return  # quiet


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        assert pick("ornith-9b") == "ornith"
        assert pick("Ornith-1.0-9B-4bit") == "ornith"
        assert pick("qwen-35b") == "qwen"
        assert pick("") == "qwen" and pick(None) == "qwen"   # default = general model
        print("selfcheck ok"); sys.exit(0)
    port = int(os.environ.get("ROUTER_PORT", "8090"))
    print("local-model router on :%d  ->  qwen=%s  ornith=%s" %
          (port, BACKENDS["qwen"][0], BACKENDS["ornith"][0]))
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
