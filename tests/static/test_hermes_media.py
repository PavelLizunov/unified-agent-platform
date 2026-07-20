#!/usr/bin/env python3
"""Component regression for the Central subscription image path."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile


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
                "status": "completed",
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


if __name__ == "__main__":
    test_media_mission_is_durable_and_does_not_generate_twice()
    print("hermes-media-ok")
