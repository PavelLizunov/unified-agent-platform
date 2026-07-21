"""Owner-readable summary projection: focused behavior tests."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tools" / "hermes-mission" / "runtime.py"
SPEC = importlib.util.spec_from_file_location("uap_missions", RUNTIME)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

MID = "mission-intake-abcdef1234567890abcdef1234567890"


def _view(**kw) -> dict:
    v = m.empty_projection()
    v.update(kw)
    return v


def _accepted(**kw) -> dict:
    p = {"goal": kw.pop("goal", "Implement the feature")}
    for f in ("project_id", "project_label", "project_repository", "dispatch_profile", "delivery_mode"):
        if f in kw:
            p[f] = kw.pop(f)
    return {
        "schema_version": 1, "mission_id": MID, "type": "mission.accepted",
        "source": "central-hermes", "correlation": {"producer_event_id": "t:a"},
        "payload": p, "sequence": 1, "event_id": f"{MID}:1",
        "occurred_at": kw.pop("occurred_at", "2026-07-21T10:00:00.000Z"),
    }


def test_headline_telegram_text_and_backward_compat() -> None:
    v = _view(project_label="UAP", project_repository="Owner/repo")
    assert m._headline(v) == "UAP (Owner/repo)"
    assert m._headline(_view(goal="Fix bug")) == "Fix bug"
    assert "34567890" in m._headline(_view(mission_id=MID))
    view = m.project([_accepted(project_label="UAP", project_repository="Owner/repo",
                                goal="Implement auth")])
    text = m.telegram_text(view)
    assert "UAP (Owner/repo)" in text and "ID:" in text
    assert "\u0426\u0435\u043b\u044c: Implement auth" in text
    compat = m.telegram_text(m.project([_accepted()]))
    assert "ID:" in compat and "\u042d\u0442\u0430\u043f:" in compat
    # Telemetry workers must not inflate the displayed worker count
    tv = _view(goal="G", status="failed", error="err", workers=[
        {"worker_id": "t1:run:1", "status": "completed"},
        {"worker_id": "author", "status": "completed", "profile": "author",
         "model": "gpt-5.6-sol", "effort": "high"},
        {"worker_id": "reviewer", "status": "completed", "profile": "reviewer",
         "model": "gpt-5.6-terra"},
    ])
    ttext = m.telegram_text(tv)
    assert "\u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u0438 1" in ttext
    assert "\u0410\u0432\u0442\u043e\u0440 (\u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d)" in ttext


def test_completion_gates_deploy_and_fail_closed() -> None:
    v = _view(goal="G", status="completed", gates=[
        {"gate_id": "tests", "status": "passed"},
        {"gate_id": "review", "status": "passed"},
        {"gate_id": "ci", "status": "failed"},
    ])
    r = m._completion_result(v)
    assert "\u0442\u0435\u0441\u0442\u044b" in r and "CI \u2014 \u043d\u0435 \u043f\u0440\u043e\u0439\u0434\u0435\u043d\u044b" in r
    all_ok = _view(goal="G", status="completed", gates=[
        {"gate_id": "tests", "status": "passed"}, {"gate_id": "review", "status": "passed"},
    ])
    assert "\u0442\u0435\u0441\u0442\u044b, \u043d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u043e\u0435 \u0440\u0435\u0432\u044c\u044e \u2014 \u043f\u0440\u043e\u0439\u0434\u0435\u043d\u044b" in m._completion_result(all_ok)
    assert "\u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445" in m._completion_result(_view(goal="G", status="completed", gates=[]))
    dep = m._completion_result(_view(goal="G", status="completed", delivery_mode="none"))
    assert "\u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0430" in dep


def test_completion_elapsed_from_updated_at() -> None:
    v = _view(goal="G", status="completed",
              started_at="2026-07-21T10:00:00.000Z", updated_at="2026-07-21T11:30:00.000Z")
    assert "1\u0447 30\u043c" in m._completion_result(v)
    assert "\u0412\u0440\u0435\u043c\u044f:" not in m._completion_result(_view(goal="G", status="completed"))


def test_completion_role_telemetry_and_no_cost() -> None:
    v = _view(goal="G", status="completed", workers=[
        {"worker_id": "author", "status": "completed", "profile": "author",
         "model": "gpt-5.6-sol", "effort": "high", "input_tokens": 5000, "output_tokens": 2000},
        {"worker_id": "reviewer", "status": "completed", "profile": "reviewer",
         "model": "gpt-5.6-terra", "effort": "high"},
    ])
    r = m._completion_result(v)
    assert "\u0410\u0432\u0442\u043e\u0440 (\u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d): gpt-5.6-sol \u00b7 effort high \u00b7 5000 in / 2000 out" in r
    assert "\u0420\u0435\u0432\u044c\u044e\u0435\u0440 (\u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d): gpt-5.6-terra \u00b7 effort high" in r
    assert "$" not in r and "cost" not in r.lower()
    r2 = m._completion_result(_view(goal="G", status="completed",
                                    workers=[{"worker_id": "w", "status": "done"}]))
    assert "\u0410\u0432\u0442\u043e\u0440 (" not in r2


def test_store_end_to_end_label_telemetry_timestamps() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = m.MissionStore(Path(temp) / "m.sqlite3")
        ev, created = store.accept("Goal", mission_id="mission-e2e",
                                   project_label="UAP", project_repository="O/r")
        assert created and ev["payload"]["project_label"] == "UAP"
        store.append_producer("mission-e2e", {
            "schema_version": 1, "mission_id": "mission-e2e",
            "type": "worker.upsert", "source": "build1-flow",
            "correlation": {"producer_event_id": "t:w"},
            "payload": {"worker_id": "author", "status": "completed", "profile": "author",
                        "model": "gpt-5.6-sol", "effort": "high",
                        "input_tokens": 100, "output_tokens": 50},
        })
        v = store.projection("mission-e2e")
        assert v["workers"][0]["model"] == "gpt-5.6-sol"
        assert v["started_at"] is not None and v["updated_at"] is not None
        assert "UAP" in m.telegram_text(v)
        _, again = store.accept("Goal", mission_id="mission-e2e",
                                project_label="UAP", project_repository="O/r")
        assert not again


def test_model_and_effort_validation() -> None:
    for bad in ("qwen3.8-max-preview", "claude-sonnet-4-20250514", "llama-4", "unknown"):
        try:
            m._validate_submission("mission-x", {
                "schema_version": 1, "mission_id": "mission-x",
                "type": "worker.upsert", "source": "build1-flow",
                "correlation": {"producer_event_id": f"t:{bad}"},
                "payload": {"worker_id": "w", "status": "done", "model": bad},
            })
            raise AssertionError(f"model {bad} accepted")
        except m.MissionError as e:
            assert "closed delivery set" in str(e)
    for bad_effort in ("ultra", "none", "", "HIGH"):
        try:
            m._validate_submission("mission-x", {
                "schema_version": 1, "mission_id": "mission-x",
                "type": "worker.upsert", "source": "build1-flow",
                "correlation": {"producer_event_id": f"te:{bad_effort}"},
                "payload": {"worker_id": "w", "status": "done", "effort": bad_effort},
            })
            raise AssertionError(f"effort {bad_effort!r} accepted")
        except m.MissionError as e:
            assert "effort" in str(e)
    # Omitted model/effort backward-compatible; valid values accepted
    m._validate_submission("mission-x", {
        "schema_version": 1, "mission_id": "mission-x",
        "type": "worker.upsert", "source": "build1-flow",
        "correlation": {"producer_event_id": "t:ok"},
        "payload": {"worker_id": "w", "status": "done",
                    "model": "gpt-5.6-sol", "effort": "xhigh"},
    })


def test_failed_mission_shows_telemetry_in_telegram() -> None:
    v = _view(goal="G", status="failed", error="CI failed", workers=[
        {"worker_id": "author", "status": "completed", "profile": "author",
         "model": "gpt-5.6-sol", "effort": "high", "input_tokens": 100, "output_tokens": 50},
    ])
    text = m.telegram_text(v)
    assert "\u0410\u0432\u0442\u043e\u0440 (\u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d): gpt-5.6-sol" in text
    assert "100 in / 50 out" in text
    assert "\u043f\u0440\u043e\u0439\u0434\u0435\u043d\u044b" not in text
    assert "\u0410\u0432\u0442\u043e\u0440 (" not in m.telegram_text(
        _view(goal="G", status="failed", error="err", workers=[]))


def test_telemetry_workers_do_not_satisfy_completion_ready() -> None:
    base = dict(
        goal="G", status="active", stage="verifying", progress_percent=90,
        tasks=[{"task_id": "t1", "title": "T", "status": "done"}],
        gates=[{"gate_id": g, "status": "passed"}
               for g in ("tests", "review", "ci", "post-verify", "cleanup")],
        deliveries=[
            {"kind": "pull_request", "status": "merged", "url": "https://x/pr/1"},
            {"kind": "default_branch", "status": "verified", "url": "https://x/c/1"},
            {"kind": "delivery", "status": "not_applicable"},
        ],
        delivery_mode="none",
    )
    telemetry = [
        {"worker_id": "author", "status": "completed", "profile": "author", "model": "gpt-5.6-sol"},
        {"worker_id": "reviewer", "status": "completed", "profile": "reviewer", "model": "gpt-5.6-terra"},
    ]
    # Canonical + telemetry → ready
    assert m.completion_ready(_view(**base, workers=[
        {"worker_id": "t1:run:1", "status": "completed"}, *telemetry,
    ]))
    # Telemetry alone → NOT ready
    assert not m.completion_ready(_view(**base, workers=telemetry))
    # Legacy scheduled retry + telemetry → ready
    assert m.completion_ready(_view(**base, workers=[
        {"worker_id": "t1:run:1", "status": "scheduled"},
        {"worker_id": "t1:run:2", "status": "completed"}, *telemetry,
    ]))
