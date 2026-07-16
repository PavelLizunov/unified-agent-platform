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
        "/api/missions/{mission_id}/terminal", adapter._handle_finish_mission
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        created = await client.post(
            "/api/missions", json={
                "mission_id": "mission-smoke",
                "goal": "Ship smoke",
                "dispatch_profile": "build1-smoke",
            }
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
        headers = {"X-Hermes-Mission-Producer-Key": "test-producer-key"}
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
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=pathlib.Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-mission-api-") as home:
        os.environ["HERMES_HOME"] = home
        os.environ["HERMES_MISSION_PRODUCER_KEY"] = "test-producer-key"
        asyncio.run(smoke(args.checkout.resolve()))
    print("hermes mission API smoke passed")


if __name__ == "__main__":
    main()
