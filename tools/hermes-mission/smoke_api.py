#!/usr/bin/env python3
"""Offline aiohttp smoke for a checkout after the mission overlay is applied."""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import tempfile


async def smoke(checkout: pathlib.Path) -> None:
    sys.path.insert(0, str(checkout))
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={}))
    app = web.Application()
    app.router.add_get("/api/missions", adapter._handle_list_missions)
    app.router.add_post("/api/missions", adapter._handle_create_mission)
    app.router.add_get("/api/missions/{mission_id}", adapter._handle_get_mission)
    app.router.add_post(
        "/api/missions/{mission_id}/events", adapter._handle_append_mission_event
    )
    app.router.add_post(
        "/api/missions/{mission_id}/answer", adapter._handle_answer_mission
    )
    app.router.add_post(
        "/api/missions/{mission_id}/terminal", adapter._handle_finish_mission
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        headers = {"X-Hermes-Mission-Producer-Key": "test-producer-key"}
        created = await client.post(
            "/api/missions", json={
                "mission_id": "mission-smoke",
                "goal": "Ship smoke",
                "dispatch_profile": "build1-smoke",
            }, headers=headers,
        )
        assert created.status == 201, await created.text()
        eligible = await client.get(
            "/api/missions?dispatch_profile=build1-smoke&limit=1"
        )
        eligible_body = await eligible.json()
        assert eligible.status == 200
        assert [item["mission_id"] for item in eligible_body["missions"]] == ["mission-smoke"]
        wrong_profile = await client.get(
            "/api/missions?dispatch_profile=another-profile&limit=1"
        )
        assert (await wrong_profile.json())["missions"] == []
        invalid_profile = await client.get("/api/missions?dispatch_profile=&limit=1")
        assert invalid_profile.status == 400
        bad = await client.post("/api/missions/mission-smoke/events", json={})
        assert bad.status == 401
        event = {
            "schema_version": 1,
            "mission_id": "mission-smoke",
            "type": "mission.stage",
            "source": "build1-flow",
            "correlation": {"producer_event_id": "flow:smoke:testing"},
            "payload": {"stage": "testing", "progress_percent": 60},
        }
        first = await client.post(
            "/api/missions/mission-smoke/events", json=event, headers=headers
        )
        assert first.status == 201, await first.text()
        replay = await client.post(
            "/api/missions/mission-smoke/events", json=event, headers=headers
        )
        replay_body = await replay.json()
        assert replay.status == 200 and replay_body["created"] is False
        collision = {**event, "payload": {"stage": "reviewing", "progress_percent": 70}}
        collision_response = await client.post(
            "/api/missions/mission-smoke/events", json=collision, headers=headers
        )
        assert collision_response.status == 400, await collision_response.text()
        unknown = {
            **event,
            "correlation": {"producer_event_id": "flow:smoke:unknown"},
            "payload": {**event["payload"], "details": "not allowed"},
        }
        rejected = await client.post(
            "/api/missions/mission-smoke/events", json=unknown, headers=headers
        )
        assert rejected.status == 400, await rejected.text()
        task = {
            "schema_version": 1,
            "mission_id": "mission-smoke",
            "type": "task.upsert",
            "source": "build1-flow",
            "correlation": {"task_id": "task-1", "producer_event_id": "flow:smoke:task"},
            "payload": {"task_id": "task-1", "title": "Root", "status": "running"},
        }
        task_response = await client.post(
            "/api/missions/mission-smoke/events", json=task, headers=headers
        )
        assert task_response.status == 201, await task_response.text()
        handed_off = await client.get(
            "/api/missions?dispatch_profile=build1-smoke&reconcile=1&limit=1"
        )
        handed_off_body = await handed_off.json()
        assert [item["mission_id"] for item in handed_off_body["missions"]] == ["mission-smoke"]
        invalid_reconcile = await client.get(
            "/api/missions?dispatch_profile=build1-smoke&reconcile=yes&limit=1"
        )
        assert invalid_reconcile.status == 400
        question = {
            "schema_version": 1,
            "mission_id": "mission-smoke",
            "type": "mission.question",
            "source": "build1-flow",
            "correlation": {"producer_event_id": "flow:smoke:question"},
            "payload": {"question_id": "q-smoke", "text": "Choose behavior"},
        }
        question_response = await client.post(
            "/api/missions/mission-smoke/events", json=question, headers=headers
        )
        assert question_response.status == 201, await question_response.text()
        answer_body = {"question_id": "q-smoke", "text": "Preserve behavior"}
        missing_owner_key = await client.post(
            "/api/missions/mission-smoke/answer", json=answer_body
        )
        assert missing_owner_key.status == 401
        owner_headers = {"X-Hermes-Mission-Owner-Key": "test-owner-key"}
        answer = await client.post(
            "/api/missions/mission-smoke/answer", json=answer_body, headers=owner_headers
        )
        answer_json = await answer.json()
        assert answer.status == 201 and answer_json["mission"]["status"] == "active"
        assert answer_json["mission"]["question"] is None
        assert answer_json["mission"]["answer"] == answer_body
        answer_replay = await client.post(
            "/api/missions/mission-smoke/answer", json=answer_body, headers=owner_headers
        )
        assert answer_replay.status == 200
        assert (await answer_replay.json())["created"] is False
        conflicting_answer = await client.post(
            "/api/missions/mission-smoke/answer",
            json={"question_id": "q-smoke", "text": "Change behavior"},
            headers=owner_headers,
        )
        assert conflicting_answer.status == 400
        forged = await client.post(
            "/api/missions/mission-forged/events",
            json={
                "schema_version": 1,
                "mission_id": "mission-forged",
                "type": "mission.accepted",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:smoke:forged"},
                "payload": {"goal": "Forged"},
            },
            headers=headers,
        )
        assert forged.status == 400, await forged.text()
        listing = await client.get("/api/missions")
        view = (await listing.json())["missions"][0]
        assert view["stage"] == "testing" and view["progress_percent"] == 60
        assert view["dispatch_profile"] == "build1-smoke"
        manual_success = await client.post(
            "/api/missions/mission-smoke/terminal",
            json={"status": "completed", "message": "Smoke delivered"},
        )
        assert manual_success.status == 400, await manual_success.text()
        cancelled = await client.post(
            "/api/missions/mission-smoke/terminal",
            json={"status": "cancelled", "message": "Smoke cleanup"},
        )
        assert cancelled.status == 201, await cancelled.text()
        cancelled_replay = await client.post(
            "/api/missions/mission-smoke/terminal",
            json={"status": "cancelled", "message": "Smoke cleanup"},
        )
        replay_body = await cancelled_replay.json()
        assert cancelled_replay.status == 200 and replay_body["created"] is False
        assert replay_body["mission"]["status"] == "cancelled"
        assert replay_body["mission"]["error"] == "Smoke cleanup"

        owner_body = {
            "goal": "Ordinary owner goal",
            "platform": "workspace",
            "source_message_id": "owner-message-smoke",
            "session_id": "owner-session-smoke",
        }
        owner_headers = {"X-Hermes-Mission-Owner-Key": "test-owner-key"}
        missing_owner_key = await client.post("/api/missions", json=owner_body)
        assert missing_owner_key.status == 401, await missing_owner_key.text()
        ambiguous = await client.post(
            "/api/missions", json=owner_body, headers={**headers, **owner_headers}
        )
        assert ambiguous.status == 401, await ambiguous.text()
        explicit_null = await client.post(
            "/api/missions", json={**owner_body, "thread_id": None}, headers=owner_headers
        )
        assert explicit_null.status == 400, await explicit_null.text()
        owner = await client.post(
            "/api/missions", json=owner_body, headers=owner_headers
        )
        owner_payload = await owner.json()
        assert owner.status == 201, owner_payload
        assert owner_payload["mission"]["dispatch_profile"] == "build1-owner-smoke"
        owner_replay = await client.post(
            "/api/missions", json=owner_body, headers=owner_headers
        )
        replay_payload = await owner_replay.json()
        assert owner_replay.status == 200 and replay_payload["created"] is False
        assert replay_payload["mission"]["mission_id"] == owner_payload["mission"]["mission_id"]
        forbidden_profile = await client.post(
            "/api/missions", json={**owner_body, "dispatch_profile": "build1-forged"},
            headers=owner_headers,
        )
        assert forbidden_profile.status == 400, await forbidden_profile.text()
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=pathlib.Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-mission-api-") as home:
        os.environ["HERMES_HOME"] = home
        os.environ["HERMES_MISSION_PRODUCER_KEY"] = "test-producer-key"
        os.environ["HERMES_MISSION_OWNER_KEY"] = "test-owner-key"
        os.environ["HERMES_MISSION_INTAKE_ROUTES"] = (
            '{"workspace":"build1-owner-smoke"}'
        )
        asyncio.run(smoke(args.checkout.resolve()))
    print("hermes mission API smoke passed")


if __name__ == "__main__":
    main()
