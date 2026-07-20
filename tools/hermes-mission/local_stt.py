#!/usr/bin/env python3
"""Bounded local voice-note preprocessing for the Hermes command-STT seam."""

from __future__ import annotations

import argparse
import array
import contextlib
import fcntl
import http.client
import json
import os
import pathlib
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse


MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DURATION_SECONDS = 15 * 60
CHUNK_DURATION_SECONDS = 20
MAX_PCM_BYTES = int(MAX_DURATION_SECONDS * 16_000 * 2)
MAX_CHUNK_PCM_BYTES = CHUNK_DURATION_SECONDS * 16_000 * 2
MAX_CHUNK_TRANSCRIPT_CHARS = 4_096
MAX_TRANSCRIPT_CHARS = 16_384
DECODE_TIMEOUT_SECONDS = 12
CPU_SECONDS = 40
ADDRESS_SPACE_BYTES = 1_500 * 1024 * 1024
LOCK_WAIT_SECONDS = 5
REMOTE_TIMEOUT_SECONDS = 8
ALLOWED_SUFFIXES = {
    ".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".mp4",
    ".ogg", ".opus", ".wav", ".webm",
}
ALLOWED_FORMATS = {
    "aac", "aiff", "flac", "matroska", "mov", "mp3", "mp4", "ogg",
    "wav", "webm",
}


class STTFailure(RuntimeError):
    """An owner-safe, transcript-free preprocessing failure."""


def _limit_process() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(
        resource.RLIMIT_AS,
        (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES),
    )
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PCM_BYTES + 4096,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _binary(env_name: str, default: str) -> str:
    candidate = os.environ.get(env_name, default)
    resolved = shutil.which(candidate)
    if not resolved:
        raise STTFailure("decoder unavailable")
    return resolved


def _probe(path: pathlib.Path) -> float:
    command = [
        _binary("UAP_STT_FFPROBE", "ffprobe"),
        "-v", "error",
        "-protocol_whitelist", "file,pipe",
        "-show_entries", "format=duration,format_name",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=DECODE_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        formats = set(str(payload["format"]["format_name"]).split(","))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise STTFailure("invalid audio metadata") from None
    except (OSError, subprocess.SubprocessError):
        raise STTFailure("audio probe failed") from None
    if not 0 < duration <= MAX_DURATION_SECONDS:
        raise STTFailure("voice note exceeds the 15 minute safety ceiling")
    if not formats.intersection(ALLOWED_FORMATS):
        raise STTFailure("unsupported audio container")
    return duration


def _decode(path: pathlib.Path, target: pathlib.Path) -> None:
    command = [
        _binary("UAP_STT_FFMPEG", "ffmpeg"),
        "-nostdin", "-v", "error", "-threads", "1",
        "-protocol_whitelist", "file,pipe",
        "-i", str(path),
        "-map_metadata", "-1", "-vn", "-sn", "-dn",
        "-t", str(MAX_DURATION_SECONDS),
        "-ac", "1", "-ar", "16000", "-f", "s16le",
        "-fs", str(MAX_PCM_BYTES),
        str(target),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=DECODE_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        raise STTFailure("safe audio decode failed") from None
    try:
        size = target.stat().st_size
    except OSError:
        raise STTFailure("safe audio decode produced no output") from None
    if size == 0 or size > MAX_PCM_BYTES or size % 2:
        raise STTFailure("safe audio decode produced invalid PCM")


def _pcm(raw: bytes) -> array.array[float]:
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return array.array("f", (sample / 32768.0 for sample in samples))


def _normalize_transcript(value: object) -> str:
    if not isinstance(value, str):
        raise STTFailure("local model returned invalid text")
    value = unicodedata.normalize("NFKC", value)
    value = " ".join(value.replace("\x00", " ").split())
    if not value or len(value) > MAX_TRANSCRIPT_CHARS:
        raise STTFailure("local model returned invalid text")
    return value


def _remote_transcribe(body: bytes, endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise STTFailure("remote transcriber configuration is invalid")
    if not 0 < len(body) <= MAX_CHUNK_PCM_BYTES or len(body) % 2:
        raise STTFailure("decoded audio is outside the remote limit")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port or 80,
        timeout=REMOTE_TIMEOUT_SECONDS,
    )
    try:
        connection.request(
            "POST",
            parsed.path or "/",
            body=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_CHUNK_TRANSCRIPT_CHARS * 4 + 1)
        if response.status != 200 or len(raw) > MAX_CHUNK_TRANSCRIPT_CHARS * 4:
            raise STTFailure("remote transcriber failed")
        try:
            return _normalize_transcript(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise STTFailure("remote transcriber returned invalid text") from None
    except (OSError, http.client.HTTPException):
        raise STTFailure("remote transcriber unavailable") from None
    finally:
        connection.close()


@contextlib.contextmanager
def _exclusive_model(model_path: pathlib.Path):
    """Serialize model loads so concurrent voice notes cannot multiply RAM."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    with model_path.open("rb") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise STTFailure("local transcriber is busy") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def transcribe(input_path: pathlib.Path, model_path: pathlib.Path) -> str:
    if input_path.is_symlink() or not input_path.is_file():
        raise STTFailure("audio input is not a regular file")
    input_path = input_path.resolve(strict=True)
    if input_path.suffix.casefold() not in ALLOWED_SUFFIXES:
        raise STTFailure("unsupported audio filename")
    if not 0 < input_path.stat().st_size <= MAX_INPUT_BYTES:
        raise STTFailure("voice note exceeds the 8 MiB limit")
    if model_path.is_symlink() or not model_path.is_file():
        raise STTFailure("local model is unavailable")
    model_path = model_path.resolve(strict=True)

    _probe(input_path)
    with tempfile.TemporaryDirectory(prefix="uap-stt-") as temporary:
        pcm_path = pathlib.Path(temporary) / "audio.s16"
        _decode(input_path, pcm_path)
        remote_endpoint = os.environ.get("UAP_STT_REMOTE_URL", "").strip()
        short_audio = pcm_path.stat().st_size <= MAX_CHUNK_PCM_BYTES
        transcripts: list[str] = []
        try:
            with pcm_path.open("rb") as handle:
                while chunk := handle.read(MAX_CHUNK_PCM_BYTES):
                    if remote_endpoint:
                        try:
                            transcripts.append(_remote_transcribe(chunk, remote_endpoint))
                            continue
                        except STTFailure:
                            if not short_audio:
                                raise STTFailure(
                                    "long voice transcription requires the Mac worker"
                                ) from None
                    samples = _pcm(chunk)
                    with _exclusive_model(model_path):
                        try:
                            import transcribe_cpp

                            result = transcribe_cpp.transcribe(
                                model_path,
                                samples,
                                backend="cpu",
                                n_threads=2,
                                language="ru",
                                timestamps="none",
                            )
                        except Exception:
                            raise STTFailure("local inference failed") from None
                    transcripts.append(
                        _normalize_transcript(getattr(result, "text", None))
                    )
        except OSError:
            raise STTFailure("failed to read decoded audio") from None
    return _normalize_transcript(" ".join(transcripts))


def _write_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".stt-", delete=False
        ) as handle:
            handle.write(text + "\n")
            temporary = pathlib.Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--model", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        _limit_process()
        transcript = transcribe(args.input, args.model)
        _write_atomic(args.output.resolve(), transcript)
    except STTFailure as error:
        print(f"local STT rejected input: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("local STT failed safely", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
