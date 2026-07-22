#!/usr/bin/env python3
import copy
import datetime
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "hermes-mission-events-v1.json"
EVENT_TYPES = {
    "mission.accepted", "mission.stage", "mission.notice", "mission.question", "mission.answer", "task.upsert",
    "worker.upsert", "terminal.append", "change.upsert", "gate.upsert",
    "delivery.upsert", "mission.completed", "mission.failed", "mission.cancelled",
}
REQUIRED_PAYLOAD = {
    "mission.accepted": {"goal"},
    "mission.stage": {"stage", "progress_percent"},
    "mission.notice": {"code", "message", "owner_action_required"},
    "mission.question": {"question_id", "text"},
    "mission.answer": {"question_id", "text"},
    "task.upsert": {"task_id", "title", "status"},
    "worker.upsert": {"worker_id", "status"},
    "terminal.append": {"stream", "text"},
    "change.upsert": {"path", "status"},
    "gate.upsert": {"gate_id", "status"},
    "delivery.upsert": {"kind", "status"},
    "mission.completed": {"result"},
    "mission.failed": {"error"},
    "mission.cancelled": {"reason"},
}
SOURCES = {"central-hermes", "workspace", "telegram", "build1-flow", "test-vm", "github", "flux"}
TERMINAL_TYPES = {"mission.completed", "mission.failed", "mission.cancelled"}
STAGES = {
    "accepted", "planning", "implementing", "testing", "reviewing",
    "delivering", "verifying", "deploying", "complete",
}


class ContractError(ValueError):
    pass


def validate_events(document):
    mission_id = document.get("mission_id")
    events = document.get("events")
    if document.get("schema_version") != 1 or not isinstance(mission_id, str) or not mission_id:
        raise ContractError("invalid mission envelope")
    if not isinstance(events, list) or not events:
        raise ContractError("events required")

    seen = set()
    progress = -1
    for sequence, event in enumerate(events, 1):
        if event.get("schema_version") != 1 or event.get("mission_id") != mission_id:
            raise ContractError("event mission/version mismatch")
        if event.get("sequence") != sequence:
            raise ContractError("sequence gap")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            raise ContractError("event_id must be unique")
        seen.add(event_id)
        if event.get("type") not in EVENT_TYPES or event.get("source") not in SOURCES:
            raise ContractError("unknown event type/source")
        if not isinstance(event.get("correlation"), dict) or not isinstance(event.get("payload"), dict):
            raise ContractError("correlation and payload must be objects")
        if not REQUIRED_PAYLOAD[event["type"]].issubset(event["payload"]):
            raise ContractError("required payload field missing")
        try:
            datetime.datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError) as error:
            raise ContractError("invalid occurred_at") from error
        if event["type"] == "mission.stage":
            next_progress = event["payload"].get("progress_percent")
            if event["payload"].get("stage") not in STAGES:
                raise ContractError("invalid stage")
            if not isinstance(next_progress, int) or not progress <= next_progress <= 100:
                raise ContractError("progress must be monotonic")
            progress = next_progress
        if event["type"] == "delivery.upsert":
            payload = event["payload"]
            not_applicable = (
                payload.get("kind") == "delivery"
                and payload.get("status") == "not_applicable"
            )
            if (not_applicable and "url" in payload) or (
                not not_applicable and not payload.get("url")
            ):
                raise ContractError("invalid delivery applicability")
        if event["type"] in TERMINAL_TYPES and sequence != len(events):
            raise ContractError("terminal event must be last")
    if events[-1]["type"] not in TERMINAL_TYPES:
        raise ContractError("terminal event required")


class FakeMissionBackend:
    def __init__(self, document):
        validate_events(document)
        self.events = copy.deepcopy(document["events"])

    def read_after(self, cursor, limit):
        return copy.deepcopy([event for event in self.events if event["sequence"] > cursor][:limit])


class Projection:
    def __init__(self):
        self.cursor = 0
        self.event_ids = set()
        self.state = {
            "mission_id": None, "status": None, "stage": None, "progress_percent": 0,
            "goal": None, "delivery_mode": None, "notice": None, "tasks": {}, "workers": {}, "terminal": [], "changes": {},
            "gates": {}, "delivery": {}, "question": None, "answer": None, "result": None,
        }

    def apply(self, event):
        if event["event_id"] in self.event_ids:
            return
        if event["sequence"] != self.cursor + 1:
            raise ContractError("projection sequence gap")
        if self.state["mission_id"] not in (None, event["mission_id"]):
            raise ContractError("projection mission mismatch")

        self.state["mission_id"] = event["mission_id"]
        payload = event["payload"]
        event_type = event["type"]
        if event_type == "mission.accepted":
            self.state.update(
                status="active", stage="accepted", goal=payload["goal"],
                delivery_mode=payload.get("delivery_mode"),
            )
        elif event_type == "mission.stage":
            self.state.update(
                stage=payload["stage"], progress_percent=payload["progress_percent"],
                notice=None,
            )
        elif event_type == "mission.notice":
            self.state["notice"] = payload
        elif event_type == "mission.question":
            self.state.update(status="waiting_owner", question=payload, answer=None)
        elif event_type == "mission.answer":
            if (
                self.state["status"] != "waiting_owner"
                or not self.state["question"]
                or self.state["question"]["question_id"] != payload["question_id"]
            ):
                raise ContractError("answer does not match the open question")
            self.state.update(status="active", question=None, answer=payload)
        elif event_type == "task.upsert":
            self.state["tasks"][payload["task_id"]] = payload
        elif event_type == "worker.upsert":
            self.state["workers"][payload["worker_id"]] = payload
        elif event_type == "terminal.append":
            self.state["terminal"].append(payload)
        elif event_type == "change.upsert":
            self.state["changes"][payload["path"]] = payload
        elif event_type == "gate.upsert":
            self.state["gates"][payload["gate_id"]] = payload
        elif event_type == "delivery.upsert":
            self.state["delivery"][payload["kind"]] = payload
        elif event_type == "mission.completed":
            self.state.update(status="completed", stage="complete", progress_percent=100, result=payload["result"])
        elif event_type == "mission.failed":
            self.state.update(status="failed", result=payload["error"])
        elif event_type == "mission.cancelled":
            self.state.update(status="cancelled", result=payload["reason"])

        self.cursor = event["sequence"]
        self.event_ids.add(event["event_id"])


def consume(backend, projection, page_size):
    while True:
        page = backend.read_after(projection.cursor, page_size)
        if not page:
            return
        for event in page:
            projection.apply(event)


class MissionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_contract(self):
        validate_events(self.document)

    def test_workspace_telegram_reconnect_and_refresh_converge(self):
        backend = FakeMissionBackend(self.document)
        workspace = Projection()
        for event in backend.read_after(0, 4):
            workspace.apply(event)
        consume(backend, workspace, 3)

        telegram = Projection()
        consume(backend, telegram, 2)

        refreshed_workspace = Projection()
        consume(backend, refreshed_workspace, 50)
        self.assertEqual(workspace.state, telegram.state)
        self.assertEqual(workspace.state, refreshed_workspace.state)
        self.assertEqual("completed", workspace.state["status"])

    def test_duplicate_is_idempotent_and_gap_fails_closed(self):
        projection = Projection()
        first, second = self.document["events"][:2]
        projection.apply(first)
        projection.apply(first)
        self.assertEqual(1, projection.cursor)
        gap = copy.deepcopy(second)
        gap["sequence"] = 3
        with self.assertRaisesRegex(ContractError, "sequence gap"):
            projection.apply(gap)

    def test_not_applicable_delivery_has_no_fake_url(self):
        document = copy.deepcopy(self.document)
        delivery = next(
            event for event in document["events"]
            if event["type"] == "delivery.upsert"
        )
        delivery["payload"] = {"kind": "delivery", "status": "not_applicable"}
        validate_events(document)
        delivery["payload"]["url"] = "https://example.invalid/fake-deploy"
        with self.assertRaisesRegex(ContractError, "delivery applicability"):
            validate_events(document)


if __name__ == "__main__":
    unittest.main()
