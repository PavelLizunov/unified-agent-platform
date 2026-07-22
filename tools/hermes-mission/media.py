"""Subscription-authenticated image generation for one Central media mission.

The runner deliberately uses Codex app-server instead of the Hermes
``openai-codex`` image provider.  The latter calls a private HTTP surface
directly; app-server is the deployed, authenticated production boundary and
returns a typed ``imageGeneration`` item with a durable ``savedPath``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Callable


MAX_IMAGE_BYTES = 25 * 1024 * 1024
MEDIA_CAPABILITY = "media.image.generate"
MEDIA_DISPATCH_PROFILE = "central-imagegen"
_ALLOWED_TYPES = {
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"RIFF": ("image/webp", ".webp"),
}


class MediaGenerationError(RuntimeError):
    """The media turn failed before a trustworthy artifact was committed."""


async def download_telegram_file(source: Any) -> tuple[Any, bytearray]:
    """Download one Telegram attachment with bounded transient retries."""
    timeouts = {
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "connect_timeout": 15.0,
        "pool_timeout": 15.0,
    }
    for attempt in range(3):
        try:
            file_obj = await source.get_file(**timeouts)
            return file_obj, await file_obj.download_as_bytearray(**timeouts)
        except Exception as error:
            retryable = error.__class__.__name__.lower() in {
                "connectionerror", "networkerror", "timedout", "timeouterror"
            } or isinstance(error, OSError)
            if not retryable or attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


def _runtime_is_openai_only() -> bool:
    try:
        from hermes_cli.config import load_config

        model = (load_config().get("model") or {})
        return (
            model.get("provider") == "openai-codex"
            and model.get("openai_runtime") == "codex_app_server"
        )
    except Exception:
        return False


def _image_type(path: Path) -> tuple[str, str]:
    size = path.stat().st_size
    if size <= 0 or size > MAX_IMAGE_BYTES:
        raise MediaGenerationError("generated image is empty or exceeds the 25 MiB limit")
    head = path.read_bytes()[:12]
    if head.startswith(b"RIFF") and head[8:12] != b"WEBP":
        raise MediaGenerationError("generated artifact is not a supported image")
    for magic, result in _ALLOWED_TYPES.items():
        if head.startswith(magic):
            return result
    raise MediaGenerationError("generated artifact is not PNG, JPEG, or WebP")


def generate_image(
    mission_id: str,
    prompt: str,
    *,
    on_thread_started: Callable[[str], None],
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run exactly one Codex image turn and materialise its bounded artifact."""
    if not _runtime_is_openai_only():
        raise MediaGenerationError(
            "media generation requires openai-codex with codex_app_server"
        )
    if not isinstance(prompt, str) or not prompt.strip():
        raise MediaGenerationError("image prompt is empty")

    if session_factory is None:
        from agent.transports.codex_app_server_session import CodexAppServerSession

        session_factory = CodexAppServerSession

    completed: list[dict[str, Any]] = []

    def capture(note: dict[str, Any]) -> None:
        item = (note.get("params") or {}).get("item") or {}
        if note.get("method") == "item/completed" and item.get("type") == "imageGeneration":
            completed.append(dict(item))

    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").resolve()
    session = session_factory(cwd=str(home), on_event=capture)
    try:
        thread_id = session.ensure_started()
        on_thread_started(thread_id)
        client = getattr(session, "_client", None)
        if client is None:
            raise MediaGenerationError("Codex app-server client is unavailable")
        capabilities = client.request("modelProvider/capabilities/read", {})
        if capabilities.get("imageGeneration") is not True:
            raise MediaGenerationError(
                "the authenticated Codex provider does not expose image generation"
            )
        result = session.run_turn(
            user_input=(
                "$imagegen\n"
                "Generate exactly one image for the request below. Use only the built-in "
                "OpenAI image generation tool. Do not use shell commands or another provider.\n\n"
                + prompt.strip()
            )
        )
        if result.error:
            raise MediaGenerationError(f"Codex image turn failed: {result.error}")
    finally:
        session.close()

    # The notification is terminal; Codex 0.142.0 may still preserve
    # status="generating" on its completed image item.
    successful = [
        item for item in completed
        if str(item.get("status", "")).lower() not in {"failed", "cancelled", "canceled"}
        and item.get("savedPath")
    ]
    if len(successful) != 1:
        raise MediaGenerationError(
            "Codex returned no unique completed image; generation will not be retried automatically"
        )

    source = Path(str(successful[0]["savedPath"])).resolve()
    if not source.is_file():
        raise MediaGenerationError("Codex reported an image path that does not exist")
    media_type, extension = _image_type(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact_id = f"image-{digest[:16]}"
    destination_dir = home / "media-artifacts" / mission_id
    destination_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(destination_dir, 0o700)
    destination = destination_dir / f"{artifact_id}{extension}"
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copyfile(source, temporary)
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise MediaGenerationError("durable image artifact digest mismatch")

    return {
        "artifact_id": artifact_id,
        "name": destination.name,
        "media_type": media_type,
        "size_bytes": destination.stat().st_size,
        "sha256": digest,
        "path": str(destination),
        "model": "gpt-image-2",
        "provider": "openai-codex",
        "thread_id": thread_id,
    }


def execute_media_mission(store: Any, mission_id: str) -> dict[str, Any]:
    """Execute or reconcile one claimed Central media mission."""
    claim = store.claim_media_job(mission_id)
    state = claim.get("state")
    if state == "claimed":
        store.start_media_projection(mission_id)
        try:
            artifact = generate_image(
                mission_id,
                store.projection(mission_id)["goal"],
                on_thread_started=lambda thread_id: store.media_thread_started(
                    mission_id, thread_id
                ),
            )
            store.record_media_success(mission_id, artifact)
        except Exception as error:
            try:
                from agent.redact import redact_sensitive_text

                message = redact_sensitive_text(str(error), force=True)
            except Exception:
                message = "Image generation failed; diagnostic was withheld"
            store.record_media_failure(mission_id, message)
    return store.finalize_media_job(mission_id)
