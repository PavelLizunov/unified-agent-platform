"""Hermetic A6.3 gate for the central mission log and both projections."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sqlite3
import stat
import tempfile
import threading
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
            colliding = {**event, "payload": {"stage": "reviewing", "progress_percent": 70}}
            try:
                store.append_producer("mission-retry", colliding)
                raise AssertionError("producer event id collision was accepted")
            except missions.MissionError as error:
                assert "collision" in str(error)

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


def test_dispatch_candidates_do_not_starve_behind_newer_missions() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Old eligible mission", mission_id="mission-old", dispatch_profile="build1-uap")
        store.accept("Second eligible mission", mission_id="mission-second", dispatch_profile="build1-uap")
        for index in range(101):
            store.accept(
                f"Newer unrelated mission {index}",
                mission_id=f"mission-newer-{index}",
                dispatch_profile="another-profile",
            )

        assert all(item["mission_id"] != "mission-old" for item in store.list(100))
        candidates = store.dispatch_candidates("build1-uap", 1)
        assert [item["mission_id"] for item in candidates] == ["mission-old"]

        store.append_producer(
            "mission-old",
            {
                "schema_version": 1,
                "mission_id": "mission-old",
                "type": "task.upsert",
                "source": "build1-flow",
                "correlation": {"task_id": "task-1", "producer_event_id": "flow:old:task"},
                "payload": {"task_id": "task-1", "title": "Root", "status": "running"},
            },
        )
        assert [item["mission_id"] for item in store.dispatch_candidates(
            "build1-uap", 1, reconcile=True
        )] == ["mission-old"]
        store.append_central(
            "mission-old",
            {
                "schema_version": 1,
                "mission_id": "mission-old",
                "type": "mission.question",
                "source": "central-hermes",
                "correlation": {},
                "payload": {"question_id": "q-1", "text": "Owner decision"},
            },
        )
        assert store.projection("mission-old")["status"] == "waiting_owner"
        assert [item["mission_id"] for item in store.dispatch_candidates(
            "build1-uap", 1, reconcile=True
        )] == ["mission-old"]
        assert [item["mission_id"] for item in store.dispatch_candidates("build1-uap", 1)] == [
            "mission-second"
        ]


def test_producer_schema_is_closed_and_all_strings_are_redacted() -> None:
    event = {
        "schema_version": 1,
        "mission_id": "mission-schema",
        "type": "task.upsert",
        "source": "build1-flow",
        "correlation": {
            "session_id": "session-token",
            "task_id": "task-1",
            "producer_event_id": "flow:schema:event",
        },
        "payload": {"task_id": "task-1", "title": "token title", "status": "queued"},
    }
    sanitized = missions.sanitize_producer_submission(
        "mission-schema", event, lambda value: value.replace("token", "redacted")
    )
    assert sanitized["correlation"]["session_id"] == "session-redacted"
    assert sanitized["correlation"]["producer_event_id"] == "flow:schema:event"
    assert sanitized["payload"]["title"] == "redacted title"

    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Schema mission", mission_id="mission-schema")
        stored, created = store.append_producer("mission-schema", sanitized)
        assert created and stored["payload"]["title"] == "redacted title"

        invalid = [
            {**event, "unexpected": True},
            {**event, "payload": {**event["payload"], "details": "not allowed"}},
            {**event, "correlation": {**event["correlation"], "extra_id": "nope"}},
            {**event, "source": "untrusted-producer"},
        ]
        for submission in invalid:
            try:
                store.append_producer("mission-schema", submission)
                raise AssertionError("producer schema accepted an unknown field/source")
            except missions.MissionError:
                pass

        sensitive_id = {
            **event,
            "correlation": {**event["correlation"], "producer_event_id": "flow:schema:token"},
        }
        try:
            missions.sanitize_producer_submission(
                "mission-schema", sensitive_id, lambda value: value.replace("token", "redacted")
            )
            raise AssertionError("sensitive producer_event_id was stored")
        except missions.MissionError as error:
            assert "sensitive producer_event_id" in str(error)

        try:
            store.append_producer(
                "mission-forged",
                {
                    "schema_version": 1,
                    "mission_id": "mission-forged",
                    "type": "mission.accepted",
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": "flow:forged:accepted"},
                    "payload": {"goal": "Forged"},
                },
            )
            raise AssertionError("producer created mission.accepted")
        except missions.MissionError as error:
            assert "producer cannot" in str(error)
        assert store.events("mission-forged") == []


def test_terminal_authority_is_loopback_only() -> None:
    assert missions.terminal_request_allowed("127.0.0.1")
    assert missions.terminal_request_allowed("::1")
    assert not missions.terminal_request_allowed("10.42.1.9")
    assert not missions.terminal_request_allowed(None)
    assert not missions.terminal_request_allowed("not-an-address")


def test_central_auto_completion_requires_the_full_delivery_contract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-auto-complete"
        store.accept("Deliver safely", mission_id=mission_id, dispatch_profile="build1-target")

        def publish(event_type: str, payload: dict, number: int) -> None:
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:auto:{number}"},
                    "payload": payload,
                },
            )

        publish(
            "task.upsert",
            {"task_id": "task-1", "title": "Root", "status": "done", "assignee": "codex-luna"},
            1,
        )
        publish(
            "worker.upsert",
            {"worker_id": "task-1:run:1", "run_id": "1", "profile": "codex-luna", "status": "success"},
            2,
        )
        number = 3
        for gate_id in ("tests", "review", "ci", "post-verify"):
            publish("gate.upsert", {"gate_id": gate_id, "status": "passed"}, number)
            number += 1
        publish(
            "delivery.upsert",
            {"kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/1"},
            number,
        )
        number += 1
        publish(
            "delivery.upsert",
            {"kind": "default_branch", "status": "verified", "url": "https://example.invalid/commit/1"},
            number,
        )
        assert store.complete_if_ready(mission_id) is None

        publish("gate.upsert", {"gate_id": "cleanup", "status": "passed"}, number + 1)
        completed = store.complete_if_ready(mission_id)
        assert completed is not None and completed[1]
        assert completed[0]["source"] == "central-hermes"
        assert completed[0]["type"] == "mission.completed"
        assert store.projection(mission_id)["status"] == "completed"
        assert store.complete_if_ready(mission_id) is None


def test_auto_completion_rejects_multiple_workers() -> None:
    view = missions.empty_projection()
    view.update(
        status="active",
        tasks=[{"task_id": "task-1", "status": "done"}],
        workers=[
            {"worker_id": "worker-1", "status": "success"},
            {"worker_id": "worker-2", "status": "success"},
        ],
        gates=[{"gate_id": gate_id, "status": "passed"} for gate_id in missions._COMPLETION_GATES],
        deliveries=[
            {"kind": kind, "status": status}
            for kind, status in missions._COMPLETION_DELIVERIES.items()
        ],
    )
    assert not missions.completion_ready(view)
    view.update(
        status="waiting_owner",
        workers=[{"worker_id": "worker-1", "status": "success"}],
    )
    assert not missions.completion_ready(view)


def test_auto_completion_snapshot_and_terminal_insert_are_one_transaction() -> None:
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        mission_id = "mission-atomic-complete"
        store.accept("Deliver atomically", mission_id=mission_id)
        events = [
            ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
            ("worker.upsert", {"worker_id": "worker-1", "status": "success"}),
            *(("gate.upsert", {"gate_id": gate_id, "status": "passed"}) for gate_id in missions._COMPLETION_GATES),
            ("delivery.upsert", {"kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/1"}),
            ("delivery.upsert", {"kind": "default_branch", "status": "verified", "url": "https://example.invalid/commit/1"}),
        ]
        for number, (event_type, payload) in enumerate(events, 1):
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:atomic:{number}"},
                    "payload": payload,
                },
            )

        readiness_entered = threading.Event()
        release_completion = threading.Event()
        regression_started = threading.Event()
        outcome: dict[str, object] = {}
        original = missions.completion_ready

        def observed(view: dict) -> bool:
            readiness_entered.set()
            assert release_completion.wait(5)
            return original(view)

        def complete() -> None:
            try:
                outcome["completion"] = store.complete_if_ready(mission_id)
            except BaseException as error:
                outcome["completion_error"] = error

        def regress() -> None:
            regression_started.set()
            try:
                store.append_producer(
                    mission_id,
                    {
                        "schema_version": 1,
                        "mission_id": mission_id,
                        "type": "gate.upsert",
                        "source": "build1-flow",
                        "correlation": {"producer_event_id": "flow:atomic:regression"},
                        "payload": {"gate_id": "review", "status": "failed"},
                    },
                )
                outcome["regression"] = "committed"
            except BaseException as error:
                outcome["regression_error"] = error

        missions.completion_ready = observed
        try:
            completer = threading.Thread(target=complete)
            completer.start()
            assert readiness_entered.wait(5)
            competing = sqlite3.connect(database, timeout=0)
            competing.execute("PRAGMA busy_timeout=0")
            try:
                competing.execute("BEGIN IMMEDIATE")
                raise AssertionError("completion did not hold the SQLite write transaction")
            except sqlite3.OperationalError as error:
                assert "locked" in str(error).lower()
            finally:
                competing.close()
            regressor = threading.Thread(target=regress)
            regressor.start()
            assert regression_started.wait(5)
            release_completion.set()
            completer.join(5)
            regressor.join(5)
        finally:
            missions.completion_ready = original
            release_completion.set()
        assert not completer.is_alive() and not regressor.is_alive()
        assert "completion_error" not in outcome
        assert outcome["completion"][1]
        assert isinstance(outcome.get("regression_error"), missions.MissionError)
        assert "terminal" in str(outcome["regression_error"])
        assert store.projection(mission_id)["status"] == "completed"


def test_unresolved_question_survives_stage_and_blocks_auto_completion() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-question-block"
        store.accept("Wait for owner", mission_id=mission_id)
        store.append_central(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.question",
                "source": "central-hermes",
                "correlation": {},
                "payload": {"question_id": "q-1", "text": "Choose the product behavior"},
            },
        )
        store.append_central(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.stage",
                "source": "central-hermes",
                "correlation": {},
                "payload": {"stage": "verifying", "progress_percent": 90},
            },
        )
        events = [
            ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
            ("worker.upsert", {"worker_id": "worker-1", "status": "success"}),
            *(("gate.upsert", {"gate_id": gate_id, "status": "passed"}) for gate_id in missions._COMPLETION_GATES),
            ("delivery.upsert", {"kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/1"}),
            ("delivery.upsert", {"kind": "default_branch", "status": "verified", "url": "https://example.invalid/commit/1"}),
        ]
        for number, (event_type, payload) in enumerate(events, 1):
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:question:{number}"},
                    "payload": payload,
                },
            )
        view = store.projection(mission_id)
        assert view["status"] == "active" and view["question"]["question_id"] == "q-1"
        assert store.complete_if_ready(mission_id) is None


def test_mission_database_is_owner_only_on_posix() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "missions.sqlite3"
        database.touch(mode=0o666)
        os.chmod(database, 0o666)
        missions.MissionStore(database)
        assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(database.stat().st_mode) == 0o600


def main() -> None:
    test_reconnect_projects_one_canonical_state()
    test_producer_retry_and_notification_checkpoint_are_idempotent()
    test_notification_can_repeat_after_delivery_before_checkpoint()
    test_producer_cannot_end_mission_or_decrease_progress()
    test_dispatch_profile_is_projected_and_immutable()
    test_dispatch_candidates_do_not_starve_behind_newer_missions()
    test_producer_schema_is_closed_and_all_strings_are_redacted()
    test_terminal_authority_is_loopback_only()
    test_central_auto_completion_requires_the_full_delivery_contract()
    test_auto_completion_rejects_multiple_workers()
    test_auto_completion_snapshot_and_terminal_insert_are_one_transaction()
    test_unresolved_question_survives_stage_and_blocks_auto_completion()
    test_mission_database_is_owner_only_on_posix()
    print("hermes mission runtime checks passed")


if __name__ == "__main__":
    main()
