#!/usr/bin/env python3
"""Bounded GigaAM CTC worker for the always-on Mac mini."""

from __future__ import annotations

import argparse
import array
import hashlib
import os
import pathlib
import sys
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, HTTPServer


SAMPLE_RATE = 16_000
MAX_DURATION_SECONDS = 25
MAX_PCM_BYTES = SAMPLE_RATE * MAX_DURATION_SECONDS * 2
MAX_TRANSCRIPT_CHARS = 4_096
PATH = "/v1/audio/transcriptions"


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid transcript")
    value = unicodedata.normalize("NFKC", value)
    value = " ".join(value.replace("\x00", " ").split())
    if not value or len(value) > MAX_TRANSCRIPT_CHARS:
        raise ValueError("invalid transcript")
    return value


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BoundedHTTPServer(HTTPServer):
    request_queue_size = 2

    def __init__(self, address, handler, model):
        super().__init__(address, handler)
        self.model = model
        self.model_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") != "/healthz":
            self._reply(404, b"not found\n", "text/plain")
            return
        self._reply(200, b'{"status":"ok"}\n', "application/json")

    def do_POST(self) -> None:
        if self.path != PATH:
            self._reply(404, b"not found\n", "text/plain")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/octet-stream":
            self._reply(415, b"unsupported media type\n", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_PCM_BYTES or length % 2:
            self._reply(413, b"invalid audio size\n", "text/plain")
            return
        self.connection.settimeout(5)
        body = self.rfile.read(length)
        if len(body) != length:
            self._reply(400, b"incomplete audio\n", "text/plain")
            return
        samples = array.array("h")
        samples.frombytes(body)
        if sys.byteorder != "little":
            samples.byteswap()
        float_samples = array.array("f", (sample / 32768.0 for sample in samples))
        try:
            with self.server.model_lock:
                with self.server.model.session(n_threads=2) as session:
                    result = session.run(float_samples, language="ru", timestamps="none")
            transcript = _normalize(result.text).encode("utf-8")
        except Exception:
            self._reply(503, b"transcription failed\n", "text/plain")
            return
        self._reply(200, transcript, "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        assert MAX_PCM_BYTES == 800_000
        assert _normalize("  тест\x00  worker ") == "тест worker"
        print("mac-stt-selfcheck-ok")
        return 0

    model_path = pathlib.Path(os.environ["UAP_STT_MODEL"])
    expected_sha = os.environ["UAP_STT_MODEL_SHA256"].lower()
    if not model_path.is_file() or model_path.is_symlink() or _sha256(model_path) != expected_sha:
        raise SystemExit("refusing to load an unpinned STT model")
    import transcribe_cpp

    model = transcribe_cpp.Model(model_path, backend="metal")
    bind = os.environ.get("UAP_STT_BIND", "100.116.97.112")
    port = int(os.environ.get("UAP_STT_PORT", "8091"))
    server = BoundedHTTPServer((bind, port), Handler, model)
    print(f"uap local STT ready on {bind}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
