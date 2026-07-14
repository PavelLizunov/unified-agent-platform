"""Hermetic A6.3 gate for the central mission log and both projections."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tools" / "hermes-mission" / "runtime.py"
FIXTURE = ROOT / "tests" / "fixtures" / "hermes-mission-events-v1.json"
SPEC = importlib.util.spec_from_file_location("uap_missions", RUNTIME)
assert SPEC and SPEC.loader
missions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(missions)


def submission(event: dict) -> dict:
    return {
        key: event[key]
        for key in ("schema_version", "mission_id", "type", "source", "correlation", "payload")
    }


def test_reconnect_projects_one_canonical_state() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        for event in document["events"]:
            stored, created = store.append_central(document["mission_id"], submission(event))
            assert created and stored["sequence"] == event["sequence"]

        workspace = store.workspace_payload(document["mission_id"], after=5)
        restarted = missions.MissionStore(database)
        telegram_view = restarted.projection(document["mission_id"])

        assert workspace["mission"] == telegram_view
        assert workspace["cursor"] == 13
        assert [event["sequence"] for event in workspace["events"]] == list(range(6, 14))
        assert telegram_view["status"] == "completed"
        assert telegram_view["progress_percent"] == 100
        assert telegram_view["result"] == "Fixture delivered"
        assert "testing · 60%" not in missions.telegram_text(telegram_view)
        assert "complete · 100% · completed" in missions.telegram_text(telegram_view)
        assert len(telegram_view["projection_id"]) == 16


def test_producer_retry_and_notification_checkpoint_are_idempotent() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            accepted, _ = store.accept("Deliver the change", mission_id="mission-retry")
            store.bind("mission-retry", "telegram", "42", "7")
            event = {
                "schema_version": 1,
                "mission_id": "mission-retry",
                "type": "mission.stage",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:mission-retry:testing"},
                "payload": {"stage": "testing", "progress_percent": 60},
            }
            stored, created = store.append_producer("mission-retry", event)
            replayed, replay_created = store.append_producer("mission-retry", event)
            assert created and not replay_created and stored == replayed

            deliveries: list[tuple[dict, str]] = []

            async def sender(target: dict, text: str) -> None:
                deliveries.append((target, text))

            assert await missions.notify_subscribers(store, stored, sender) == 1
            assert await missions.notify_subscribers(store, replayed, sender) == 0
            assert len(deliveries) == 1
            assert deliveries[0][0]["chat_id"] == "42"
            assert "testing · 60% · active" in deliveries[0][1]
            assert accepted["sequence"] == 1 and stored["sequence"] == 2

            completed, _ = store.append_central(
                "mission-retry",
                {
                    "schema_version": 1,
                    "mission_id": "mission-retry",
                    "type": "mission.completed",
                    "source": "central-hermes",
                    "correlation": {},
                    "payload": {"result": "Delivered"},
                },
            )
            assert await missions.notify_subscribers(store, completed, sender) == 1
            assert "Result: Delivered" in deliveries[-1][1]

    asyncio.run(scenario())


def test_notification_can_repeat_after_delivery_before_checkpoint() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            store.accept("Deliver the change", mission_id="mission-notify-window")
            store.bind("mission-notify-window", "telegram", "42")
            event, _ = store.append_central(
                "mission-notify-window",
                {
                    "schema_version": 1,
                    "mission_id": "mission-notify-window",
                    "type": "mission.stage",
                    "source": "central-hermes",
                    "correlation": {},
                    "payload": {"stage": "testing", "progress_percent": 60},
                },
            )
            deliveries: list[str] = []

            async def delivered_then_failed(_target: dict, text: str) -> None:
                deliveries.append(text)
                raise RuntimeError("simulated crash after remote delivery")

            try:
                await missions.notify_subscribers(store, event, delivered_then_failed)
                raise AssertionError("delivery failure was hidden")
            except RuntimeError:
                pass

            async def retry_sender(_target: dict, text: str) -> None:
                deliveries.append(text)

            assert await missions.notify_subscribers(store, event, retry_sender) == 1
            assert len(deliveries) == 2

    asyncio.run(scenario())


def test_producer_cannot_end_mission_or_decrease_progress() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Safe mission", mission_id="mission-safe")
        store.append_producer(
            "mission-safe",
            {
                "schema_version": 1,
                "mission_id": "mission-safe",
                "type": "mission.stage",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:safe:one"},
                "payload": {"stage": "testing", "progress_percent": 60},
            },
        )
        try:
            store.append_producer(
                "mission-safe",
                {
                    "schema_version": 1,
                    "mission_id": "mission-safe",
                    "type": "mission.completed",
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": "flow:safe:forged"},
                    "payload": {"result": "forged"},
                },
            )
            raise AssertionError("producer forged mission completion")
        except missions.MissionError as error:
            assert "producer cannot" in str(error)

        try:
            store.append_producer(
                "mission-safe",
                {
                    "schema_version": 1,
                    "mission_id": "mission-safe",
                    "type": "mission.stage",
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": "flow:safe:two"},
                    "payload": {"stage": "implementing", "progress_percent": 40},
                },
            )
            raise AssertionError("progress decreased")
        except missions.MissionError as error:
            assert "progress decreased" in str(error)


def test_dispatch_profile_is_projected_and_immutable() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.accept(
            "Safe mission",
            mission_id="mission-dispatch",
            dispatch_profile="build1-uap",
        )
        assert created
        assert accepted["payload"]["dispatch_profile"] == "build1-uap"
        assert store.projection("mission-dispatch")["dispatch_profile"] == "build1-uap"
        replayed, replay_created = store.accept(
            "Safe mission",
            mission_id="mission-dispatch",
            dispatch_profile="build1-uap",
        )
        assert not replay_created and replayed == accepted
        try:
            store.accept(
                "Safe mission",
                mission_id="mission-dispatch",
                dispatch_profile="different-profile",
            )
            raise AssertionError("dispatch profile changed after acceptance")
        except missions.MissionError as error:
            assert "different parameters" in str(error)


def test_terminal_authority_is_loopback_only() -> None:
    assert missions.terminal_request_allowed("127.0.0.1")
    assert missions.terminal_request_allowed("::1")
    assert not missions.terminal_request_allowed("10.42.1.9")
    assert not missions.terminal_request_allowed(None)
    assert not missions.terminal_request_allowed("not-an-address")


def main() -> None:
    test_reconnect_projects_one_canonical_state()
    test_producer_retry_and_notification_checkpoint_are_idempotent()
    test_notification_can_repeat_after_delivery_before_checkpoint()
    test_producer_cannot_end_mission_or_decrease_progress()
    test_dispatch_profile_is_projected_and_immutable()
    test_terminal_authority_is_loopback_only()
    print("hermes mission runtime checks passed")


if __name__ == "__main__":
    main()
