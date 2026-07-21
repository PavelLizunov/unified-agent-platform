"""Hermetic A6.3 gate for the central mission log and both projections."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import tempfile
import threading
from pathlib import Path
from unittest import mock


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


def test_research_only_goal_bypasses_coding_mission_intake() -> None:
    assert missions.is_controlled_research_goal(
        "Look up the latest Codex web search documentation"
    )
    assert missions.is_controlled_research_goal(
        "Поищи актуальную документацию Brave Search API"
    )
    assert not missions.is_controlled_research_goal(
        "Research the API, implement the integration, and open a PR"
    )
    assert not missions.is_controlled_research_goal("Fix the search component test")
    assert not missions.is_controlled_research_goal(None)


def test_project_onboarding_is_idempotent_restart_safe_and_forward_only() -> None:
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": ""}
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        requested, created = store.request_project_onboarding(
            "mac-ledger", "Dependency-free ledger for macOS", "rust"
        )
        assert created
        assert requested["repository"] == "PavelLizunov/mac-ledger"
        assert requested["project_id"] == "mac-ledger"
        assert requested["checkpoint"] == "requested"
        assert requested["invocations"] is None
        assert requested["progress_percent"] == 0
        assert requested["error_code"] is None

        restarted = missions.MissionStore(database)
        replayed, replay_created = restarted.request_project_onboarding(
            "mac-ledger", "Dependency-free ledger for macOS", "rust"
        )
        assert not replay_created and replayed == requested
        assert restarted.pending_project_onboarding() == requested

        first_invocation = {
            "unit": "hermes-project-onboarding.service",
            "invocation_id": "1" * 32,
        }
        invoked, recorded = restarted.record_project_onboarding_invocation(
            requested["request_id"], first_invocation
        )
        assert recorded and invoked["invocations"]["count"] == 1
        replayed_invocation, recorded = missions.MissionStore(
            database
        ).record_project_onboarding_invocation(
            requested["request_id"], first_invocation
        )
        assert not recorded and replayed_invocation == invoked
        second_invocation = {
            "unit": "hermes-project-onboarding.service",
            "invocation_id": "2" * 32,
        }
        invoked, recorded = missions.MissionStore(
            database
        ).record_project_onboarding_invocation(
            requested["request_id"], second_invocation
        )
        assert recorded
        assert invoked["invocations"]["count"] == 2
        assert invoked["invocations"]["first"] == first_invocation
        assert invoked["invocations"]["last"] == second_invocation

        try:
            restarted.request_project_onboarding(
                "mac-ledger", "Different payload", "rust"
            )
            raise AssertionError("onboarding idempotency collision was accepted")
        except missions.MissionError as error:
            assert "collision" in str(error)

        repository_ready, advanced = restarted.advance_project_onboarding(
            requested["request_id"], "requested", "repository_ready"
        )
        assert advanced and repository_ready["progress_percent"] == 25
        replayed_transition, replay_advanced = restarted.advance_project_onboarding(
            requested["request_id"], "requested", "repository_ready"
        )
        assert not replay_advanced and replayed_transition == repository_ready
        try:
            restarted.advance_project_onboarding(
                requested["request_id"], "repository_ready", "canary_passed"
            )
            raise AssertionError("onboarding checkpoint skip was accepted")
        except missions.MissionError as error:
            assert "forward-only" in str(error)

        current = repository_ready
        for expected, checkpoint in (
            ("repository_ready", "runtime_ready"),
            ("runtime_ready", "canary_passed"),
            ("canary_passed", "ready"),
        ):
            current, advanced = missions.MissionStore(database).advance_project_onboarding(
                requested["request_id"], expected, checkpoint
            )
            assert advanced
        assert current["checkpoint"] == "ready"
        assert current["progress_percent"] == 100
        assert missions.MissionStore(database).pending_project_onboarding() is None
        try:
            restarted.record_project_onboarding_invocation(
                requested["request_id"], second_invocation
            )
            raise AssertionError("terminal onboarding accepted an invocation")
        except missions.MissionError as error:
            assert "terminal" in str(error)

        failed_request, _ = restarted.request_project_onboarding(
            "failed-project", "Expected failure path", "python"
        )
        failed, advanced = restarted.advance_project_onboarding(
            failed_request["request_id"], "requested", "failed",
            error_code="github-capability-missing",
        )
        assert advanced
        assert failed["checkpoint"] == "failed"
        assert failed["error_code"] == "github-capability-missing"
        assert restarted.pending_project_onboarding() is None

        for name, preset in (("bad/name", "rust"), ("valid-name", "custom")):
            try:
                restarted.request_project_onboarding(name, "description", preset)
                raise AssertionError("invalid onboarding request was accepted")
            except missions.MissionError:
                pass


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
        assert "Автоматические проверки · 60%" not in missions.telegram_text(telegram_view)
        assert "Этап: Готово · 100%" in missions.telegram_text(telegram_view)
        assert "Статус: завершено" in missions.telegram_text(telegram_view)
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
            assert "Этап: Автоматические проверки · 60%" in deliveries[0][1]
            assert "Статус: в работе" in deliveries[0][1]
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
            assert "Ошибка: Delivery failed" in deliveries[-1][1]

    asyncio.run(scenario())


def test_capacity_notice_projects_to_workspace_and_telegram_without_owner_gate() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            store.accept("Deliver the change", mission_id="mission-capacity")
            store.bind("mission-capacity", "telegram", "42", "7")
            notice = {
                "schema_version": 1,
                "mission_id": "mission-capacity",
                "type": "mission.notice",
                "source": "build1-flow",
                "correlation": {
                    "task_id": "task-1",
                    "producer_event_id": "flow:mission-capacity:wait-1",
                },
                "payload": {
                    "code": "capacity_wait",
                    "message": "OpenAI capacity: automatic author retry scheduled.",
                    "owner_action_required": False,
                    "next_attempt_at": "2026-07-18T18:00:00Z",
                },
            }
            stored, created = store.append_producer("mission-capacity", notice)
            assert created
            view = store.projection("mission-capacity")
            assert view["status"] == "active"
            assert view["progress_percent"] == 0
            assert view["question"] is None
            assert view["notice"] == notice["payload"]
            rendered = missions.telegram_text(view)
            assert "Следующая автоматическая попытка (UTC): 2026-07-18T18:00:00Z" in rendered
            assert "От вас ничего не требуется." in rendered

            deliveries: list[str] = []

            async def sender(_target: dict, text: str) -> None:
                deliveries.append(text)

            assert await missions.notify_subscribers(store, stored, sender) == 1
            assert deliveries == [rendered]

            reconciling = {
                **notice,
                "correlation": {
                    **notice["correlation"],
                    "producer_event_id": "flow:mission-capacity:reconciling",
                },
                "payload": {
                    "code": "execution_reconciling",
                    "message": "Interrupted author execution is being reconciled automatically.",
                    "owner_action_required": False,
                },
            }
            store.append_producer("mission-capacity", reconciling)
            view = store.projection("mission-capacity")
            assert view["status"] == "active"
            assert view["question"] is None
            assert view["notice"] == reconciling["payload"]
            assert "От вас ничего не требуется." in missions.telegram_text(view)

            invalid = {
                **notice,
                "correlation": {
                    **notice["correlation"],
                    "producer_event_id": "flow:mission-capacity:invalid",
                },
                "payload": {**notice["payload"], "owner_action_required": "no"},
            }
            try:
                store.append_producer("mission-capacity", invalid)
                raise AssertionError("string owner action flag was accepted")
            except missions.MissionError as error:
                assert "owner_action_required" in str(error)

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
            terminal = store.complete_if_ready(new_mission)
            assert terminal is not None
            assert store.completion_notification(new_mission) == terminal[0]

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
            delivery_mode="none",
        )
        assert created
        assert accepted["payload"]["dispatch_profile"] == "build1-uap"
        assert accepted["payload"]["delivery_mode"] == "none"
        assert store.projection("mission-dispatch")["dispatch_profile"] == "build1-uap"
        assert store.projection("mission-dispatch")["delivery_mode"] == "none"
        replayed, replay_created = store.accept(
            "Safe mission",
            mission_id="mission-dispatch",
            dispatch_profile="build1-uap",
            delivery_mode="none",
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
        try:
            store.accept(
                "Safe mission",
                mission_id="mission-dispatch",
                dispatch_profile="build1-uap",
            )
            raise AssertionError("delivery mode changed after acceptance")
        except missions.MissionError as error:
            assert "different parameters" in str(error)


def test_registered_owner_intake_is_deterministic_and_fail_closed() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
        "telegram": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        accepted, created = store.ingest_owner_goal(
            "Deliver the registered change",
            platform="workspace",
            source_message_id="4f1d8ea8-2d27-4b50-a351-f04272f5ea70",
            session_id="session-owner",
        )
        assert created
        assert accepted["mission_id"].startswith("mission-intake-")
        assert accepted["payload"]["dispatch_profile"] == "build1-registered"
        assert accepted["payload"]["delivery_mode"] == "none"
        workspace_source_key = missions._json({
            "platform": "workspace",
            "session_id": "session-owner",
            "chat_id": "",
            "thread_id": "",
            "source_message_id": "4f1d8ea8-2d27-4b50-a351-f04272f5ea70",
        })
        workspace_source_sha256 = hashlib.sha256(
            workspace_source_key.encode("utf-8")
        ).hexdigest()
        assert accepted["mission_id"] == (
            "mission-intake-" + workspace_source_sha256[:32]
        )
        assert accepted["payload"]["input_platform"] == "workspace"
        assert accepted["payload"]["input_source_key_sha256"] == (
            workspace_source_sha256
        )
        assert accepted["payload"]["input_source_message_sha256"] == (
            hashlib.sha256(
                b"4f1d8ea8-2d27-4b50-a351-f04272f5ea70"
            ).hexdigest()
        )
        projection = store.projection(accepted["mission_id"])
        assert projection["input_platform"] == "workspace"
        assert projection["input_source_key_sha256"] == workspace_source_sha256

        restarted = missions.MissionStore(database)
        replayed, replay_created = restarted.ingest_owner_goal(
            "Deliver the registered change",
            platform="workspace",
            source_message_id="4f1d8ea8-2d27-4b50-a351-f04272f5ea70",
            session_id="session-owner",
        )
        assert not replay_created and replayed == accepted
        assert len(restarted.events(accepted["mission_id"])) == 1

        try:
            restarted.ingest_owner_goal(
                "Changed payload for the same owner turn",
                platform="workspace",
                source_message_id="4f1d8ea8-2d27-4b50-a351-f04272f5ea70",
                session_id="session-owner",
            )
            raise AssertionError("owner intake idempotency collision was accepted")
        except missions.MissionError as error:
            assert "different parameters" in str(error)

        telegram, telegram_created = restarted.ingest_owner_goal(
            "Deliver from Telegram",
            platform="telegram",
            source_message_id="telegram-message-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert telegram_created
        assert restarted.bound_mission(
            "telegram", "owner-chat", "owner-thread"
        ) == telegram["mission_id"]
        assert restarted.binding_history()[-1]["reason"] == "owner-intake"
        replayed_telegram, replayed_telegram_created = restarted.ingest_owner_goal(
            "Deliver from Telegram",
            platform="telegram",
            source_message_id="telegram-message-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert not replayed_telegram_created and replayed_telegram == telegram
        assert len(restarted.binding_history()) == 1
        assert telegram["payload"]["input_platform"] == "telegram"
        assert telegram["payload"]["input_source_message_sha256"] == (
            hashlib.sha256(b"telegram-message-1").hexdigest()
        )

        later_telegram, later_created = restarted.ingest_owner_goal(
            "Deliver the next Telegram goal",
            platform="telegram",
            source_message_id="telegram-message-2",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert later_created
        assert restarted.bound_mission(
            "telegram", "owner-chat", "owner-thread"
        ) == later_telegram["mission_id"]
        restarted.ingest_owner_goal(
            "Deliver from Telegram",
            platform="telegram",
            source_message_id="telegram-message-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert restarted.bound_mission(
            "telegram", "owner-chat", "owner-thread"
        ) == later_telegram["mission_id"]
        assert len(restarted.binding_history()) == 2

        legacy_source_key = missions._json({
            "platform": "workspace",
            "session_id": "legacy-session",
            "chat_id": "",
            "thread_id": "",
            "source_message_id": "legacy-message",
        })
        legacy_source_sha256 = hashlib.sha256(
            legacy_source_key.encode("utf-8")
        ).hexdigest()
        legacy_id = "mission-intake-" + legacy_source_sha256[:32]
        legacy, legacy_created = restarted.accept(
            "Replay a pre-lineage ordinary goal",
            mission_id=legacy_id,
            session_id="legacy-session",
            dispatch_profile="build1-registered",
            delivery_mode="none",
        )
        assert legacy_created
        legacy_replay, legacy_replay_created = restarted.ingest_owner_goal(
            "Replay a pre-lineage ordinary goal",
            platform="workspace",
            source_message_id="legacy-message",
            session_id="legacy-session",
        )
        assert not legacy_replay_created and legacy_replay == legacy

        try:
            restarted.accept(
                "Forged input lineage",
                mission_id="mission-intake-" + "0" * 32,
                dispatch_profile="build1-registered",
                delivery_mode="none",
                input_platform="workspace",
                input_source_key_sha256="1" * 64,
                input_source_message_sha256="2" * 64,
            )
            raise AssertionError("mismatched input lineage was accepted")
        except missions.MissionError as error:
            assert "input lineage" in str(error)

        before = len(restarted.list(100))
        try:
            restarted.ingest_owner_goal(
                "Unknown channel",
                platform="signal",
                source_message_id="message-unknown",
                chat_id="owner-chat",
            )
            raise AssertionError("unknown owner channel was accepted")
        except missions.MissionError as error:
            assert "no registered delivery route" in str(error)
        assert len(restarted.list(100)) == before

        for malformed in (
            None,
            "[]",
            "{}",
            '{"workspace":true}',
            '{"workspace":{"dispatch_profile":"first"}}',
            '{"workspace":{"dispatch_profile":"first","delivery_mode":"deploy"}}',
            '{"workspace":{"dispatch_profile":"first","delivery_mode":"none","model":"sol"}}',
            '{"workspace":"first","workspace":"second"}',
            '{"workspace":"first"," workspace ":"second"}',
        ):
            environment = (
                {} if malformed is None
                else {"HERMES_MISSION_INTAKE_ROUTES": malformed}
            )
            with mock.patch.dict(os.environ, environment, clear=True):
                try:
                    restarted.ingest_owner_goal(
                        "Malformed registry",
                        platform="workspace",
                        source_message_id="message-malformed",
                        session_id="session-owner",
                    )
                    raise AssertionError("malformed owner intake registry was accepted")
                except missions.MissionError:
                    pass
            assert len(restarted.list(100)) == before

        invalid_owner_values = (
            {
                "goal": 1,
                "platform": "workspace",
                "source_message_id": "message-bad-goal",
                "session_id": "session-owner",
            },
            {
                "goal": "Bad platform",
                "platform": True,
                "source_message_id": "message-bad-platform",
                "session_id": "session-owner",
            },
            {
                "goal": "Bad message",
                "platform": "workspace",
                "source_message_id": 1,
                "session_id": "session-owner",
            },
            {
                "goal": "Bad session",
                "platform": "workspace",
                "source_message_id": "message-bad-session",
                "session_id": {"id": "owner"},
            },
            {
                "goal": "Bad chat",
                "platform": "workspace",
                "source_message_id": "message-bad-chat",
                "chat_id": True,
            },
            {
                "goal": "Bad thread",
                "platform": "workspace",
                "source_message_id": "message-bad-thread",
                "chat_id": "owner-chat",
                "thread_id": [],
            },
        )
        for arguments in invalid_owner_values:
            try:
                restarted.ingest_owner_goal(**arguments)
                raise AssertionError("non-string owner intake value was accepted")
            except missions.MissionError:
                pass
            assert len(restarted.list(100)) == before


def test_registered_project_selection_is_durable_and_restart_safe() -> None:
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnctl",
                "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl",
                "summary": "Rust VPN control plane",
                "aliases": ["vpn ctl", "впн контроллер"],
                "dispatch_profile": "build1-vpnctl-registered-v4",
                "delivery_mode": "none",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnrouter",
                "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter",
                "summary": "Windows VPN router",
                "aliases": ["vpn router", "впн роутер"],
                "dispatch_profile": "build1-vpnrouter-registered-v4",
                "delivery_mode": "none",
                "platforms": ["workspace", "telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        public = missions.public_intake_projects("workspace")
        assert [item["project_id"] for item in public] == ["vpnctl", "vpnrouter"]
        assert all("dispatch_profile" not in item for item in public)

        accepted, created = store.ingest_owner_turn(
            "Add a deterministic status command",
            platform="workspace",
            project_id="vpnctl",
            source_message_id="workspace-project-goal",
            session_id="workspace-project-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "vpnctl"
        assert accepted["payload"]["dispatch_profile"] == "build1-vpnctl-registered-v4"
        assert store.projection(accepted["mission_id"])["project_id"] == "vpnctl"

        try:
            store.ingest_owner_turn(
                "Improve status reporting",
                platform="telegram",
                source_message_id="telegram-project-goal",
                session_id="telegram-project-session",
                chat_id="owner-project-chat",
            )
            raise AssertionError("ambiguous Telegram goal was accepted")
        except missions.MissionProjectRequired as error:
            assert len(error.projects) == 2
        assert len(store.list(100)) == 1

        restarted = missions.MissionStore(database)
        try:
            restarted.ingest_owner_turn(
                "Improve status reporting",
                platform="telegram",
                source_message_id="telegram-project-goal",
                session_id="telegram-project-session",
                chat_id="owner-project-chat",
            )
            raise AssertionError("replayed ambiguous goal was accepted")
        except missions.MissionProjectRequired:
            pass

        selected, selected_created = restarted.ingest_owner_turn(
            "vpnctl",
            platform="telegram",
            source_message_id="telegram-project-selection",
            session_id="telegram-project-session",
            chat_id="owner-project-chat",
        )
        assert selected_created
        assert selected["payload"]["goal"] == "Improve status reporting"
        assert selected["payload"]["project_id"] == "vpnctl"
        selection_replay, replay_created = missions.MissionStore(database).ingest_owner_turn(
            "vpnctl",
            platform="telegram",
            source_message_id="telegram-project-selection",
            session_id="telegram-project-session",
            chat_id="owner-project-chat",
        )
        assert not replay_created and selection_replay == selected

        later, later_created = restarted.ingest_owner_turn(
            "VPNRouter: add one regression test",
            platform="telegram",
            source_message_id="telegram-next-goal",
            session_id="telegram-project-session",
            chat_id="owner-project-chat",
        )
        assert later_created and later["payload"]["project_id"] == "vpnrouter"
        delayed_selection_replay, delayed_created = restarted.ingest_owner_turn(
            "vpnctl",
            platform="telegram",
            source_message_id="telegram-project-selection",
            session_id="telegram-project-session",
            chat_id="owner-project-chat",
        )
        assert not delayed_created and delayed_selection_replay == selected
        assert len(restarted.list(100)) == 3

        try:
            store.ingest_owner_turn(
                "Add a deterministic status command",
                platform="workspace",
                project_id="vpnrouter",
                source_message_id="workspace-project-goal",
                session_id="workspace-project-session",
            )
            raise AssertionError("changed project replay was accepted")
        except missions.MissionError as error:
            assert "different parameters" in str(error)

        malformed = json.dumps({
            "schema_version": 1,
            "projects": [
                {
                    "project_id": "one", "label": "One", "repository": "owner/one",
                    "summary": "One", "aliases": ["same"], "dispatch_profile": "one",
                    "delivery_mode": "none", "platforms": ["workspace"],
                },
                {
                    "project_id": "two", "label": "Two", "repository": "owner/two",
                    "summary": "Two", "aliases": ["same"], "dispatch_profile": "two",
                    "delivery_mode": "none", "platforms": ["workspace"],
                },
            ],
        })
        with mock.patch.dict(
            os.environ, {"HERMES_MISSION_PROJECTS": malformed}, clear=True
        ):
            try:
                missions.registered_intake_projects("workspace")
                raise AssertionError("ambiguous catalog alias was accepted")
            except missions.MissionError as error:
                assert "ambiguous project alias" in str(error)


def test_telegram_project_selection_draft_can_be_cancelled_and_replayed() -> None:
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        try:
            store.ingest_owner_turn(
                "отмена", platform="telegram", source_message_id="cancel-empty",
                session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("cancellation without a draft was accepted")
        except missions.MissionError as error:
            assert str(error) == "нет ожидающего выбора проекта"
        assert store.list(100) == []

        try:
            store.ingest_owner_turn(
                "Добавь краткий статус", platform="telegram",
                source_message_id="goal-1", session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("ambiguous goal was accepted")
        except missions.MissionProjectRequired:
            pass

        for current in (store, missions.MissionStore(database)):
            try:
                current.ingest_owner_turn(
                    "/cancel", platform="telegram", source_message_id="cancel-1",
                    session_id="session-1", chat_id="chat-1",
                )
                raise AssertionError("cancelled draft returned a mission event")
            except missions.MissionIntakeCancelled:
                pass
        assert store.list(100) == []

        try:
            store.ingest_owner_turn(
                "vpnctl", platform="telegram", source_message_id="cancel-1",
                session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("changed cancellation replay was accepted")
        except missions.MissionError as error:
            assert "idempotency collision" in str(error)

        try:
            store.ingest_owner_turn(
                "Добавь краткий статус", platform="telegram",
                source_message_id="goal-2", session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("second ambiguous goal was accepted")
        except missions.MissionProjectRequired:
            pass
        accepted, created = store.ingest_owner_turn(
            "vpnctl", platform="telegram", source_message_id="selection-2",
            session_id="session-1", chat_id="chat-1",
        )
        assert created and accepted["payload"]["project_id"] == "vpnctl"


def test_telegram_project_selection_and_cancel_are_serialized() -> None:
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        try:
            store.ingest_owner_turn(
                "Добавь краткий статус", platform="telegram",
                source_message_id="goal-1", session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("ambiguous goal was accepted")
        except missions.MissionProjectRequired:
            pass

        selection_started = threading.Event()
        release_selection = threading.Event()
        original_ingest = store.ingest_owner_goal

        def delayed_ingest(*args, **kwargs):
            selection_started.set()
            assert release_selection.wait(5)
            return original_ingest(*args, **kwargs)

        outcome: dict[str, object] = {}

        def select_project() -> None:
            try:
                outcome["selected"] = store.ingest_owner_turn(
                    "vpnctl", platform="telegram", source_message_id="selection-1",
                    session_id="session-1", chat_id="chat-1",
                )
            except BaseException as error:
                outcome["selection_error"] = error

        with mock.patch.object(store, "ingest_owner_goal", delayed_ingest):
            selector = threading.Thread(target=select_project)
            selector.start()
            assert selection_started.wait(5)
            try:
                store.ingest_owner_turn(
                    "/cancel", platform="telegram", source_message_id="cancel-1",
                    session_id="session-1", chat_id="chat-1",
                )
                raise AssertionError("in-flight project selection was cancelled")
            except missions.MissionError as error:
                assert "завершён" in str(error)
            finally:
                release_selection.set()
            selector.join(5)

        assert not selector.is_alive()
        assert "selection_error" not in outcome
        selected, created = outcome["selected"]
        assert created and selected["payload"]["project_id"] == "vpnctl"
        assert len(store.list(100)) == 1


def test_telegram_project_selection_claim_resumes_after_crash() -> None:
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        try:
            store.ingest_owner_turn(
                "Добавь краткий статус", platform="telegram",
                source_message_id="goal-1", session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("ambiguous goal was accepted")
        except missions.MissionProjectRequired:
            pass

        with mock.patch.object(
            store, "ingest_owner_goal", side_effect=RuntimeError("injected crash")
        ):
            try:
                store.ingest_owner_turn(
                    "vpnctl", platform="telegram", source_message_id="selection-1",
                    session_id="session-1", chat_id="chat-1",
                )
                raise AssertionError("crashing selection returned")
            except RuntimeError as error:
                assert str(error) == "injected crash"

        restarted = missions.MissionStore(database)
        try:
            restarted.ingest_owner_turn(
                "vpnrouter", platform="telegram", source_message_id="selection-2",
                session_id="session-1", chat_id="chat-1",
            )
            raise AssertionError("a competing selection replaced the durable claim")
        except missions.MissionError as error:
            assert "уже выполняется" in str(error)

        accepted, created = restarted.ingest_owner_turn(
            "vpnctl", platform="telegram", source_message_id="selection-1",
            session_id="session-1", chat_id="chat-1",
        )
        assert created and accepted["payload"]["project_id"] == "vpnctl"
        replay, replay_created = missions.MissionStore(database).ingest_owner_turn(
            "vpnctl", platform="telegram", source_message_id="selection-1",
            session_id="session-1", chat_id="chat-1",
        )
        assert not replay_created and replay == accepted
        assert len(restarted.list(100)) == 1


def test_project_inventory_exposes_all_repositories_but_dispatches_only_ready() -> None:
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "ready", "label": "Ready", "repository": "owner/ready",
                "summary": "Ready project", "aliases": ["готов"],
                "dispatch_profile": "build1-ready", "delivery_mode": "none",
                "platforms": ["workspace", "telegram"], "category": "pilot",
                "status": "ready", "test_targets": ["uap-build-1", "github-linux"],
            },
            {
                "project_id": "later", "label": "Later", "repository": "owner/later",
                "summary": "Known but not executable", "aliases": ["позже"],
                "dispatch_profile": None, "delivery_mode": "none",
                "platforms": ["workspace", "telegram"], "category": "research",
                "status": "setup_required", "test_targets": ["windows-brat"],
            },
            {
                "project_id": "old", "label": "Old", "repository": "owner/old",
                "summary": "Archived project", "aliases": ["старый"],
                "dispatch_profile": None, "delivery_mode": "none",
                "platforms": ["workspace", "telegram"], "category": "archived",
                "status": "archived", "test_targets": [],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        public = missions.public_intake_projects("workspace")
        assert [project["project_id"] for project in public] == ["ready", "later", "old"]
        assert public[0]["test_targets"] == ["uap-build-1", "github-linux"]
        assert public[1]["status"] == "setup_required"
        assert all("dispatch_profile" not in project for project in public)

        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        try:
            store.ingest_owner_turn(
                "Сделай изменение",
                platform="workspace",
                source_message_id="inventory-ambiguous",
                session_id="inventory-session",
            )
            raise AssertionError("inventory without a selected ready project was accepted")
        except missions.MissionProjectRequired as error:
            assert [project["project_id"] for project in error.projects] == ["ready"]

        try:
            store.ingest_owner_turn(
                "Later: сделай изменение",
                platform="workspace",
                project_id="later",
                source_message_id="inventory-unavailable",
                session_id="inventory-session",
            )
            raise AssertionError("project without a reviewed profile was accepted")
        except missions.MissionProjectUnavailable as error:
            assert "пока нельзя выполнять автоматически" in str(error)
        assert store.list(100) == []

        accepted, created = store.ingest_owner_turn(
            "Ready: сделай изменение",
            platform="workspace",
            project_id="ready",
            source_message_id="inventory-ready",
            session_id="inventory-session",
        )
        assert created and accepted["payload"]["dispatch_profile"] == "build1-ready"


def test_bound_ordinary_owner_turn_answers_once_and_survives_restart() -> None:
    routes = json.dumps({
        "telegram": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        accepted, created = store.ingest_owner_turn(
            "Deliver from Telegram",
            platform="telegram",
            source_message_id="telegram-goal-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert created
        mission_id = accepted["mission_id"]
        store.append_producer(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:question:1"},
                "payload": {
                    "question_id": "question-1",
                    "text": "Preserve the current behavior?",
                },
            },
        )

        answer, answer_created = store.ingest_owner_turn(
            "Yes, preserve it",
            platform="telegram",
            source_message_id="telegram-answer-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert answer_created and answer["type"] == "mission.answer"
        assert answer["mission_id"] == mission_id
        assert answer["payload"] == {
            "question_id": "question-1",
            "source_message_id": "telegram-answer-1",
            "source_platform": "telegram",
            "text": "Yes, preserve it",
        }
        behind = store.channel_evidence(mission_id)
        assert behind["workspace"] == {
            "cursor": answer["sequence"],
            "projection_id": store.projection(mission_id)["projection_id"],
        }
        assert behind["telegram"] == {
            "subscriber_count": 1,
            "cursor": 0,
            "projection_id": None,
        }
        subscription = store.pending_subscriptions(mission_id, answer["sequence"])[0]
        token = store.claim_notification(subscription, answer["sequence"])
        assert token
        store.finish_notification(
            subscription, answer["sequence"], token, delivered=True
        )
        converged = store.channel_evidence(mission_id)
        assert converged["telegram"] == {
            "subscriber_count": 1,
            "cursor": answer["sequence"],
            "projection_id": converged["workspace"]["projection_id"],
        }
        assert store.projection(mission_id)["status"] == "active"
        assert len(store.list(100)) == 1

        restarted = missions.MissionStore(database)
        replay, replay_created = restarted.ingest_owner_turn(
            "Yes, preserve it",
            platform="telegram",
            source_message_id="telegram-answer-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert not replay_created and replay == answer
        assert len(restarted.list(100)) == 1
        try:
            restarted.ingest_owner_turn(
                "No, change it",
                platform="telegram",
                source_message_id="telegram-answer-1",
                session_id="session-telegram",
                chat_id="owner-chat",
                thread_id="owner-thread",
            )
            raise AssertionError("changed replayed owner answer was accepted")
        except missions.MissionError as error:
            assert "owner turn idempotency collision" in str(error)

        next_goal, next_created = restarted.ingest_owner_turn(
            "Deliver the next Telegram goal",
            platform="telegram",
            source_message_id="telegram-goal-2",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert next_created and next_goal["mission_id"] != mission_id
        assert restarted.bound_mission(
            "telegram", "owner-chat", "owner-thread"
        ) == next_goal["mission_id"]
        delayed_replay, delayed_created = restarted.ingest_owner_turn(
            "Yes, preserve it",
            platform="telegram",
            source_message_id="telegram-answer-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert not delayed_created and delayed_replay == answer
        assert len(restarted.list(100)) == 2
        assert restarted.bound_mission(
            "telegram", "owner-chat", "owner-thread"
        ) == next_goal["mission_id"]


def test_owner_gate_accepts_only_exact_approval_without_clearing_question() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.accept(
            "Architecture change",
            mission_id="mission-owner-gate",
            dispatch_profile="build1-owner-gate",
        )
        assert created
        question_id = "owner-gate:0123456789abcdef01234567"
        store.append_producer(
            accepted["mission_id"],
            {
                "schema_version": 1,
                "mission_id": accepted["mission_id"],
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:owner-gate:1"},
                "payload": {
                    "question_id": question_id,
                    "text": "Reply exactly APPROVE",
                },
            },
        )

        for text in ("approve", "NO", "APPROVE architecture"):
            try:
                store.answer(accepted["mission_id"], question_id, text)
                raise AssertionError("non-exact owner approval was accepted")
            except missions.MissionError as error:
                assert "exactly APPROVE" in str(error)
            projection = store.projection(accepted["mission_id"])
            assert projection["status"] == "waiting_owner"
            assert projection["question"]["question_id"] == question_id
            assert projection["answer"] is None

        # Regression: owner gate question text must distinguish plain text from command
        gate_view = store.projection(accepted["mission_id"])
        gate_text = missions.telegram_text(gate_view)
        assert "обычным сообщением" in gate_text
        assert "(не командой)" in gate_text
        assert "APPROVE" in gate_text

        answer, answer_created = store.answer(
            accepted["mission_id"], question_id, "APPROVE"
        )
        assert answer_created and answer["payload"]["text"] == "APPROVE"
        assert store.projection(accepted["mission_id"])["status"] == "active"


def test_session_ordinary_owner_turn_answers_once_and_survives_restart() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        accepted, created = store.ingest_owner_turn(
            "Deliver from Workspace",
            platform="workspace",
            source_message_id="workspace-goal-1",
            session_id="session-workspace",
        )
        assert created
        mission_id = accepted["mission_id"]
        store.append_producer(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:workspace-question:1"},
                "payload": {
                    "question_id": "workspace-question-1",
                    "text": "Preserve the current behavior?",
                },
            },
        )

        answer, answer_created = store.ingest_owner_turn(
            "Yes, preserve it",
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-workspace",
        )
        assert answer_created and answer["type"] == "mission.answer"
        assert answer["mission_id"] == mission_id
        assert answer["payload"] == {
            "question_id": "workspace-question-1",
            "source_message_id": "workspace-answer-1",
            "source_platform": "workspace",
            "text": "Yes, preserve it",
        }
        assert store.projection(mission_id)["status"] == "active"
        assert len(store.list(100)) == 1

        restarted = missions.MissionStore(database)
        replay, replay_created = restarted.ingest_owner_turn(
            "Yes, preserve it",
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-workspace",
        )
        assert not replay_created and replay == answer
        try:
            restarted.ingest_owner_turn(
                "No, change it",
                platform="workspace",
                source_message_id="workspace-answer-1",
                session_id="session-workspace",
            )
            raise AssertionError("changed replayed Workspace answer was accepted")
        except missions.MissionError as error:
            assert "owner turn idempotency collision" in str(error)

        next_goal, next_created = restarted.ingest_owner_turn(
            "Deliver the next Workspace goal",
            platform="workspace",
            source_message_id="workspace-goal-2",
            session_id="session-workspace",
        )
        assert next_created and next_goal["mission_id"] != mission_id
        delayed_replay, delayed_created = restarted.ingest_owner_turn(
            "Yes, preserve it",
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-workspace",
        )
        assert not delayed_created and delayed_replay == answer
        unrelated, unrelated_created = restarted.ingest_owner_turn(
            "The same source ID belongs to another Central session",
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-other",
        )
        assert unrelated_created and unrelated["mission_id"] not in {
            mission_id, next_goal["mission_id"]
        }


def test_session_owner_turn_fails_closed_for_multiple_open_questions() -> None:
    routes = json.dumps({"workspace": "build1-registered"})
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        for number in (1, 2):
            mission_id = f"mission-ambiguous-{number}"
            store.accept(
                f"Goal {number}",
                mission_id=mission_id,
                session_id="session-ambiguous",
                dispatch_profile="build1-registered",
            )
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.question",
                    "source": "build1-flow",
                    "correlation": {
                        "producer_event_id": f"flow:ambiguous-question:{number}"
                    },
                    "payload": {
                        "question_id": f"question-{number}",
                        "text": f"Question {number}?",
                    },
                },
            )
        try:
            store.ingest_owner_turn(
                "Ambiguous answer",
                platform="workspace",
                source_message_id="workspace-ambiguous-answer",
                session_id="session-ambiguous",
            )
            raise AssertionError("ambiguous Workspace answer was accepted")
        except missions.MissionError as error:
            assert "multiple open mission questions" in str(error)
        assert all(
            not any(event["type"] == "mission.answer" for event in store.events(mission_id))
            for mission_id in ("mission-ambiguous-1", "mission-ambiguous-2")
        )


def test_concurrent_owner_intake_converges_on_one_acceptance() -> None:
    routes = json.dumps({"workspace": "build1-registered"})
    barrier = threading.Barrier(2)
    local = threading.local()

    class RacingStore(missions.MissionStore):
        def events(self, mission_id: str, after: int = 0) -> list[dict]:
            rows = super().events(mission_id, after)
            if (
                threading.current_thread() is not threading.main_thread()
                and mission_id.startswith("mission-intake-")
                and not getattr(local, "read", False)
            ):
                local.read = True
                barrier.wait(timeout=5)
            return rows

    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        database = Path(temp) / "missions.sqlite3"
        stores = [RacingStore(database), RacingStore(database)]
        results: list[tuple[dict, bool]] = []
        failures: list[Exception] = []

        def ingest(store: RacingStore) -> None:
            try:
                results.append(store.ingest_owner_goal(
                    "Concurrent delivery",
                    platform="workspace",
                    source_message_id="message-concurrent",
                    session_id="session-owner",
                ))
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=ingest, args=(store,)) for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not failures and len(results) == 2
        assert len({result[0]["mission_id"] for result in results}) == 1
        assert sorted(result[1] for result in results) == [False, True]
        assert len(stores[0].list(100)) == 1


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
        assert [item["mission_id"] for item in store.dispatch_candidates(
            "build1-uap", 2
        )] == ["mission-old"]
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
        assert store.dispatch_candidates("build1-uap", 1) == []
        store.append_central(
            "mission-old",
            {
                "schema_version": 1,
                "mission_id": "mission-old",
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {"producer_event_id": "central:cancel:mission-old"},
                "payload": {"reason": "serial queue test cleanup"},
            },
        )
        assert [item["mission_id"] for item in store.dispatch_candidates(
            "build1-uap", 2
        )] == ["mission-second"]


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


def test_owner_answer_capability_is_separate_from_the_producer_key() -> None:
    previous_owner = os.environ.get("HERMES_MISSION_OWNER_KEY")
    previous_producer = os.environ.get("HERMES_MISSION_PRODUCER_KEY")
    try:
        os.environ["HERMES_MISSION_OWNER_KEY"] = "owner-secret"
        os.environ["HERMES_MISSION_PRODUCER_KEY"] = "producer-secret"
        assert missions.owner_key_valid("owner-secret")
        assert not missions.owner_key_valid("producer-secret")
        assert not missions.owner_key_valid(None)
    finally:
        if previous_owner is None:
            os.environ.pop("HERMES_MISSION_OWNER_KEY", None)
        else:
            os.environ["HERMES_MISSION_OWNER_KEY"] = previous_owner
        if previous_producer is None:
            os.environ.pop("HERMES_MISSION_PRODUCER_KEY", None)
        else:
            os.environ["HERMES_MISSION_PRODUCER_KEY"] = previous_producer


def test_central_auto_completion_requires_the_full_delivery_contract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-auto-complete"
        store.accept(
            "Deliver safely",
            mission_id=mission_id,
            dispatch_profile="build1-target",
            delivery_mode="none",
        )

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
            {"worker_id": "task-1:run:1", "run_id": "1", "profile": "codex-luna", "status": "scheduled"},
            2,
        )
        publish(
            "worker.upsert",
            {"worker_id": "task-1:run:2", "run_id": "2", "profile": "codex-luna", "status": "success"},
            3,
        )
        publish("change.upsert", {"path": "src/lib.rs", "status": "modified"}, 4)
        publish("change.upsert", {"path": "README.md", "status": "modified"}, 5)
        number = 6
        for gate_id in ("tests", "review", "ci", "post-verify"):
            publish("gate.upsert", {"gate_id": gate_id, "status": "passed"}, number)
            number += 1
        publish(
            "delivery.upsert",
            {
                "kind": "pull_request", "status": "merged",
                "url": "https://example.invalid/pr/1",
                "summary": "Implemented the requested change and covered it with tests.",
            },
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
        assert store.complete_if_ready(mission_id) is None
        publish(
            "delivery.upsert",
            {"kind": "delivery", "status": "not_applicable"},
            number + 2,
        )
        assert store.completion_notification(mission_id) is None
        completed = store.complete_if_ready(mission_id)
        assert completed is not None and completed[1]
        assert completed[0]["source"] == "central-hermes"
        assert completed[0]["type"] == "mission.completed"
        result_text = completed[0]["payload"]["result"]
        assert result_text.startswith(
            "Implemented the requested change and covered it with tests."
        )
        assert "Deliver safely" not in result_text
        assert "PR: https://example.invalid/pr/1" in result_text
        assert "Merge-коммит: https://example.invalid/commit/1" in result_text
        assert "тесты" in result_text
        assert "независимое ревью" in result_text
        assert "пройдены" in result_text
        assert "не настроен для этого проекта" in result_text
        assert "Изменённые файлы (2): README.md, src/lib.rs" in result_text
        verbose = store.projection(mission_id)
        verbose["goal"] = "x" * 8_192
        verbose["changes"] = [
            {"path": f"src/{number}-" + "y" * 240, "status": "modified"}
            for number in range(20)
        ]
        assert len(missions._completion_result(verbose)) <= (
            missions._MAX_COMPLETION_RESULT_CHARS
        )
        assert store.projection(mission_id)["status"] == "completed"
        assert store.completion_notification(mission_id) is None
        assert store.pending_terminal_notification("build1-target") is None

        store.bind(mission_id, "telegram", "42", "7")
        store.bind(mission_id, "telegram", "43", "8")
        notification = store.completion_notification(mission_id)
        assert notification == completed[0]
        assert store.pending_terminal_notification("another-target") is None
        assert store.pending_terminal_notification("build1-target") == completed[0]
        subscription = store.pending_subscriptions(mission_id, notification["sequence"])[0]
        wrong_sequence_token = store.claim_notification(subscription, 1)
        assert wrong_sequence_token is not None
        assert not store.finish_notification(
            subscription,
            notification["sequence"],
            wrong_sequence_token,
            delivered=True,
        )
        assert store.projection(mission_id)["status"] == "completed"
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
        assert store.projection(mission_id)["status"] == "completed"

        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        assert store.complete_if_ready(mission_id) is None
        assert sum(
            event["type"] in missions.TERMINAL_TYPES
            for event in store.events(mission_id)
        ) == 1
        notification = store.completion_notification(mission_id)
        assert notification == completed[0]
        expected_terminal_text = missions.telegram_text(store.projection(mission_id))
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
        assert store.projection(mission_id)["status"] == "completed"
        assert store.pending_terminal_notification("build1-target") == completed[0]

        retry: list[tuple[str, str]] = []

        async def retry_sender(target: dict, text: str) -> None:
            retry.append((target["chat_id"], text))

        assert asyncio.run(missions.notify_subscribers(store, notification, retry_sender)) == 1
        assert retry == [("43", expected_terminal_text)]
        assert store.completion_notification(mission_id) is None
        assert store.pending_terminal_notification("build1-target") is None
        assert asyncio.run(missions.notify_subscribers(store, completed[0], retry_sender)) == 0
        assert retry == [("43", expected_terminal_text)]
        assert store.complete_if_ready(mission_id) is None


def test_auto_completion_accepts_only_scheduled_capacity_history() -> None:
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
        workers=[
            {"worker_id": "worker-1", "status": "scheduled"},
            {"worker_id": "worker-2", "status": "success"},
        ],
    )
    assert missions.completion_ready(view)
    view["workers"][0]["status"] = "running"
    assert not missions.completion_ready(view)
    view["workers"][0]["status"] = "failed"
    assert not missions.completion_ready(view)
    view.update(status="waiting_owner", workers=[{"worker_id": "worker-1", "status": "success"}])
    assert not missions.completion_ready(view)


def test_completion_ready_depends_only_on_delivery_contract() -> None:
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
    assert missions.completion_ready(view)


def test_auto_failure_requires_one_cleaned_review_rejection() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = missions.MissionStore(Path(directory) / "missions.sqlite3")
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
        store = missions.MissionStore(Path(directory) / "missions.sqlite3")
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
            "error": "Автоматические проверки не прошли после разрешённого числа попыток"
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


def test_owner_answer_is_idempotent_and_resumes_the_same_mission() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-question-block"
        store.accept("Wait for owner", mission_id=mission_id)
        store.bind(mission_id, "telegram", "42")
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
        assert view["status"] == "waiting_owner"
        assert view["question"]["question_id"] == "q-1"
        assert store.complete_if_ready(mission_id) is None
        try:
            store.append_producer(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.answer",
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": "flow:forged-answer"},
                    "payload": {"question_id": "q-1", "text": "Forged answer"},
                },
            )
            raise AssertionError("producer forged an owner answer")
        except missions.MissionError as error:
            assert "producer cannot publish" in str(error)
        try:
            store.answer(mission_id, "q-other", "Wrong question")
            raise AssertionError("mismatched owner answer was accepted")
        except missions.MissionError as error:
            assert "open question" in str(error)
        answer, created = store.answer(mission_id, "q-1", "Preserve the current behavior")
        assert created and answer["type"] == "mission.answer"
        replay, replay_created = store.answer(
            mission_id, "q-1", "Preserve the current behavior"
        )
        assert not replay_created and replay == answer
        try:
            store.answer(mission_id, "q-1", "Change the behavior")
            raise AssertionError("conflicting owner answer was accepted")
        except missions.MissionError as error:
            assert "collision" in str(error)
        resumed = store.projection(mission_id)
        assert resumed["status"] == "active" and resumed["question"] is None
        assert resumed["answer"] == {
            "question_id": "q-1",
            "text": "Preserve the current behavior",
        }
        deliveries: list[str] = []

        async def send(_subscription: dict, text: str) -> None:
            deliveries.append(text)

        assert asyncio.run(missions.notify_subscribers(store, answer, send)) == 1
        assert deliveries and "Ответ принят: Preserve the current behavior" in deliveries[0]
        assert store.pending_subscriptions(mission_id, answer["sequence"]) == []
        assert missions.completion_ready(resumed)


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


def test_terminal_retention_preserves_recent_and_bound_missions() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        for number in range(1, 5):
            mission_id = f"mission-retention-{number}"
            store.accept("Retain bounded history", mission_id=mission_id)
            store.append_central(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": f"central:cancel:{number}"},
                    "payload": {"reason": "test cleanup"},
                },
            )
        store.bind("mission-retention-2", "telegram", "42")
        store.bind("mission-retention-1", "telegram", "42")

        assert store.prune_terminal(keep=2) == 1
        assert store.bound_mission("telegram", "42") == "mission-retention-1"
        assert {item["mission_id"] for item in store.list(10)} == {
            "mission-retention-1", "mission-retention-3", "mission-retention-4",
        }
        assert all(
            "mission-retention-2" not in {
                row["previous_mission_id"], row["mission_id"], row["related_mission_id"]
            }
            for row in store.binding_history()
        )
        try:
            store.accept("Reuse retired identity", mission_id="mission-retention-2")
            raise AssertionError("retired mission id was reused")
        except missions.MissionError as error:
            assert str(error) == "mission id was already retired"


def test_terminal_append_applies_default_retention() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        for number in range(missions._MAX_RETAINED_TERMINAL_MISSIONS + 1):
            mission_id = f"mission-auto-retention-{number}"
            store.accept("Retain automatically", mission_id=mission_id)
            store.append_central(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": f"central:auto-cancel:{number}"},
                    "payload": {"reason": "test cleanup"},
                },
            )
        assert len(store.list(100)) == missions._MAX_RETAINED_TERMINAL_MISSIONS
        try:
            store.projection("mission-auto-retention-0")
            raise AssertionError("old terminal mission escaped automatic retention")
        except missions.MissionError as error:
            assert str(error) == "mission not found"
        try:
            store.accept("Reuse retired identity", mission_id="mission-auto-retention-0")
            raise AssertionError("automatic retention allowed mission id reuse")
        except missions.MissionError as error:
            assert str(error) == "mission id was already retired"


def test_bind_and_retention_cannot_create_a_dangling_subscription() -> None:
    with tempfile.TemporaryDirectory() as temp:
        selecting = threading.Event()
        release = threading.Event()
        pause = threading.Event()

        class PausingConnection(sqlite3.Connection):
            def execute(self, sql: str, parameters=(), /):
                normalized = " ".join(sql.split())
                if pause.is_set() and normalized.startswith(
                    "SELECT * FROM mission_events WHERE mission_id"
                ):
                    pause.clear()
                    selecting.set()
                    assert release.wait(2)
                return super().execute(sql, parameters)

        class PausingStore(missions.MissionStore):
            def _connect(self) -> sqlite3.Connection:
                connection = sqlite3.connect(
                    self.path, timeout=10, factory=PausingConnection
                )
                self._harden_permissions()
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA busy_timeout=10000")
                return connection

        store = PausingStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-bind-prune-race"
        store.accept("Retain or reject the bind", mission_id=mission_id)
        store.append_central(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {"producer_event_id": "central:cancel:bind-race"},
                "payload": {"reason": "test cleanup"},
            },
        )
        errors: list[Exception] = []
        pruned: list[int] = []

        def bind() -> None:
            try:
                store.bind(mission_id, "telegram", "42")
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        pause.set()
        bind_thread = threading.Thread(target=bind)
        bind_thread.start()
        assert selecting.wait(2)
        prune_thread = threading.Thread(
            target=lambda: pruned.append(store.prune_terminal(keep=0))
        )
        prune_thread.start()
        assert prune_thread.is_alive()
        release.set()
        bind_thread.join(2)
        prune_thread.join(2)
        assert not bind_thread.is_alive() and not prune_thread.is_alive()
        assert not errors
        assert pruned == [0]
        assert store.bound_mission("telegram", "42") == mission_id
        assert store.projection(mission_id)["mission_id"] == mission_id


def test_explicit_repair_terminal_notifies_before_parent_restore() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            parent = "mission-explicit-parent"
            child = "mission-explicit-child"
            store.accept("Deliver", mission_id=parent)
            store.bind(parent, "telegram", "42")
            store.accept("Repair", mission_id=child, parent_mission_id=parent)
            try:
                store.bind(parent, "telegram", "42")
                raise AssertionError("active repair binding was manually bypassed")
            except missions.MissionError as error:
                assert "protected until terminal notification" in str(error)
            event, created = store.append_central(
                child,
                {
                    "schema_version": 1,
                    "mission_id": child,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": "central:cancel:explicit"},
                    "payload": {"reason": "repair cancelled"},
                },
            )
            assert created and store.bound_mission("telegram", "42") == child
            try:
                store.bind(parent, "telegram", "42")
                raise AssertionError("terminal repair binding was bypassed before notification")
            except missions.MissionError as error:
                assert "protected until terminal notification" in str(error)
            try:
                store.restore_parent_after_terminal_notification(child)
                raise AssertionError("repair binding restored before terminal notification")
            except missions.MissionError as error:
                assert str(error) == "repair terminal notification not checkpointed"

            delivered: list[str] = []

            async def send(_subscription: dict, text: str) -> None:
                delivered.append(text)

            assert await missions.notify_subscribers(store, event, send) == 1
            assert delivered and "cancelled" in delivered[0].lower()
            store.restore_parent_after_terminal_notification(child)
            assert store.bound_mission("telegram", "42") == parent
            replayed, replay_created = store.append_central(child, {
                "schema_version": 1,
                "mission_id": child,
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {"producer_event_id": "central:cancel:explicit"},
                "payload": {"reason": "repair cancelled"},
            })
            assert not replay_created
            assert await missions.notify_subscribers(store, replayed, send) == 0
            store.restore_parent_after_terminal_notification(child)

    asyncio.run(scenario())


def test_terminal_notification_outbox_survives_lease_and_restart() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "missions.sqlite3"
            store = missions.MissionStore(database)
            mission_id = "mission-terminal-outbox-restart"
            store.accept("Deliver", mission_id=mission_id, dispatch_profile="build1-outbox")
            store.bind(mission_id, "telegram", "42")
            ready = [
                ("task.upsert", {"task_id": "task-1", "title": "Root", "status": "done"}),
                ("worker.upsert", {"worker_id": "worker-1", "status": "success"}),
                *(("gate.upsert", {"gate_id": gate, "status": "passed"})
                  for gate in missions._COMPLETION_GATES),
                ("delivery.upsert", {
                    "kind": "pull_request", "status": "merged",
                    "url": "https://example.invalid/pr/1",
                }),
                ("delivery.upsert", {
                    "kind": "default_branch", "status": "verified",
                    "url": "https://example.invalid/commit/1",
                }),
            ]
            for number, (event_type, payload) in enumerate(ready, 1):
                store.append_producer(mission_id, {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:outbox:{number}"},
                    "payload": payload,
                })
            completed = store.complete_if_ready(mission_id)
            assert completed is not None
            terminal = completed[0]
            subscription = store.pending_subscriptions(mission_id, terminal["sequence"])[0]
            token = store.claim_notification(subscription, terminal["sequence"])
            assert token is not None

            restarted = missions.MissionStore(database)
            assert restarted.pending_terminal_notification("build1-outbox") == terminal
            sent: list[str] = []

            async def send(_subscription: dict, text: str) -> None:
                sent.append(text)

            assert await missions.notify_subscribers(restarted, terminal, send) == 0
            assert sent == []
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """UPDATE mission_subscriptions
                       SET notification_lease_until = 0
                       WHERE mission_id = ?""",
                    (mission_id,),
                )
                connection.commit()
            finally:
                connection.close()
            assert await missions.notify_subscribers(restarted, terminal, send) == 1
            assert len(sent) == 1
            assert restarted.pending_terminal_notification("build1-outbox") is None
            assert sum(
                event["type"] in missions.TERMINAL_TYPES
                for event in restarted.events(mission_id)
            ) == 1

    asyncio.run(scenario())


def test_terminal_retention_preserves_active_repair_chain() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        parent = "mission-active-parent"
        child = "mission-terminal-child"
        store.accept("Deliver", mission_id=parent)
        store.bind(parent, "telegram", "42")
        store.accept("Repair", mission_id=child, parent_mission_id=parent)
        store.append_central(
            child,
            {
                "schema_version": 1,
                "mission_id": child,
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {"producer_event_id": "central:cancel:child"},
                "payload": {"reason": "test cleanup"},
            },
        )
        assert store.bound_mission("telegram", "42") == child
        assert store.prune_terminal(keep=0) == 0
        assert store.projection(parent)["status"] == "active"
        assert store.projection(child)["status"] == "cancelled"

    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        parent = "mission-terminal-parent"
        child = "mission-active-child"
        store.accept("Deliver", mission_id=parent)
        store.bind(parent, "telegram", "42")
        store.accept("Repair", mission_id=child, parent_mission_id=parent)
        store.append_central(
            parent,
            {
                "schema_version": 1,
                "mission_id": parent,
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {"producer_event_id": "central:cancel:parent"},
                "payload": {"reason": "test cleanup"},
            },
        )
        assert store.prune_terminal(keep=0) == 0
        assert store.projection(parent)["status"] == "cancelled"
        assert store.projection(child)["status"] == "active"


def test_terminal_retention_preserves_parent_until_repair_notification() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            parent = "mission-terminal-parent"
            child = "mission-terminal-child"
            store.accept("Deliver", mission_id=parent)
            store.bind(parent, "telegram", "42")
            store.accept("Repair", mission_id=child, parent_mission_id=parent)
            store.append_central(
                parent,
                {
                    "schema_version": 1,
                    "mission_id": parent,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": "central:cancel:parent"},
                    "payload": {"reason": "parent stopped"},
                },
            )
            for number in range(101):
                mission_id = f"mission-retention-fill-{number:03d}"
                store.accept("Fill retention", mission_id=mission_id)
                store.append_central(
                    mission_id,
                    {
                        "schema_version": 1,
                        "mission_id": mission_id,
                        "type": "mission.cancelled",
                        "source": "central-hermes",
                        "correlation": {
                            "producer_event_id": f"central:cancel:fill:{number}"
                        },
                        "payload": {"reason": "fill retention"},
                    },
                )
            event, created = store.append_central(
                child,
                {
                    "schema_version": 1,
                    "mission_id": child,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": "central:cancel:child"},
                    "payload": {"reason": "child stopped"},
                },
            )
            assert created
            assert store.projection(parent)["status"] == "cancelled"

            async def send(_subscription: dict, _text: str) -> None:
                return None

            assert await missions.notify_subscribers(store, event, send) == 1
            store.restore_parent_after_terminal_notification(child)
            assert store.bound_mission("telegram", "42") == parent
            assert store.projection(parent)["status"] == "cancelled"
            connection = sqlite3.connect(store.path)
            try:
                unbound = connection.execute(
                    """SELECT COUNT(DISTINCT events.mission_id)
                       FROM mission_events AS events
                       LEFT JOIN mission_subscriptions AS subscriptions
                         ON subscriptions.mission_id = events.mission_id
                       WHERE subscriptions.mission_id IS NULL"""
                ).fetchone()[0]
            finally:
                connection.close()
            assert unbound == missions._MAX_RETAINED_TERMINAL_MISSIONS
            try:
                store.projection("mission-retention-fill-001")
                raise AssertionError("binding restoration left excess terminal history")
            except missions.MissionError as error:
                assert str(error) == "mission not found"

    asyncio.run(scenario())


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
        store.append_central(
            parent,
            {
                "schema_version": 1,
                "mission_id": parent,
                "type": "mission.cancelled",
                "source": "central-hermes",
                "correlation": {
                    "producer_event_id": "central:cancel:repair-parent"
                },
                "payload": {"reason": "parent stopped during repair"},
            },
        )
        for number in range(missions._MAX_RETAINED_TERMINAL_MISSIONS):
            mission_id = f"mission-auto-repair-fill-{number:03d}"
            store.accept("Fill repair retention", mission_id=mission_id)
            store.append_central(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.cancelled",
                    "source": "central-hermes",
                    "correlation": {
                        "producer_event_id": f"central:cancel:repair-fill:{number}"
                    },
                    "payload": {"reason": "fill repair retention"},
                },
            )

        def reject_separate_prune(*_args, **_kwargs):
            raise AssertionError(
                "automatic completion used a second retention transaction"
            )

        original_prune = store.prune_terminal
        store.prune_terminal = reject_separate_prune
        try:
            completed = store.complete_if_ready(child)
        finally:
            store.prune_terminal = original_prune
        assert completed is not None and completed[0]["type"] == "mission.completed"
        assert store.bound_mission("telegram", "42", "7") == child
        notification = store.completion_notification(child)
        assert notification == completed[0]
        subscription = store.pending_subscriptions(child, notification["sequence"])[0]
        token = store.claim_notification(subscription, notification["sequence"])
        assert token and store.finish_notification(
            subscription, notification["sequence"], token, delivered=True
        )
        store.restore_parent_after_terminal_notification(child)
        assert store.bound_mission("telegram", "42", "7") == parent
        connection = sqlite3.connect(store.path)
        try:
            unbound = connection.execute(
                """SELECT COUNT(DISTINCT events.mission_id)
                   FROM mission_events AS events
                   LEFT JOIN mission_subscriptions AS subscriptions
                     ON subscriptions.mission_id = events.mission_id
                   WHERE subscriptions.mission_id IS NULL"""
            ).fetchone()[0]
        finally:
            connection.close()
        assert unbound == missions._MAX_RETAINED_TERMINAL_MISSIONS, unbound
        assert [item["reason"] for item in store.binding_history()] == [
            "manual-bind", "repair-inherit", "repair-restore"
        ]
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
        assert review["payload"]["error"] == "Независимое ревью отклонило результат"
        author_checks = fail(
            "mission-author-checks-failed-after-pr",
            [("tests", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert author_checks["payload"]["error"] == (
            "Автоматические проверки не прошли после разрешённого числа попыток"
        )
        execution = fail(
            "mission-execution-state-failed",
            [("execution", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert execution["payload"]["error"] == (
            "Прерванное выполнение потеряло рабочую копию и безопасно остановлено"
        )
        ci = fail(
            "mission-ci-failed",
            [("tests", "passed"), ("review", "passed"), ("ci", "failed"), ("cleanup", "passed")],
            "failed",
        )
        assert ci["payload"]["error"] == (
            "Обязательный CI не прошёл после разрешённого числа попыток"
        )
        post_verify = fail(
            "mission-post-verify-failed",
            [
                ("tests", "passed"), ("review", "passed"), ("ci", "passed"),
                ("post-verify", "failed"), ("cleanup", "passed"),
            ],
            "merged",
        )
        assert post_verify["payload"]["error"] == (
            "Проверка после слияния не прошла после автоматического исправления"
        )


def test_failure_terminal_commits_before_telegram_and_retries_delivery() -> None:
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

            terminal = store.complete_if_ready(mission_id)
            assert terminal is not None and terminal[0]["type"] == "mission.failed"
            notification = store.completion_notification(mission_id)
            assert notification == terminal[0]

            async def fail_once(_subscription: dict, _text: str) -> None:
                raise RuntimeError("telegram unavailable")

            try:
                await missions.notify_subscribers(store, notification, fail_once)
                raise AssertionError("failed Telegram delivery was accepted")
            except RuntimeError as error:
                assert str(error) == "telegram unavailable"
            assert store.complete_if_ready(mission_id) is None
            assert store.projection(mission_id)["status"] == "failed"

            delivered: list[str] = []

            async def send(_subscription: dict, text: str) -> None:
                delivered.append(text)

            assert await missions.notify_subscribers(store, notification, send) == 1
            assert delivered and ("ошибк" in delivered[0].lower() or "failed" in delivered[0].lower())
            assert store.completion_notification(mission_id) is None
            assert store.complete_if_ready(mission_id) is None
            assert store.pending_subscriptions(mission_id, terminal[0]["sequence"]) == []

    asyncio.run(scenario())


def test_disk_space_notice_contract_through_runtime_validation_and_store() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            store.accept("Deliver the change", mission_id="mission-disk")

            pre_handoff = {
                "schema_version": 1,
                "mission_id": "mission-disk",
                "type": "mission.notice",
                "source": "build1-flow",
                "correlation": {
                    "producer_event_id": "flow:mission-disk:disk-wait-pre",
                },
                "payload": {
                    "code": "disk_space_wait",
                    "message": (
                        "Worktree volume is below the minimum free-space reserve; "
                        "delivery paused until space is available."
                    ),
                    "owner_action_required": False,
                    "next_attempt_at": "2026-07-21T12:00:00Z",
                },
            }
            stored, created = store.append_producer("mission-disk", pre_handoff)
            assert created
            view = store.projection("mission-disk")
            assert view["notice"] == pre_handoff["payload"]
            assert view["question"] is None

            dup, dup_created = store.append_producer("mission-disk", pre_handoff)
            assert not dup_created
            assert dup["sequence"] == stored["sequence"]

            collision = {
                **pre_handoff,
                "payload": {**pre_handoff["payload"], "message": "changed text"},
            }
            try:
                store.append_producer("mission-disk", collision)
                raise AssertionError("producer id collision was accepted")
            except missions.MissionError as error:
                assert "collision" in str(error)

            with_task = {
                "schema_version": 1,
                "mission_id": "mission-disk",
                "type": "mission.notice",
                "source": "build1-flow",
                "correlation": {
                    "task_id": "task-42",
                    "producer_event_id": "flow:mission-disk:disk-wait-active",
                },
                "payload": {
                    "code": "disk_space_wait",
                    "message": (
                        "Worktree volume is below the minimum free-space reserve; "
                        "delivery paused until space is available."
                    ),
                    "owner_action_required": False,
                    "next_attempt_at": "2026-07-21T12:05:00Z",
                },
            }
            stored2, created2 = store.append_producer("mission-disk", with_task)
            assert created2
            view2 = store.projection("mission-disk")
            assert view2["notice"] == with_task["payload"]

            recovered = {
                "schema_version": 1,
                "mission_id": "mission-disk",
                "type": "mission.notice",
                "source": "build1-flow",
                "correlation": {
                    "task_id": "task-42",
                    "producer_event_id": "flow:mission-disk:disk-recovered",
                },
                "payload": {
                    "code": "disk_space_recovered",
                    "message": "Worktree volume free space recovered; delivery resumed.",
                    "owner_action_required": False,
                },
            }
            stored3, created3 = store.append_producer("mission-disk", recovered)
            assert created3
            view3 = store.projection("mission-disk")
            assert view3["notice"] == recovered["payload"]
            rendered = missions.telegram_text(view3)
            assert "освобождено" in rendered

            empty_correlation = {
                "schema_version": 1,
                "mission_id": "mission-disk",
                "type": "mission.notice",
                "source": "build1-flow",
                "correlation": {
                    "task_id": "",
                    "producer_event_id": "flow:mission-disk:empty-task",
                },
                "payload": {
                    "code": "disk_space_wait",
                    "message": "test",
                    "owner_action_required": False,
                },
            }
            try:
                store.append_producer("mission-disk", empty_correlation)
                raise AssertionError("empty task_id correlation was accepted")
            except missions.MissionError as error:
                assert "correlation.task_id" in str(error)

    asyncio.run(scenario())



def main() -> None:
    test_research_only_goal_bypasses_coding_mission_intake()
    test_project_onboarding_is_idempotent_restart_safe_and_forward_only()
    test_reconnect_projects_one_canonical_state()
    test_producer_retry_and_notification_checkpoint_are_idempotent()
    test_notification_can_repeat_after_delivery_before_checkpoint()
    test_notification_checkpoint_cannot_cross_a_mission_rebind()
    test_producer_cannot_end_mission_or_decrease_progress()
    test_dispatch_profile_is_projected_and_immutable()
    test_registered_owner_intake_is_deterministic_and_fail_closed()
    test_registered_project_selection_is_durable_and_restart_safe()
    test_bound_ordinary_owner_turn_answers_once_and_survives_restart()
    test_owner_gate_accepts_only_exact_approval_without_clearing_question()
    test_session_ordinary_owner_turn_answers_once_and_survives_restart()
    test_session_owner_turn_fails_closed_for_multiple_open_questions()
    test_concurrent_owner_intake_converges_on_one_acceptance()
    test_dispatch_candidates_do_not_starve_behind_newer_missions()
    test_producer_schema_is_closed_and_all_strings_are_redacted()
    test_terminal_authority_is_loopback_only()
    test_owner_answer_capability_is_separate_from_the_producer_key()
    test_central_auto_completion_requires_the_full_delivery_contract()
    test_auto_completion_accepts_only_scheduled_capacity_history()
    test_completion_ready_depends_only_on_delivery_contract()
    test_auto_completion_snapshot_and_terminal_insert_are_one_transaction()
    test_owner_answer_is_idempotent_and_resumes_the_same_mission()
    test_mission_database_is_owner_only_on_posix()
    test_terminal_retention_preserves_recent_and_bound_missions()
    test_terminal_append_applies_default_retention()
    test_bind_and_retention_cannot_create_a_dangling_subscription()
    test_explicit_repair_terminal_notifies_before_parent_restore()
    test_terminal_notification_outbox_survives_lease_and_restart()
    test_terminal_retention_preserves_active_repair_chain()
    test_terminal_retention_preserves_parent_until_repair_notification()
    test_existing_subscription_table_gets_notification_lease_columns()
    test_repair_mission_inherits_and_restores_telegram_binding()
    test_terminal_failure_contracts_include_preserved_pr_ci_and_post_verify()
    test_failure_terminal_commits_before_telegram_and_retries_delivery()
    test_disk_space_notice_contract_through_runtime_validation_and_store()
    print("hermes mission runtime checks passed")


if __name__ == "__main__":
    main()

def test_worker_upsert_schema_accepts_telemetry_fields() -> None:
    """worker.upsert accepts model, effort, input_tokens, output_tokens."""
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Schema test", mission_id="mission-schema-worker")
        store.append_producer("mission-schema-worker", {
            "schema_version": 1, "mission_id": "mission-schema-worker",
            "type": "worker.upsert", "source": "build1-flow",
            "correlation": {"producer_event_id": "schema:w1"},
            "payload": {"worker_id": "w1", "status": "completed",
                        "model": "gpt-5.6-sol", "effort": "high",
                        "input_tokens": 1000, "output_tokens": 500},
        })
        view = store.projection("mission-schema-worker")
        assert view["workers"][0]["model"] == "gpt-5.6-sol"
        assert view["workers"][0]["input_tokens"] == 1000


def test_worker_upsert_schema_rejects_invalid_tokens() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Schema test", mission_id="mission-schema-reject")
        for bad_value in (-1, True):
            try:
                store.append_producer("mission-schema-reject", {
                    "schema_version": 1, "mission_id": "mission-schema-reject",
                    "type": "worker.upsert", "source": "build1-flow",
                    "correlation": {"producer_event_id": f"schema:bad:{bad_value}"},
                    "payload": {"worker_id": "w1", "status": "completed",
                                "input_tokens": bad_value},
                })
                raise AssertionError(f"invalid input_tokens {bad_value} was accepted")
            except missions.MissionError:
                pass


def test_accepted_schema_project_label_repository() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        ev, created = store.accept("Label test", mission_id="mission-schema-label",
                                   project_label="UAP",
                                   project_repository="Owner/repo")
        assert created and ev["payload"]["project_label"] == "UAP"
        try:
            store.accept("Bad repo", mission_id="mission-schema-badrepo",
                         project_repository="not valid!")
            raise AssertionError("invalid project_repository was accepted")
        except missions.MissionError:
            pass
