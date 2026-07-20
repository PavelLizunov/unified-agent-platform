#!/usr/bin/env python3
"""Component regression for voice preprocessing -> exactly one Central mission."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import textwrap


ROOT = pathlib.Path(__file__).resolve().parents[2]
STT = pathlib.Path(__file__).with_name("local_stt.py")
MISSION_RUNTIME = pathlib.Path(__file__).with_name("runtime.py")


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
            "print(json.dumps({'format': {'duration': '3.5', 'format_name': 'ogg'}}))\n",
        )
        _executable(
            fake_bin / "ffmpeg",
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[-1]).write_bytes(b'\\0' * (16000 * 4))\n",
        )
        fake_python = root / "python"
        fake_python.mkdir()
        (fake_python / "transcribe_cpp.py").write_text(
            textwrap.dedent(
                """
                from types import SimpleNamespace
                def transcribe(model, samples, **kwargs):
                    assert kwargs == {
                        "backend": "cpu", "n_threads": 2, "language": "ru",
                        "timestamps": "none",
                    }
                    assert len(samples) == 16000
                    return SimpleNamespace(text="  Проверить   резервную копию.  ")
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
        })
        completed = subprocess.run(
            [sys.executable, str(STT), str(audio), str(output), "--model", str(model)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == ""
        assert output.read_text(encoding="utf-8") == "Проверить резервную копию.\n"

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
