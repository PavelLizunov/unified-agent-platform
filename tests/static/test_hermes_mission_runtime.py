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
            # The fixture includes a historical terminal frame; public Central callers cannot.
            stored, created = store._append(document["mission_id"], submission(event))
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

            terminal = {
                "schema_version": 1,
                "mission_id": "mission-retry",
                "type": "mission.completed",
                "source": "central-hermes",
                "correlation": {},
                "payload": {"result": "Delivered"},
            }
            for event_type in ("mission.completed", " mission.completed "):
                try:
                    store.append_central("mission-retry", {**terminal, "type": event_type})
                    raise AssertionError("direct Central completion bypassed delivery gates")
                except missions.MissionError as error:
                    assert "automatic delivery contract" in str(error)

            failed, _ = store.append_central(
                "mission-retry",
                {
                    **terminal,
                    "type": "mission.failed",
                    "payload": {"error": "Delivery failed"},
                },
            )
            assert await missions.notify_subscribers(store, failed, sender) == 1
            assert "Error: Delivery failed" in deliveries[-1][1]

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


def test_notification_checkpoint_cannot_cross_a_mission_rebind() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            new_mission = "mission-new-binding"
            store.accept("New delivery", mission_id=new_mission)
            ready = [
                ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
                ("worker.upsert", {"worker_id": "worker-1", "status": "success"}),
                *(('gate.upsert', {"gate_id": gate_id, "status": "passed"})
                  for gate_id in missions._COMPLETION_GATES),
                ("delivery.upsert", {"kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/1"}),
                ("delivery.upsert", {"kind": "default_branch", "status": "verified", "url": "https://example.invalid/commit/1"}),
            ]
            for number, (event_type, payload) in enumerate(ready, 1):
                store.append_producer(
                    new_mission,
                    {
                        "schema_version": 1,
                        "mission_id": new_mission,
                        "type": event_type,
                        "source": "build1-flow",
                        "correlation": {"producer_event_id": f"flow:new:{number}"},
                        "payload": payload,
                    },
                )

            old_mission = "mission-old-binding"
            store.accept("Old delivery", mission_id=old_mission)
            store.bind(old_mission, "telegram", "42", "7")
            old_event = None
            for number in range(12):
                old_event, _ = store.append_central(
                    old_mission,
                    {
                        "schema_version": 1,
                        "mission_id": old_mission,
                        "type": "mission.stage",
                        "source": "central-hermes",
                        "correlation": {},
                        "payload": {"stage": "testing", "progress_percent": 50},
                    },
                )
            assert old_event is not None

            stale = store.pending_subscriptions(old_mission, old_event["sequence"])
            assert len(stale) == 1
            store.bind(new_mission, "telegram", "42", "7")
            pending_subscriptions = store.pending_subscriptions
            store.pending_subscriptions = lambda _mission, _sequence: stale
            stale_sends: list[str] = []

            async def sender(_target: dict, text: str) -> None:
                stale_sends.append(text)

            try:
                assert await missions.notify_subscribers(store, old_event, sender) == 0
            finally:
                store.pending_subscriptions = pending_subscriptions
            assert stale_sends == []

            pending = store.pending_subscriptions(new_mission, old_event["sequence"])
            assert len(pending) == 1 and pending[0]["last_notified_sequence"] == 0
            assert store.completion_notification(new_mission) is not None
            assert store.complete_if_ready(new_mission) is None

            store.bind(old_mission, "telegram", "43")
            leased = store.pending_subscriptions(old_mission, old_event["sequence"])[0]
            token = store.claim_notification(leased, old_event["sequence"])
            assert token is not None
            try:
                store.bind(new_mission, "telegram", "43")
                raise AssertionError("rebind bypassed an active notification lease")
            except missions.MissionError as error:
                assert "notification in progress" in str(error)
            assert store.bound_mission("telegram", "43") == old_mission
            assert store.finish_notification(
                leased, old_event["sequence"], token, delivered=False
            )
            store.bind(new_mission, "telegram", "43")
            assert store.bound_mission("telegram", "43") == new_mission

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
        assert store.completion_notification(mission_id) is None
        assert store.complete_if_ready(mission_id) is None

        store.bind(mission_id, "telegram", "42", "7")
        store.bind(mission_id, "telegram", "43", "8")
        notification = store.completion_notification(mission_id)
        assert notification is not None and notification["type"] == "mission.completed"
        subscription = store.pending_subscriptions(mission_id, notification["sequence"])[0]
        wrong_sequence_token = store.claim_notification(subscription, 1)
        assert wrong_sequence_token is not None
        assert not store.finish_notification(
            subscription,
            notification["sequence"],
            wrong_sequence_token,
            delivered=True,
        )
        assert store.complete_if_ready(mission_id) is None
        assert store.finish_notification(
            subscription, 1, wrong_sequence_token, delivered=False
        )

        async def failing_sender(_target: dict, _text: str) -> None:
            raise RuntimeError("simulated Telegram outage")

        try:
            asyncio.run(missions.notify_subscribers(store, notification, failing_sender))
            raise AssertionError("terminal notification failure was hidden")
        except RuntimeError as error:
            assert "Telegram outage" in str(error)
        assert store.complete_if_ready(mission_id) is None

        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        notification = store.completion_notification(mission_id)
        assert notification is not None
        expected_terminal_text = missions.telegram_text(
            missions.project([*store.events(mission_id), notification])
        )
        first_attempt: list[tuple[str, str]] = []

        async def partial_sender(target: dict, text: str) -> None:
            first_attempt.append((target["chat_id"], text))
            if target["chat_id"] == "43":
                raise RuntimeError("simulated partial Telegram outage")

        try:
            asyncio.run(missions.notify_subscribers(store, notification, partial_sender))
            raise AssertionError("partial terminal notification failure was hidden")
        except RuntimeError as error:
            assert "partial Telegram outage" in str(error)
        assert {chat_id for chat_id, _text in first_attempt} == {"42", "43"}
        assert all(text == expected_terminal_text for _chat_id, text in first_attempt)
        assert store.complete_if_ready(mission_id) is None

        retry: list[tuple[str, str]] = []

        async def retry_sender(target: dict, text: str) -> None:
            retry.append((target["chat_id"], text))

        assert asyncio.run(missions.notify_subscribers(store, notification, retry_sender)) == 1
        assert retry == [("43", expected_terminal_text)]
        completed = store.complete_if_ready(mission_id)
        assert completed is not None and completed[1]
        assert completed[0]["sequence"] == notification["sequence"]
        assert completed[0]["source"] == "central-hermes"
        assert completed[0]["type"] == "mission.completed"
        assert store.projection(mission_id)["status"] == "completed"
        assert asyncio.run(missions.notify_subscribers(store, completed[0], retry_sender)) == 0
        assert retry == [("43", expected_terminal_text)]
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
    assert not missions.completion_ready(view, telegram_terminal_ready=True)
    view.update(
        status="waiting_owner",
        workers=[{"worker_id": "worker-1", "status": "success"}],
    )
    assert not missions.completion_ready(view, telegram_terminal_ready=True)


def test_completion_ready_requires_telegram_terminal_checkpoint() -> None:
    view = missions.empty_projection()
    view.update(
        status="active",
        tasks=[{"task_id": "task-1", "status": "done"}],
        workers=[{"worker_id": "worker-1", "status": "success"}],
        gates=[
            {"gate_id": gate_id, "status": "passed"}
            for gate_id in missions._COMPLETION_GATES
        ],
        deliveries=[
            {"kind": kind, "status": status}
            for kind, status in missions._COMPLETION_DELIVERIES.items()
        ],
    )
    assert not missions.completion_ready(view)
    assert missions.completion_ready(view, telegram_terminal_ready=True)


def test_auto_failure_requires_one_cleaned_review_rejection() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = missions.MissionStore(pathlib.Path(directory) / "missions.sqlite3")
        mission_id = "mission-review-rejected"
        store.accept(
            "Fix issue 39",
            mission_id=mission_id,
            dispatch_profile="build1-vpnrouter-a7-3",
        )

        def publish(event_type: str, payload: dict, number: int) -> None:
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:reject:{number}"},
                    "payload": payload,
                },
            )

        publish(
            "task.upsert",
            {"task_id": "task-1", "title": "Root", "status": "done", "assignee": "coordinator"},
            1,
        )
        publish(
            "worker.upsert",
            {"worker_id": "task-1:run:1", "run_id": "1", "profile": "coordinator", "status": "completed"},
            2,
        )
        publish("gate.upsert", {"gate_id": "tests", "status": "passed"}, 3)
        publish("gate.upsert", {"gate_id": "review", "status": "failed"}, 4)
        assert store.complete_if_ready(mission_id) is None
        publish("gate.upsert", {"gate_id": "cleanup", "status": "passed"}, 5)

        failed = store.complete_if_ready(mission_id)
        assert failed is not None and failed[1]
        assert failed[0]["source"] == "central-hermes"
        assert failed[0]["type"] == "mission.failed"
        assert store.projection(mission_id)["status"] == "failed"
        assert store.complete_if_ready(mission_id) is None


def test_auto_failure_accepts_only_cleaned_exhausted_author_checks() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = missions.MissionStore(pathlib.Path(directory) / "missions.sqlite3")
        mission_id = "mission-author-checks-failed"
        store.accept(
            "Fix issue 39",
            mission_id=mission_id,
            dispatch_profile="build1-vpnrouter-a7-3",
        )

        def publish(event_type: str, payload: dict, number: int) -> None:
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:checks-failed:{number}"},
                    "payload": payload,
                },
            )

        publish(
            "task.upsert",
            {"task_id": "task-1", "title": "Root", "status": "done", "assignee": "coordinator"},
            1,
        )
        publish(
            "worker.upsert",
            {"worker_id": "task-1:run:1", "run_id": "1", "profile": "coordinator", "status": "completed"},
            2,
        )
        publish("gate.upsert", {"gate_id": "tests", "status": "failed"}, 3)
        assert store.complete_if_ready(mission_id) is None
        publish("gate.upsert", {"gate_id": "cleanup", "status": "passed"}, 4)

        failed = store.complete_if_ready(mission_id)
        assert failed is not None and failed[1]
        assert failed[0]["type"] == "mission.failed"
        assert failed[0]["payload"] == {
            "error": "Author checks failed after the approved cycle limit"
        }
        assert store.projection(mission_id)["status"] == "failed"


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
        store.bind(mission_id, "telegram", "42")
        notification = store.completion_notification(mission_id)
        assert notification is not None
        subscription = store.pending_subscriptions(mission_id, notification["sequence"])[0]
        token = store.claim_notification(subscription, notification["sequence"])
        assert token is not None
        assert store.finish_notification(
            subscription, notification["sequence"], token, delivered=True
        )

        readiness_entered = threading.Event()
        release_completion = threading.Event()
        regression_started = threading.Event()
        outcome: dict[str, object] = {}
        original = missions.completion_ready

        def observed(view: dict, *, telegram_terminal_ready: bool = False) -> bool:
            readiness_entered.set()
            assert release_completion.wait(5)
            return original(view, telegram_terminal_ready=telegram_terminal_ready)

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


def test_existing_subscription_table_gets_notification_lease_columns() -> None:
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "missions.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                """CREATE TABLE mission_subscriptions (
                       platform TEXT NOT NULL,
                       chat_id TEXT NOT NULL,
                       thread_id TEXT NOT NULL,
                       mission_id TEXT NOT NULL,
                       last_notified_sequence INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (platform, chat_id, thread_id)
                   )"""
            )
            connection.commit()
        finally:
            connection.close()
        missions.MissionStore(database)
        connection = sqlite3.connect(database)
        try:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(mission_subscriptions)")
            }
        finally:
            connection.close()
        assert {
            "notification_lease",
            "notification_lease_sequence",
            "notification_lease_until",
        } <= columns


def test_repair_mission_inherits_and_restores_telegram_binding() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        parent = "mission-parent"
        child = "mission-repair"
        store.accept(
            "Deliver change", mission_id=parent, dispatch_profile="build1-parent"
        )
        store.bind(parent, "telegram", "42", "7")
        accepted, created = store.accept(
            "Repair post-verify",
            mission_id=child,
            dispatch_profile="build1-repair",
            parent_mission_id=parent,
        )
        assert created and accepted["payload"]["parent_mission_id"] == parent
        assert store.projection(child)["parent_mission_id"] == parent
        assert store.bound_mission("telegram", "42", "7") == child
        assert not store.accept(
            "Repair post-verify",
            mission_id=child,
            dispatch_profile="build1-repair",
            parent_mission_id=parent,
        )[1]

        events = [
            ("task.upsert", {"task_id": "task-1", "title": "Repair", "status": "done"}),
            ("worker.upsert", {"worker_id": "worker-1", "status": "success"}),
            *(("gate.upsert", {"gate_id": gate, "status": "passed"})
              for gate in missions._COMPLETION_GATES),
            ("delivery.upsert", {"kind": "pull_request", "status": "merged", "url": "https://example.invalid/pr/2"}),
            ("delivery.upsert", {"kind": "default_branch", "status": "verified", "url": "https://example.invalid/commit/2"}),
        ]
        for number, (event_type, payload) in enumerate(events, 1):
            store.append_producer(
                child,
                {
                    "schema_version": 1,
                    "mission_id": child,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:repair:{number}"},
                    "payload": payload,
                },
            )
        notification = store.completion_notification(child)
        assert notification is not None
        subscription = store.pending_subscriptions(child, notification["sequence"])[0]
        token = store.claim_notification(subscription, notification["sequence"])
        assert token and store.finish_notification(
            subscription, notification["sequence"], token, delivered=True
        )
        completed = store.complete_if_ready(child)
        assert completed is not None and completed[0]["type"] == "mission.completed"
        assert store.bound_mission("telegram", "42", "7") == parent
        assert [item["reason"] for item in store.binding_history()] == [
            "manual-bind", "repair-inherit", "repair-restore"
        ]
        assert not store.accept(
            "Repair post-verify",
            mission_id=child,
            dispatch_profile="build1-repair",
            parent_mission_id=parent,
        )[1]
        assert store.bound_mission("telegram", "42", "7") == parent


def test_terminal_failure_contracts_include_preserved_pr_ci_and_post_verify() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")

        def fail(mission_id: str, gates: list[tuple[str, str]], delivery: str) -> dict:
            store.accept("Deliver", mission_id=mission_id)
            events = [
                ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
                ("worker.upsert", {"worker_id": "worker-1", "status": "completed"}),
                *(("gate.upsert", {"gate_id": gate, "status": status}) for gate, status in gates),
                ("delivery.upsert", {"kind": "pull_request", "status": delivery, "url": "https://example.invalid/pr/1"}),
            ]
            for number, (event_type, payload) in enumerate(events, 1):
                store.append_producer(
                    mission_id,
                    {
                        "schema_version": 1,
                        "mission_id": mission_id,
                        "type": event_type,
                        "source": "build1-flow",
                        "correlation": {"producer_event_id": f"flow:{mission_id}:{number}"},
                        "payload": payload,
                    },
                )
            terminal = store.complete_if_ready(mission_id)
            assert terminal is not None
            return terminal[0]

        review = fail(
            "mission-review-failed-after-pr",
            [("tests", "passed"), ("review", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert review["payload"]["error"] == "Independent review rejected the candidate"
        author_checks = fail(
            "mission-author-checks-failed-after-pr",
            [("tests", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert author_checks["payload"]["error"] == (
            "Author checks failed after the approved cycle limit"
        )
        ci = fail(
            "mission-ci-failed",
            [("tests", "passed"), ("review", "passed"), ("ci", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert ci["payload"]["error"] == "Required CI failed after the approved cycle limit"
        post_verify = fail(
            "mission-post-verify-failed",
            [
                ("tests", "passed"), ("review", "passed"), ("ci", "passed"),
                ("post-verify", "failed"), ("cleanup", "passed"),
            ],
            "merged",
        )
        assert post_verify["payload"]["error"] == (
            "Post-verify failed after the approved repair mission"
        )


def test_failure_terminal_waits_for_telegram_checkpoint_and_retries() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            mission_id = "mission-review-failed-with-telegram"
            store.accept("Deliver", mission_id=mission_id)
            store.bind(mission_id, "telegram", "42")
            events = [
                ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
                ("worker.upsert", {"worker_id": "worker-1", "status": "completed"}),
                ("gate.upsert", {"gate_id": "tests", "status": "passed"}),
                ("gate.upsert", {"gate_id": "review", "status": "failed"}),
                ("delivery.upsert", {
                    "kind": "pull_request", "status": "failed",
                    "url": "https://example.invalid/pr/1",
                }),
                ("gate.upsert", {"gate_id": "cleanup", "status": "passed"}),
            ]
            for number, (event_type, payload) in enumerate(events, 1):
                store.append_producer(
                    mission_id,
                    {
                        "schema_version": 1,
                        "mission_id": mission_id,
                        "type": event_type,
                        "source": "build1-flow",
                        "correlation": {"producer_event_id": f"flow:telegram-failure:{number}"},
                        "payload": payload,
                    },
                )

            assert store.complete_if_ready(mission_id) is None
            notification = store.completion_notification(mission_id)
            assert notification is not None and notification["type"] == "mission.failed"

            async def fail_once(_subscription: dict, _text: str) -> None:
                raise RuntimeError("telegram unavailable")

            try:
                await missions.notify_subscribers(store, notification, fail_once)
                raise AssertionError("failed Telegram delivery was accepted")
            except RuntimeError as error:
                assert str(error) == "telegram unavailable"
            assert store.complete_if_ready(mission_id) is None
            assert store.projection(mission_id)["status"] == "active"

            delivered: list[str] = []

            async def send(_subscription: dict, text: str) -> None:
                delivered.append(text)

            assert await missions.notify_subscribers(store, notification, send) == 1
            assert delivered and "failed" in delivered[0].lower()
            terminal = store.complete_if_ready(mission_id)
            assert terminal is not None and terminal[0]["type"] == "mission.failed"
            assert store.pending_subscriptions(mission_id, terminal[0]["sequence"]) == []

    asyncio.run(scenario())


def main() -> None:
    test_reconnect_projects_one_canonical_state()
    test_producer_retry_and_notification_checkpoint_are_idempotent()
    test_notification_can_repeat_after_delivery_before_checkpoint()
    test_notification_checkpoint_cannot_cross_a_mission_rebind()
    test_producer_cannot_end_mission_or_decrease_progress()
    test_dispatch_profile_is_projected_and_immutable()
    test_dispatch_candidates_do_not_starve_behind_newer_missions()
    test_producer_schema_is_closed_and_all_strings_are_redacted()
    test_terminal_authority_is_loopback_only()
    test_central_auto_completion_requires_the_full_delivery_contract()
    test_auto_completion_rejects_multiple_workers()
    test_completion_ready_requires_telegram_terminal_checkpoint()
    test_auto_completion_snapshot_and_terminal_insert_are_one_transaction()
    test_unresolved_question_survives_stage_and_blocks_auto_completion()
    test_mission_database_is_owner_only_on_posix()
    test_existing_subscription_table_gets_notification_lease_columns()
    test_repair_mission_inherits_and_restores_telegram_binding()
    test_terminal_failure_contracts_include_preserved_pr_ci_and_post_verify()
    test_failure_terminal_waits_for_telegram_checkpoint_and_retries()
    print("hermes mission runtime checks passed")


if __name__ == "__main__":
    main()
