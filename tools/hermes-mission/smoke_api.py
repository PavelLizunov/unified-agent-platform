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
        completed = await client.post(
            "/api/missions/mission-smoke/terminal",
            json={"status": "completed", "message": "Smoke delivered"},
        )
        assert completed.status == 201, await completed.text()
        completed_replay = await client.post(
            "/api/missions/mission-smoke/terminal",
            json={"status": "completed", "message": "Smoke delivered"},
        )
        replay_body = await completed_replay.json()
        assert completed_replay.status == 200 and replay_body["created"] is False
        assert replay_body["mission"]["status"] == "completed"
        assert replay_body["mission"]["result"] == "Smoke delivered"
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
