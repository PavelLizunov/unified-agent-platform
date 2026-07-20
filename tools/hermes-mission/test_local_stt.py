#!/usr/bin/env python3
"""Component regression for voice preprocessing -> exactly one Central mission."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer


ROOT = pathlib.Path(__file__).resolve().parents[2]
STT = pathlib.Path(__file__).with_name("local_stt.py")
MISSION_RUNTIME = pathlib.Path(__file__).with_name("runtime.py")
LOCAL_ROUTER = ROOT / "tools" / "local-models" / "route.py"


class FakeMacSTT(BaseHTTPRequestHandler):
    received_lengths: list[int] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        assert self.path == "/v1/audio/transcriptions"
        assert self.headers["Content-Type"] == "application/octet-stream"
        assert len(body) == 20 * 16_000 * 2
        self.received_lengths.append(len(body))
        transcript = "Проверить резервную копию.".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(transcript)))
        self.end_headers()
        self.wfile.write(transcript)

    def log_message(self, *args) -> None:
        return


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _executable(path: pathlib.Path, source: str) -> pathlib.Path:
    path.write_text(source, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def main() -> None:
    if os.name != "posix":
        raise SystemExit("local STT component test requires a POSIX runner")
    with tempfile.TemporaryDirectory(prefix="uap-local-stt-test-") as temporary:
        root = pathlib.Path(temporary)
        audio = root / "voice.ogg"
        audio.write_bytes(b"bounded fake ogg")
        model = root / "model.gguf"
        model.write_bytes(b"fake model")
        output = root / "transcript.txt"
        fake_bin = root / "bin"
        fake_bin.mkdir()
        _executable(
            fake_bin / "ffprobe",
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'format': {'duration': '20', 'format_name': 'ogg'}}))\n",
        )
        _executable(
            fake_bin / "ffmpeg",
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[-1]).write_bytes(b'\\0' * (20 * 16000 * 2))\n",
        )
        fake_python = root / "python"
        fake_python.mkdir()
        (fake_python / "transcribe_cpp.py").write_text(
            textwrap.dedent(
                """
                import os
                import pathlib
                from types import SimpleNamespace
                def transcribe(model, samples, **kwargs):
                    pathlib.Path(os.environ["UAP_STT_FALLBACK_MARKER"]).write_text("called")
                    assert kwargs == {
                        "backend": "cpu", "n_threads": 2, "language": "ru",
                        "timestamps": "none",
                    }
                    assert len(samples) == 20 * 16000
                    return SimpleNamespace(text="  Локальная   резервная расшифровка.  ")
                """
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update({
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "PYTHONPATH": str(fake_python),
            "UAP_STT_FFPROBE": str(fake_bin / "ffprobe"),
            "UAP_STT_FFMPEG": str(fake_bin / "ffmpeg"),
            "UAP_STT_FALLBACK_MARKER": str(root / "fallback-called"),
        })
        backend = HTTPServer(("127.0.0.1", 0), FakeMacSTT)
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        router_port = _free_port()
        router_env = os.environ.copy()
        router_env.update({
            "ROUTER_PORT": str(router_port),
            "STT_URL": f"http://127.0.0.1:{backend.server_port}/v1/audio/transcriptions",
        })
        router = subprocess.Popen(
            [sys.executable, str(LOCAL_ROUTER)],
            env=router_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{router_port}/v1/models", timeout=0.2
                    ).close()
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AssertionError("local-model router did not start")
                    time.sleep(0.05)
            env["UAP_STT_REMOTE_URL"] = (
                f"http://127.0.0.1:{router_port}/v1/audio/transcriptions"
            )
            completed = subprocess.run(
                [sys.executable, str(STT), str(audio), str(output), "--model", str(model)],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
        finally:
            router.terminate()
            router.wait(timeout=5)
            backend.shutdown()
            backend.server_close()
            backend_thread.join(timeout=5)
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == ""
        assert output.read_text(encoding="utf-8") == "Проверить резервную копию.\n"
        assert FakeMacSTT.received_lengths == [20 * 16_000 * 2]
        assert not (root / "fallback-called").exists()

        fallback_output = root / "fallback.txt"
        fallback = subprocess.run(
            [sys.executable, str(STT), str(audio), str(fallback_output), "--model", str(model)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert fallback.returncode == 0, fallback.stderr
        assert fallback_output.read_text(encoding="utf-8") == "Локальная резервная расшифровка.\n"
        assert (root / "fallback-called").read_text() == "called"

        symlink = root / "linked.ogg"
        symlink.symlink_to(audio)
        linked = subprocess.run(
            [sys.executable, str(STT), str(symlink), str(root / "linked.txt"), "--model", str(model)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert linked.returncode == 2
        assert "not a regular file" in linked.stderr
        assert not (root / "linked.txt").exists()

        namespace: dict[str, object] = {"__file__": str(MISSION_RUNTIME)}
        exec(compile(MISSION_RUNTIME.read_text(encoding="utf-8"), MISSION_RUNTIME, "exec"), namespace)
        MissionStore = namespace["MissionStore"]
        database = root / "missions.sqlite3"
        os.environ.pop("HERMES_MISSION_PROJECTS", None)
        os.environ["HERMES_MISSION_INTAKE_ROUTES"] = json.dumps({
            "telegram": {"dispatch_profile": "uap", "delivery_mode": "none"}
        })
        transcript = output.read_text(encoding="utf-8").strip()
        first, created = MissionStore(database).ingest_owner_turn(
            transcript,
            platform="telegram",
            source_message_id="telegram-message-4242",
            chat_id="owner-chat",
        )
        replay, replay_created = MissionStore(database).ingest_owner_turn(
            transcript,
            platform="telegram",
            source_message_id="telegram-message-4242",
            chat_id="owner-chat",
        )
        assert created is True and replay_created is False
        assert first["mission_id"] == replay["mission_id"]
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT COUNT(DISTINCT mission_id) FROM mission_events"
            ).fetchone()[0] == 1

        output.unlink()
        env["UAP_STT_FFPROBE_DURATION"] = "26"
        (fake_bin / "ffprobe").write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'format': {'duration': '26', 'format_name': 'ogg'}}))\n",
            encoding="utf-8",
        )
        failed = subprocess.run(
            [sys.executable, str(STT), str(audio), str(output), "--model", str(model)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert failed.returncode == 2
        assert "25 second limit" in failed.stderr
        assert not output.exists()
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT COUNT(DISTINCT mission_id) FROM mission_events"
            ).fetchone()[0] == 1
        failed_database = root / "failed-missions.sqlite3"
        MissionStore(failed_database)
        with sqlite3.connect(failed_database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM mission_events").fetchone()[0] == 0

    print("local STT component checks passed")


if __name__ == "__main__":
    main()
