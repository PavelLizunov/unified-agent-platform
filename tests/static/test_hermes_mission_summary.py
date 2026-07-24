"""Owner-readable summary projection: focused behavior tests."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from unittest import mock

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


def _worker(profile: str, model: str | None = None, **metrics) -> dict:
    """Build one bounded author/reviewer/usage telemetry worker record."""
    worker = {"worker_id": profile, "status": "completed", "profile": profile}
    if model is not None:
        worker["model"] = model
    worker.update(metrics)
    return worker


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


def test_active_telegram_has_workspace_link_progress_and_honest_usage_scope() -> None:
    view = _view(
        mission_id=MID,
        project_label="Suflyor",
        status="active",
        stage="testing",
        progress_percent=50,
        notice={
            "code": "progress_detail",
            "message": "Черновик PR проходит обязательный CI.",
            "owner_action_required": False,
            "phase": "candidate_pr_open",
            "cycle": 2,
            "cycle_limit": 8,
            "url": "https://github.com/Owner/repo/pull/23",
        },
        workers=[
            {
                "worker_id": "author",
                "status": "completed",
                "profile": "author",
                "model": "gpt-5.6-sol",
                "input_tokens": 2_292_409,
                "cached_input_tokens": 2_156_544,
                "output_tokens": 15_025,
                "model_requests": 37,
                "attempts_discarded": 1,
            },
            {
                "worker_id": "usage-total",
                "status": "completed",
                "profile": "usage",
                "input_tokens": 2_292_409,
                "cached_input_tokens": 2_156_544,
                "output_tokens": 15_025,
                "model_requests": 37,
                "attempts_discarded": 3,
            },
        ],
    )
    with mock.patch.dict(
        "os.environ",
        {"HERMES_MISSION_WORKSPACE_URL": "http://100.85.56.31:3000"},
        clear=False,
    ):
        text = m.telegram_text(view)
    assert f"http://100.85.56.31:3000/dashboard?mission={MID}" in text
    assert "Цикл: 2 из 8" in text
    assert "https://github.com/Owner/repo/pull/23" in text
    assert "Накопительный подтверждённый расход: вход 2,29 млн" in text
    assert "Автор (последний завершённый прогон): gpt-5.6-sol" in text
    assert "как минимум 3 предыдущих или отброшенных прогонов не входят" in text


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
    deployed = m._completion_result(_view(
        goal="G", status="completed", delivery_mode="deploy",
        deliveries=[{
            "kind": "deployment", "status": "verified",
            "environment": "vpnctl-production", "deployed_revision": "a" * 40,
        }],
    ))
    assert "\u0414\u0435\u043f\u043b\u043e\u0439: vpnctl-production" in deployed
    # compact(revision, 12) keeps 11 chars + ellipsis; the verified marker is shown.
    assert "aaaaaaaaaaa\u2026" in deployed and "\u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d" in deployed


def test_completion_uses_delivery_summary_and_never_echoes_goal() -> None:
    goal = "A very long owner request that is not a completion answer"
    summary = "Исправлены русские склонения; число 14 подтверждено тестом."
    result = m._completion_result(_view(
        goal=goal,
        status="completed",
        deliveries=[{
            "kind": "pull_request", "status": "merged",
            "url": "https://example.invalid/pr/1", "summary": summary,
        }],
    ))
    assert result.startswith(summary)
    assert goal not in result
    fallback = m._completion_result(_view(goal=goal, status="completed"))
    assert "подробное описание результата недоступно" in fallback
    assert goal not in fallback


def test_delivery_summary_schema_is_closed_and_bounded() -> None:
    base = {
        "schema_version": 1, "mission_id": "mission-x",
        "type": "delivery.upsert", "source": "build1-flow",
        "correlation": {"producer_event_id": "summary:test"},
        "payload": {
            "kind": "pull_request", "status": "merged",
            "url": "https://example.invalid/pr/1", "summary": "Короткий итог",
        },
    }
    m._validate_submission("mission-x", base)
    for summary in ("x" * 701, "две\nстроки", "", 42):
        invalid = {**base, "payload": {**base["payload"], "summary": summary}}
        try:
            m._validate_submission("mission-x", invalid)
            raise AssertionError("invalid summary was accepted")
        except m.MissionError as error:
            assert "summary" in str(error)
    wrong_kind = {
        **base,
        "payload": {**base["payload"], "kind": "default_branch"},
    }
    try:
        m._validate_submission("mission-x", wrong_kind)
        raise AssertionError("summary on a non-PR delivery was accepted")
    except m.MissionError as error:
        assert "delivery summary" in str(error)


def test_completion_elapsed_from_updated_at() -> None:
    v = _view(goal="G", status="completed",
              started_at="2026-07-21T10:00:00.000Z", updated_at="2026-07-21T11:30:00.000Z")
    assert "1\u0447 30\u043c" in m._completion_result(v)
    assert "\u0412\u0440\u0435\u043c\u044f:" not in m._completion_result(_view(goal="G", status="completed"))


def test_completion_role_telemetry_usage_and_unattested_cost() -> None:
    v = _view(goal="G", status="completed", workers=[
        _worker("author", "gpt-5.6-sol", effort="xhigh",
                input_tokens=8419465, cached_input_tokens=8159232,
                output_tokens=21094, reasoning_output_tokens=11403,
                model_requests=60, command_calls=47, failed_commands=9,
                web_search_calls=4),
        _worker("reviewer", "gpt-5.6-terra", effort="xhigh",
                input_tokens=1645218, cached_input_tokens=1517056,
                output_tokens=9627, reasoning_output_tokens=6213,
                model_requests=21, command_calls=17, failed_commands=4,
                web_search_calls=2),
    ])
    r = m._completion_result(v)
    assert "Автор (финальный прогон): gpt-5.6-sol · effort xhigh" in r
    assert "Ревьюер (финальный прогон): gpt-5.6-terra · effort xhigh" in r
    assert "Статистика финальных прогонов: вход 10,06 млн" in r
    assert "runtime-кэш (подтверждено runtime, не биллинг) 9,68 млн (96,1%)" in r
    assert "новый вход 388,4 тыс." in r
    assert "выход 30,7 тыс." in r
    assert "запросы к моделям 81" in r
    assert "Инструменты: shell 64 · ненулевой код 13 · web search 6" in r
    # No attested official price contract -> cost is reported as not attested,
    # never an invented API-equivalent.
    assert m._COST_UNATTESTED in r
    assert "API-эквивалент" not in r and "$" not in r
    r2 = m._completion_result(_view(goal="G", status="completed",
                                    workers=[{"worker_id": "w", "status": "done"}]))
    assert "Автор (" not in r2
    assert "Статистика финальных прогонов:" not in r2


def test_completion_keeps_usage_statistics_when_details_are_truncated() -> None:
    v = _view(
        goal="G", status="completed",
        deliveries=[
            {"kind": "pull_request", "status": "merged", "summary": "S" * 700,
             "url": "https://example.test/pr/" + "p" * 600},
            {"kind": "default_branch", "status": "verified",
             "url": "https://example.test/commit/" + "c" * 600},
        ],
        changes=[{"path": f"src/{index:02d}-{'x' * 110}.py"} for index in range(20)],
        workers=[
            _worker("author", "gpt-5.6-sol", effort="high", input_tokens=1000,
                    cached_input_tokens=800, output_tokens=100, model_requests=2),
            _worker("reviewer", "gpt-5.6-terra", effort="high", input_tokens=500,
                    cached_input_tokens=400, output_tokens=50, model_requests=1),
        ],
    )
    result = m._completion_result(v)
    assert len(result) <= m._MAX_COMPLETION_RESULT_CHARS
    assert "Статистика финальных прогонов:" in result
    assert m._COST_UNATTESTED in result


def test_completion_partial_telemetry_preserves_roles_and_never_prices() -> None:
    partial = _view(goal="G", status="completed", workers=[
        _worker("author", "gpt-5.6-sol", input_tokens=100, output_tokens=20),
        _worker("reviewer", "gpt-5.6-terra"),
    ])
    partial_result = m._completion_result(partial)
    # Per-role statistics survive even when one role lacks telemetry...
    assert "Автор (финальный прогон): gpt-5.6-sol · 100 in / 20 out" in partial_result
    assert "Ревьюер (финальный прогон): gpt-5.6-terra" in partial_result
    # ...but the aggregate total/cache/cost is explicitly unavailable, never invented.
    assert "Статистика финальных прогонов: совокупный расход, кэш и API-стоимость недоступны" in partial_result
    assert "API-эквивалент" not in partial_result
    assert "вход 100" not in partial_result

    # A large single run is ordinary attested telemetry: tokens + runtime-reported
    # cache are shown, but cost is never priced (no attested official price).
    large = _view(goal="G", status="completed", workers=[
        _worker("author", "gpt-5.6-sol", input_tokens=300000,
                cached_input_tokens=250000, output_tokens=1000, model_requests=1),
    ])
    rendered = m._completion_result(large)
    assert "Статистика финальных прогонов:" in rendered
    assert "runtime-кэш (подтверждено runtime, не биллинг) 250 тыс. (83,3%)" in rendered
    assert m._COST_UNATTESTED in rendered
    assert "API-эквивалент" not in rendered and "$" not in rendered


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


def test_usage_total_aggregate_is_telemetry_not_canonical() -> None:
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
    role_telemetry = [
        {"worker_id": "author", "status": "completed", "profile": "author", "model": "gpt-5.6-sol"},
        {"worker_id": "reviewer", "status": "completed", "profile": "reviewer", "model": "gpt-5.6-terra"},
    ]
    usage_total = {"worker_id": "usage-total", "status": "completed", "profile": "usage"}
    canonical = {"worker_id": "coordinator-codex-auto-a7", "status": "completed",
                 "profile": "coordinator-codex-auto-a7"}
    # Exact observed event order: author, reviewer, usage-total, canonical → ready
    assert m.completion_ready(_view(**base, workers=[
        *role_telemetry, usage_total, canonical,
    ]))
    # Wrong worker_id with profile=usage stays canonical → fail-closed
    wrong_id = {"worker_id": "usage-detail", "status": "completed", "profile": "usage"}
    assert not m.completion_ready(_view(**base, workers=[
        *role_telemetry, wrong_id, canonical,
    ]))
    # Wrong profile with worker_id=usage-total stays canonical → fail-closed
    wrong_profile = {"worker_id": "usage-total", "status": "completed", "profile": "usage-detail"}
    assert not m.completion_ready(_view(**base, workers=[
        *role_telemetry, wrong_profile, canonical,
    ]))


def _stage(stage: str, progress: int, occurred_at: str, seq: int) -> dict:
    return {
        "schema_version": 1, "mission_id": MID, "type": "mission.stage",
        "source": "central-hermes", "correlation": {"producer_event_id": f"t:s{seq}"},
        "payload": {"stage": stage, "progress_percent": progress},
        "sequence": seq, "event_id": f"{MID}:{seq}", "occurred_at": occurred_at,
    }


def test_role_telemetry_exposes_attested_per_role_details() -> None:
    workers = [
        _worker("author", "gpt-5.6-sol", effort="xhigh",
                input_tokens=8_419_465, cached_input_tokens=8_159_232,
                output_tokens=21_094, reasoning_output_tokens=11_403,
                model_requests=60, attempts_discarded=2),
    ]
    lines = m._role_telemetry_lines(workers)
    assert len(lines) == 1
    line = lines[0]
    assert "Автор (финальный прогон): gpt-5.6-sol" in line
    assert "effort xhigh" in line
    assert "8419465 in / 21094 out" in line
    assert "кэш 8159232" in line
    assert "reasoning 11403" in line
    assert "запросов 60" in line
    assert "отброшено 2" in line


def test_role_telemetry_omits_unattested_per_role_details() -> None:
    workers = [_worker("author", "gpt-5.6-sol", input_tokens=100, output_tokens=50)]
    line = m._role_telemetry_lines(workers)[0]
    assert "100 in / 50 out" in line
    assert "кэш" not in line
    assert "reasoning" not in line
    assert "запросов" not in line
    assert "отброшено" not in line


def test_active_telegram_elapsed_is_deterministic_across_replay() -> None:
    events = [
        _accepted(goal="Implement the feature", occurred_at="2026-07-21T10:00:00.000Z"),
        _stage("testing", 50, "2026-07-21T11:30:00.000Z", 2),
    ]
    view = m.project(events)
    assert view["status"] == "active"
    text = m.telegram_text(view)
    assert "В работе: 1ч 30м" in text
    # Restart/replay projects the identical view and text — no duplicate semantics.
    replayed = m.project(events)
    assert replayed["projection_id"] == view["projection_id"]
    assert m.telegram_text(replayed) == text
    # A completed mission reports total duration in the result, not the active line.
    done = _view(goal="G", status="completed",
                 started_at="2026-07-21T10:00:00.000Z",
                 updated_at="2026-07-21T11:30:00.000Z")
    assert "В работе:" not in m.telegram_text(done)


def test_usage_statistics_honest_markers() -> None:
    """Cache ratio only from attested input+cached; cost is never invented."""
    cases = [
        # name, workers, must_contain, must_not_contain
        ("cache not attested -> explicit cache marker, cost unattested",
         [_worker("author", "gpt-5.6-sol", input_tokens=5000, output_tokens=100,
                  model_requests=3)],
         ["вход 5 тыс.", "runtime-кэш: недоступно", m._COST_UNATTESTED],
         ["API-эквивалент", "$"]),
        ("fully attested -> runtime cache ratio + unattested cost, never a price",
         [_worker("author", "gpt-5.6-sol", input_tokens=5000, cached_input_tokens=4000,
                  output_tokens=100, model_requests=3)],
         ["runtime-кэш (подтверждено runtime, не биллинг) 4 тыс. (80,0%)",
          "новый вход 1 тыс.", m._COST_UNATTESTED],
         ["недоступно", "API-эквивалент", "$"]),
        ("one role missing telemetry -> aggregate unavailable, discarded preserved",
         [_worker("author", "gpt-5.6-sol", input_tokens=5000, cached_input_tokens=4000,
                  output_tokens=100, attempts_discarded=2),
          _worker("reviewer", "gpt-5.6-terra")],
         ["Статистика финальных прогонов: совокупный расход, кэш и API-стоимость недоступны",
          "как минимум 2 предыдущих или отброшенных прогонов не входят"],
         ["API-эквивалент", "вход ", "$"]),
        ("cumulative usage profile also emits the unattested-cost line",
         [_worker("usage", None, input_tokens=5000, cached_input_tokens=4000,
                  output_tokens=100, model_requests=3)],
         ["Накопительный подтверждённый расход",
          "runtime-кэш (подтверждено runtime, не биллинг) 4 тыс. (80,0%)",
          m._COST_UNATTESTED],
         ["API-эквивалент", "$"]),
    ]
    for name, workers, must_contain, must_not in cases:
        joined = "\n".join(m._usage_statistics_lines(workers))
        for needle in must_contain:
            assert needle in joined, (name, needle)
        for needle in must_not:
            assert needle not in joined, (name, needle)
    # Per-role lines preserve each role's attested details independently.
    role_lines = m._role_telemetry_lines([
        _worker("author", "gpt-5.6-sol", input_tokens=5000, cached_input_tokens=4000,
                output_tokens=100, attempts_discarded=2),
        _worker("reviewer", "gpt-5.6-terra"),
    ])
    assert "Автор (финальный прогон): gpt-5.6-sol · 5000 in / 100 out" in role_lines[0]
    assert "кэш 4000" in role_lines[0]
    assert role_lines[1] == "Ревьюер (финальный прогон): gpt-5.6-terra"
    # No telemetry at all -> empty here; the active view adds the "becomes
    # available after an attested run" line (covered in the active-update test).
    assert m._usage_statistics_lines([{"worker_id": "w", "status": "done"}]) == []


def test_active_telegram_generic_update_fields() -> None:
    """Current operation, durable checkpoint, wait reason and owner action."""
    cases = [
        # name, view kwargs, must_contain, must_not_contain
        ("running task + mapped checkpoint phase, no owner wait",
         dict(status="active", stage="implementing", progress_percent=40, sequence=5,
              tasks=[{"task_id": "t1", "title": "  Refactor   the router ",
                      "status": "running"}],
              notice={"code": "progress_detail", "message": "Открываю черновик PR.",
                      "owner_action_required": False, "phase": "candidate_pr_open"}),
         ["Сейчас: Внесение изменений — Refactor the router",
          "Контрольная точка: Внесение изменений · durable-событие 5 · открыт черновик PR",
          "Ждёт: причина ожидания ещё не записана, жду следующей автоматической контрольной точки",
          "Нужно ваше действие: нет"],
         ["Ждёт: вашего ответа", "candidate_pr_open"]),
        ("pending question is the wait reason and requires owner action",
         dict(status="waiting_owner", stage="reviewing", sequence=9,
              question={"question_id": "q1", "text": "Продолжать?"}),
         ["Сейчас: Независимая проверка",
          "Контрольная точка: Независимая проверка · durable-событие 9",
          "Ждёт: вашего ответа на вопрос",
          "Нужно ваше действие: да"],
         []),
        ("bounded capacity-wait notice names the wait reason",
         dict(status="active", stage="implementing", sequence=3,
              notice={"code": "capacity_wait", "message": "занято",
                      "owner_action_required": False}),
         ["Ждёт: освобождения модели OpenAI", "Нужно ваше действие: нет"],
         []),
    ]
    for name, kw, must_contain, must_not in cases:
        text = m.telegram_text(_view(mission_id=MID, **kw))
        for needle in must_contain:
            assert needle in text, (name, needle)
        for needle in must_not:
            assert needle not in text, (name, needle)
    # Checkpoint is shown for EVERY active mission and never exposes a raw phase
    # id alone: an unmapped phase is omitted, stage + sequence remain.
    unmapped = m.telegram_text(_view(
        mission_id=MID, status="active", stage="testing", sequence=7,
        notice={"code": "x", "message": "m", "owner_action_required": False,
                "phase": "totally_unknown_phase"}))
    assert "Контрольная точка: Автоматические проверки · durable-событие 7" in unmapped
    assert "totally_unknown_phase" not in unmapped
    # Terminal missions show no generic active-update block.
    done = m.telegram_text(_view(goal="G", status="completed", stage="complete"))
    assert "Сейчас:" not in done and "Нужно ваше действие:" not in done
    # Active mission with no telemetry yet -> explicit "becomes available" line.
    bare = m.telegram_text(_view(mission_id=MID, status="active", stage="testing",
                                 sequence=2, workers=[]))
    assert "подтверждённый usage появится после" in bare
    # Unknown stage falls back to the localized generic label in the active-update
    # block, never the raw id (the legacy "Этап:" line echoes the stage and is out
    # of scope here).
    unknown = m.telegram_text(_view(mission_id=MID, status="active",
                                    stage="some_internal_stage", sequence=4))
    assert "Сейчас: Выполнение" in unknown
    assert "Контрольная точка: Выполнение · durable-событие 4" in unknown
    assert "Сейчас: some_internal_stage" not in unknown
    assert "Контрольная точка: some_internal_stage" not in unknown
    # Active mission without timestamps -> no invented elapsed line.
    no_ts = m.telegram_text(_view(mission_id=MID, status="active", stage="testing",
                                  sequence=1))
    assert "В работе:" not in no_ts


def test_telegram_deep_link_is_exact_and_optional() -> None:
    view = _view(mission_id=MID, project_label="UAP", status="active", stage="testing")
    with mock.patch.dict(
        "os.environ", {"HERMES_MISSION_WORKSPACE_URL": "http://100.85.56.31:3000"}, clear=False,
    ):
        text = m.telegram_text(view)
    assert f"Подробнее: http://100.85.56.31:3000/dashboard?mission={MID}" in text
    # No configured Workspace base -> no invented link.
    with mock.patch.dict("os.environ", {}, clear=True):
        assert "Подробнее:" not in m.telegram_text(view)
    # Trailing slash is normalized; an unsafe scheme is rejected.
    with mock.patch.dict(
        "os.environ", {"HERMES_MISSION_WORKSPACE_URL": "https://ws.example/"}, clear=False,
    ):
        assert f"Подробнее: https://ws.example/dashboard?mission={MID}" in m.telegram_text(view)
    with mock.patch.dict(
        "os.environ", {"HERMES_MISSION_WORKSPACE_URL": "javascript:alert(1)"}, clear=False,
    ):
        assert "Подробнее:" not in m.telegram_text(view)


def test_long_goal_and_result_are_bounded() -> None:
    long_goal = "repair " * 100
    view = m.project([_accepted(goal=long_goal)])
    text = m.telegram_text(view)
    goal_line = next(line for line in text.splitlines() if line.startswith("Цель:"))
    assert len(goal_line) <= len("Цель: ") + 120
    assert goal_line.endswith("…")

    long_summary = "S" * 5000
    result = m._completion_result(_view(
        goal="G", status="completed",
        deliveries=[{"kind": "pull_request", "status": "merged", "summary": long_summary}],
    ))
    assert len(result) <= m._MAX_COMPLETION_RESULT_CHARS


def test_duplicate_producer_event_is_idempotent_in_projection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = m.MissionStore(Path(temp) / "m.sqlite3")
        store.accept("Goal", mission_id="mission-dup", project_label="UAP")
        event = {
            "schema_version": 1, "mission_id": "mission-dup",
            "type": "worker.upsert", "source": "build1-flow",
            "correlation": {"producer_event_id": "dup:w1"},
            "payload": {"worker_id": "author", "status": "completed", "profile": "author",
                        "model": "gpt-5.6-sol", "input_tokens": 100, "output_tokens": 50},
        }
        store.append_producer("mission-dup", event)
        first = store.projection("mission-dup")
        store.append_producer("mission-dup", event)  # duplicate replay
        second = store.projection("mission-dup")
        assert first["projection_id"] == second["projection_id"]
        assert len(second["workers"]) == 1
        assert m.telegram_text(first) == m.telegram_text(second)


def main() -> None:
    test_headline_telegram_text_and_backward_compat()
    test_active_telegram_has_workspace_link_progress_and_honest_usage_scope()
    test_completion_gates_deploy_and_fail_closed()
    test_completion_uses_delivery_summary_and_never_echoes_goal()
    test_delivery_summary_schema_is_closed_and_bounded()
    test_completion_elapsed_from_updated_at()
    test_completion_role_telemetry_usage_and_unattested_cost()
    test_completion_keeps_usage_statistics_when_details_are_truncated()
    test_completion_partial_telemetry_preserves_roles_and_never_prices()
    test_store_end_to_end_label_telemetry_timestamps()
    test_model_and_effort_validation()
    test_failed_mission_shows_telemetry_in_telegram()
    test_telemetry_workers_do_not_satisfy_completion_ready()
    test_usage_total_aggregate_is_telemetry_not_canonical()
    test_role_telemetry_exposes_attested_per_role_details()
    test_role_telemetry_omits_unattested_per_role_details()
    test_active_telegram_elapsed_is_deterministic_across_replay()
    test_usage_statistics_honest_markers()
    test_active_telegram_generic_update_fields()
    test_telegram_deep_link_is_exact_and_optional()
    test_long_goal_and_result_are_bounded()
    test_duplicate_producer_event_is_idempotent_in_projection()


if __name__ == "__main__":
    main()
