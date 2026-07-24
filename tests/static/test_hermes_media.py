#!/usr/bin/env python3
"""Component regression for the Central subscription image path."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import tempfile
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


missions = load("uap_missions_test", ROOT / "tools/hermes-mission/runtime.py")
media = load("uap_media_test", ROOT / "tools/hermes-mission/media.py")


class FakeResult:
    error = None


class FakeClient:
    def request(self, method, params):
        assert method == "modelProvider/capabilities/read"
        assert params == {}
        return {"imageGeneration": True}


class FakeSession:
    calls = 0

    def __init__(self, *, cwd, on_event):
        self.cwd = pathlib.Path(cwd)
        self.on_event = on_event
        self._client = FakeClient()

    def ensure_started(self):
        return "thread-media-1"

    def run_turn(self, *, user_input):
        assert user_input.startswith("$imagegen\n")
        FakeSession.calls += 1
        generated = self.cwd / "generated.png"
        generated.write_bytes(b"\x89PNG\r\n\x1a\n" + b"bounded-test-image")
        self.on_event({
            "method": "item/completed",
            "params": {"item": {
                "id": "image-1",
                "type": "imageGeneration",
                # Codex 0.142.0 keeps this value even on item/completed.
                "status": "generating",
                "result": "ignored-base64",
                "savedPath": str(generated),
            }},
        })
        return FakeResult()

    def close(self):
        pass


def test_media_mission_is_durable_and_does_not_generate_twice() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        previous_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = temporary
        original_runtime_check = media._runtime_is_openai_only
        original_generate = media.generate_image
        try:
            media._runtime_is_openai_only = lambda: True

            def fake_generate(mission_id, prompt, *, on_thread_started):
                return original_generate(
                    mission_id,
                    prompt,
                    on_thread_started=on_thread_started,
                    session_factory=FakeSession,
                )

            media.generate_image = fake_generate
            store = missions.MissionStore(pathlib.Path(temporary) / "missions.sqlite3")
            accepted, created = store.ingest_owner_turn(
                "Сгенерируй изображение: маяк на скалистом берегу",
                platform="telegram",
                source_message_id="42",
                session_id="session-media",
                chat_id="729937253",
            )
            assert created
            mission_id = accepted["mission_id"]
            view = media.execute_media_mission(store, mission_id)
            assert view["status"] == "completed"
            assert view["capability"] == media.MEDIA_CAPABILITY
            assert len(view["artifacts"]) == 1
            artifact = store.media_artifact(mission_id)
            assert artifact and pathlib.Path(artifact["path"]).is_file()
            assert artifact["provider"] == "openai-codex"
            assert artifact["model"] == "gpt-image-2"
            assert FakeSession.calls == 1

            replay = media.execute_media_mission(
                missions.MissionStore(pathlib.Path(temporary) / "missions.sqlite3"),
                mission_id,
            )
            assert replay["projection_id"] == view["projection_id"]
            assert FakeSession.calls == 1

            try:
                store.ingest_owner_turn(
                    "$imagegen edit this image: remove the logo",
                    platform="telegram",
                    source_message_id="43",
                    session_id="session-media",
                    chat_id="729937253",
                )
            except missions.MissionError as error:
                assert "editing is unavailable" in str(error)
            else:
                raise AssertionError("image editing must fail closed")
        finally:
            media._runtime_is_openai_only = original_runtime_check
            media.generate_image = original_generate
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home


TWO_PROJECT_CATALOG = json.dumps({
    "schema_version": 1,
    "projects": [
        {
            "project_id": "alpha",
            "label": "Alpha",
            "repository": "owner/alpha",
            "summary": "First project",
            "aliases": ["alpha"],
            "dispatch_profile": "build1-alpha-v1",
            "delivery_mode": "none",
            "platforms": ["workspace", "telegram"],
        },
        {
            "project_id": "beta",
            "label": "Beta",
            "repository": "owner/beta",
            "summary": "Second project",
            "aliases": ["beta"],
            "dispatch_profile": "build1-beta-v1",
            "delivery_mode": "none",
            "platforms": ["workspace", "telegram"],
        },
    ],
})

MEDIA_TOPICS_SUPERGROUP = json.dumps([
    {"chat_id": "supergroup", "thread_id": "images-topic"},
])


def test_topic_routes_ordinary_text_to_media() -> None:
    """Configured (chat_id, thread_id) pair routes ordinary text to media."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_PROJECTS": TWO_PROJECT_CATALOG,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            accepted, created = store.ingest_owner_turn(
                "lighthouse on a rocky shore at sunset",
                platform="telegram",
                source_message_id="img-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert created
            assert accepted["payload"]["capability"] == "media.image.generate"
            assert accepted["payload"]["goal"] == "lighthouse on a rocky shore at sunset"
            assert store.bound_mission(
                "telegram", "supergroup", "images-topic"
            ) == accepted["mission_id"]


def test_same_thread_id_in_different_chat_is_not_media_or_code_intake() -> None:
    """A chat-local topic mismatch cannot turn an image description into code."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_PROJECTS": TWO_PROJECT_CATALOG,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "lighthouse on a rocky shore at sunset",
                    platform="telegram",
                    source_message_id="other-1",
                    session_id="s1",
                    chat_id="other-chat",
                    thread_id="images-topic",
                )
                raise AssertionError("same thread_id in different chat must not route media")
            except missions.MissionError as error:
                assert str(error) == "owner turn is not an execution goal"
            assert store.latest() is None


def test_ordinary_text_in_unknown_topic_is_not_code_intake() -> None:
    """Ordinary text outside a media topic remains ordinary chat."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_PROJECTS": TWO_PROJECT_CATALOG,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "lighthouse on a rocky shore at sunset",
                    platform="telegram",
                    source_message_id="code-1",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="code-topic",
                )
                raise AssertionError("ordinary text was accepted as code intake")
            except missions.MissionError as error:
                assert str(error) == "owner turn is not an execution goal"
            assert store.latest() is None


def test_pending_code_draft_intact_while_images_topic_media_accepted() -> None:
    """A pending Code draft survives while ordinary Images-topic media is accepted."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_PROJECTS": TWO_PROJECT_CATALOG,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "add a status command",
                    platform="telegram",
                    source_message_id="code-1",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="code-topic",
                )
            except missions.MissionProjectRequired:
                pass
            code_scope = missions._json(
                {"chat_id": "supergroup", "thread_id": "code-topic"}
            )
            assert store._intake_draft("telegram", code_scope) is not None

            accepted, created = store.ingest_owner_turn(
                "mountain lake with morning fog",
                platform="telegram",
                source_message_id="img-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert created
            assert accepted["payload"]["capability"] == "media.image.generate"

            assert store._intake_draft("telegram", code_scope) is not None
            draft = store._intake_draft("telegram", code_scope)
            assert draft["goal"] == "add a status command"

            selected, selected_created = store.ingest_owner_turn(
                "alpha",
                platform="telegram",
                source_message_id="code-2",
                session_id="s1",
                chat_id="supergroup",
                thread_id="code-topic",
            )
            assert selected_created
            assert selected["payload"]["project_id"] == "alpha"


def test_images_topic_replay_returns_same_mission() -> None:
    """Replay of the Images source message returns the same mission, no duplicate."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            first, created1 = store.ingest_owner_turn(
                "lighthouse on a rocky shore",
                platform="telegram",
                source_message_id="img-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert created1
            second, created2 = store.ingest_owner_turn(
                "lighthouse on a rocky shore",
                platform="telegram",
                source_message_id="img-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert not created2
            assert second["mission_id"] == first["mission_id"]


def test_explicit_imagegen_works_outside_media_topic() -> None:
    """Explicit $imagegen still works in a non-configured topic."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            accepted, created = store.ingest_owner_turn(
                "$imagegen: lighthouse on a rocky shore",
                platform="telegram",
                source_message_id="img-explicit",
                session_id="s1",
                chat_id="supergroup",
                thread_id="code-topic",
            )
            assert created
            assert accepted["payload"]["capability"] == "media.image.generate"
            assert accepted["payload"]["goal"] == "lighthouse on a rocky shore"


def test_voice_transcript_uses_topic_dispatch() -> None:
    """Voice transcript (ordinary text at the ingest_owner_turn seam) routes via topic pair."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            accepted, created = store.ingest_owner_turn(
                "sunset over the mountains with a river",
                platform="telegram",
                source_message_id="voice-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert created
            assert accepted["payload"]["capability"] == "media.image.generate"
            assert accepted["payload"]["goal"] == "sunset over the mountains with a river"


def test_malformed_media_topics_config_fails_closed() -> None:
    """Malformed HERMES_MISSION_MEDIA_TOPICS fails closed at the helper level."""
    malformed_values = [
        '{"not": "a list"}',
        '[{"chat_id": "a", "thread_id": "b", "extra": true}]',
        '[{"chat_id": "a"}]',
        '[{"chat_id": "a", "thread_id": 123}]',
        '[{"chat_id": "a", "thread_id": "b"}, {"chat_id": "a", "thread_id": "b"}]',
        '[{"chat_id": "", "thread_id": "b"}]',
        '[{"chat_id": "a", "thread_id": ""}]',
        '[{"chat_id": "a", "thread_id": "ctrl\\u0000"}]',
        "not json at all",
        "[",
        '["plain-string-not-object"]',
        '[{"chat_id":"allowed","chat_id":"other","thread_id":"images"}]',
    ]
    for malformed in malformed_values:
        with tempfile.TemporaryDirectory() as temporary:
            env_patch = {
                "HERMES_HOME": temporary,
                "HERMES_MISSION_MEDIA_TOPICS": malformed,
            }
            with mock.patch.dict(os.environ, env_patch, clear=False):
                try:
                    missions.media_topic_pairs()
                    raise AssertionError(
                        f"malformed config was accepted: {malformed!r}"
                    )
                except missions.MissionError as error:
                    assert "media topic" in str(error)

    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": "",
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            assert missions.media_topic_pairs() == set()


def test_malformed_config_blocks_owner_turn_with_zero_side_effects() -> None:
    """Malformed config raises MissionError on owner turn; no mission or draft created."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_PROJECTS": TWO_PROJECT_CATALOG,
            "HERMES_MISSION_MEDIA_TOPICS": '[{"chat_id": "supergroup"}]',
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "lighthouse on a rocky shore",
                    platform="telegram",
                    source_message_id="bad-1",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="images-topic",
                )
                raise AssertionError("malformed config must block the owner turn")
            except missions.MissionError as error:
                assert "media topic" in str(error)
            assert store.list(100) == []
            scope = missions._json(
                {"chat_id": "supergroup", "thread_id": "images-topic"}
            )
            assert store._intake_draft("telegram", scope) is None


def test_voice_topic_replay_with_different_transcript_returns_same_mission() -> None:
    """A redelivered voice note (same message_id, different STT text) is one mission.

    Local STT is non-deterministic: the same voice message can transcribe
    differently on a transport redelivery.  Mission identity is the stable
    Telegram source_message_id (via the source_key-derived mission_id), not the
    transcript content, so the replay must return the original mission instead
    of failing closed as a goal collision or generating a second image.
    """
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            first, created1 = store.ingest_owner_turn(
                "sunset over the mountains with a river",
                platform="telegram",
                source_message_id="voice-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert created1
            assert first["payload"]["capability"] == "media.image.generate"
            second, created2 = store.ingest_owner_turn(
                "sunset over mountains near a river",
                platform="telegram",
                source_message_id="voice-1",
                session_id="s1",
                chat_id="supergroup",
                thread_id="images-topic",
            )
            assert not created2
            assert second["mission_id"] == first["mission_id"]


def test_media_topic_edit_request_fails_closed() -> None:
    """Image edit requests in a configured media topic still fail closed."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "edit the image: remove the logo",
                    platform="telegram",
                    source_message_id="edit-1",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="images-topic",
                )
                raise AssertionError("edit request must fail closed in media topic")
            except missions.MissionError as error:
                assert "editing is unavailable" in str(error)


def test_telegram_download_retries_transient_failure_only() -> None:
    class TimedOut(Exception):
        pass

    class FakeFile:
        calls = 0

        async def download_as_bytearray(self, **timeouts):
            self.calls += 1
            assert timeouts == {
                "read_timeout": 30.0,
                "write_timeout": 30.0,
                "connect_timeout": 15.0,
                "pool_timeout": 15.0,
            }
            if self.calls < 3:
                raise TimedOut("temporary Telegram timeout")
            return bytearray(b"voice")

    class TransientSource:
        calls = 0

        async def get_file(self, **timeouts):
            self.calls += 1
            assert timeouts == {
                "read_timeout": 30.0,
                "write_timeout": 30.0,
                "connect_timeout": 15.0,
                "pool_timeout": 15.0,
            }
            return file

    file = FakeFile()
    source = TransientSource()
    with mock.patch.object(media.asyncio, "sleep", new=mock.AsyncMock()) as sleep:
        _, body = asyncio.run(media.download_telegram_file(source))
    assert body == b"voice"
    assert source.calls == 3
    assert file.calls == 3
    assert sleep.await_count == 2

    class PermanentSource:
        calls = 0

        async def get_file(self, **_timeouts):
            self.calls += 1
            raise ValueError("invalid Telegram file")

    permanent = PermanentSource()
    try:
        asyncio.run(media.download_telegram_file(permanent))
        raise AssertionError("permanent download error must fail")
    except ValueError:
        pass
    assert permanent.calls == 1


MIXED_REJECTION = "image generation and project changes must be sent as separate messages"


def test_english_mixed_media_code_rejected() -> None:
    """English natural mixed image+code request is rejected with no mission."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "generate an image: add a login form to the repository",
                    platform="telegram",
                    source_message_id="mix-en-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("English mixed request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []


def test_russian_mixed_media_code_rejected() -> None:
    """Russian natural mixed image+code request is rejected with no mission."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "сгенерируй изображение: добавь форму входа в репозиторий",
                    platform="telegram",
                    source_message_id="mix-ru-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("Russian mixed request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []


def test_explicit_imagegen_mixed_rejected() -> None:
    """Explicit $imagegen mixed image+code request is rejected with no mission."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "$imagegen add a login form to the project",
                    platform="telegram",
                    source_message_id="mix-explicit-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("explicit $imagegen mixed request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []


def test_pure_image_prompts_remain_media() -> None:
    """Pure image prompts without code targets remain media missions in a topic."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            for idx, prompt in enumerate([
                "add a lighthouse",
                "remove clouds",
                "draw a login screen illustration",
            ]):
                accepted, created = store.ingest_owner_turn(
                    prompt,
                    platform="telegram",
                    source_message_id=f"pure-{idx}",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="images-topic",
                )
                assert created, f"pure prompt must create a media mission: {prompt!r}"
                assert accepted["payload"]["capability"] == "media.image.generate"


def test_mixed_rejected_in_media_topic() -> None:
    """Mixed image+code request in a configured media topic is rejected."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {
            "HERMES_HOME": temporary,
            "HERMES_MISSION_MEDIA_TOPICS": MEDIA_TOPICS_SUPERGROUP,
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "$imagegen add a login form to the project",
                    platform="telegram",
                    source_message_id="mix-topic-1",
                    session_id="s1",
                    chat_id="supergroup",
                    thread_id="images-topic",
                )
                raise AssertionError("mixed request in media topic must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []


def test_replay_after_mixed_rejection_creates_nothing() -> None:
    """source_message_id replay after mixed rejection creates no receipt or event."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            for _attempt in range(2):
                try:
                    store.ingest_owner_turn(
                        "$imagegen add a login form to the project",
                        platform="telegram",
                        source_message_id="mix-replay-1",
                        session_id="s1",
                        chat_id="729937253",
                    )
                    raise AssertionError("replay of mixed request must be rejected")
                except missions.MissionError as error:
                    assert MIXED_REJECTION in str(error)
            assert store.list(100) == []
            assert store.latest() is None


def test_mixed_generate_logo_in_app_ui_rejected() -> None:
    """'generate a logo and use it in the app UI' is rejected with zero side effects."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "generate a logo and use it in the app UI",
                    platform="telegram",
                    source_message_id="mix-logo-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("mixed logo+code request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []
            assert store.latest() is None


def test_mixed_create_image_add_to_readme_rejected() -> None:
    """'create an image and add it to README.md' is rejected with zero side effects."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "create an image and add it to README.md",
                    platform="telegram",
                    source_message_id="mix-readme-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("mixed image+README request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []
            assert store.latest() is None


def test_mixed_russian_attach_to_repo_rejected() -> None:
    """Russian mixed image+repo request is rejected with zero side effects."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "Сгенерируй изображение и приложи его к репозиторию проекта",
                    platform="telegram",
                    source_message_id="mix-ru-attach-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("Russian mixed request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []
            assert store.latest() is None


def test_mixed_russian_embed_in_interface_rejected() -> None:
    """'сгенерируй логотип и внедри его в интерфейс проекта' is rejected."""
    with tempfile.TemporaryDirectory() as temporary:
        env_patch = {"HERMES_HOME": temporary}
        with mock.patch.dict(os.environ, env_patch, clear=False):
            store = missions.MissionStore(pathlib.Path(temporary) / "m.sqlite3")
            try:
                store.ingest_owner_turn(
                    "сгенерируй логотип и внедри его в интерфейс проекта",
                    platform="telegram",
                    source_message_id="mix-ru-embed-1",
                    session_id="s1",
                    chat_id="729937253",
                )
                raise AssertionError("Russian mixed request must be rejected")
            except missions.MissionError as error:
                assert MIXED_REJECTION in str(error)
            assert store.list(100) == []
            assert store.latest() is None


if __name__ == "__main__":
    test_media_mission_is_durable_and_does_not_generate_twice()
    test_topic_routes_ordinary_text_to_media()
    test_same_thread_id_in_different_chat_is_not_media_or_code_intake()
    test_ordinary_text_in_unknown_topic_is_not_code_intake()
    test_pending_code_draft_intact_while_images_topic_media_accepted()
    test_images_topic_replay_returns_same_mission()
    test_explicit_imagegen_works_outside_media_topic()
    test_voice_transcript_uses_topic_dispatch()
    test_voice_topic_replay_with_different_transcript_returns_same_mission()
    test_malformed_media_topics_config_fails_closed()
    test_malformed_config_blocks_owner_turn_with_zero_side_effects()
    test_media_topic_edit_request_fails_closed()
    test_telegram_download_retries_transient_failure_only()
    test_english_mixed_media_code_rejected()
    test_russian_mixed_media_code_rejected()
    test_explicit_imagegen_mixed_rejected()
    test_pure_image_prompts_remain_media()
    test_mixed_rejected_in_media_topic()
    test_replay_after_mixed_rejection_creates_nothing()
    test_mixed_generate_logo_in_app_ui_rejected()
    test_mixed_create_image_add_to_readme_rejected()
    test_mixed_russian_attach_to_repo_rejected()
    test_mixed_russian_embed_in_interface_rejected()
    print("hermes-media-ok")
