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


_TASK_OWNER_GATE_POSITIVES = {
    "architecture_change": (
        "Replace the accepted architecture and update ADR-031",
        "Modify the accepted architecture",
        "Refactor the authority boundary",
        "Implement a new source of truth",
        "Configure a new cluster topology",
        "Move the authoritative mission state from Central to the worker",
        "Change the accepted security boundary in ADR-031",
        "Замени принятую архитектуру и обнови ADR-031",
        "Перенеси authoritative mission state из Central в worker",
        "Измени принятую security boundary в ADR-031",
        "Update README only to replace the accepted architecture in ADR-031",
    ),
    "destructive": (
        "Delete the production database and all customer records",
        "Remove the production database now",
        "Reset the production k3s cluster",
        "Purge the persistent production volume",
        "Удали production базу данных со всеми записями",
        "Сбрось production кластер k3s",
        "Очисти persistent production volume",
    ),
    "credentials_or_external_authority": (
        "Create a new GitHub write token for the worker",
        "Add a GitHub write token",
        "Implement admin access for the worker",
        "Add RBAC permissions",
        "Grant the delivery worker cluster-admin permissions",
        "Grant cluster-admin, then configure the RBAC validator test",
        "Rotate the production API key",
        "Создай новый GitHub write token для worker",
        "Выдай delivery worker права cluster-admin",
        "Ротируй production API key",
    ),
    "new_provider": (
        "Add Anthropic as a new model provider",
        "Anthropic should become the new model provider; integrate it",
        "Configure Anthropic as a model provider",
        "Build an OpenRouter model provider",
        "Implement support for Gemini as a provider",
        "Create a Qwen model provider integration",
        "Switch autonomous delivery from OpenAI to OpenRouter",
        "Integrate Claude into autonomous delivery",
        "Добавь Anthropic как нового model provider",
        "Переключи autonomous delivery с OpenAI на OpenRouter",
        "Интегрируй Claude в autonomous delivery",
    ),
    "local_or_gpu": (
        "Enable Ollama local inference for autonomous delivery",
        "Add Ollama local inference",
        "Integrate Ollama local inference",
        "Implement a CUDA GPU worker",
        "Build an RTX inference worker",
        "Create a local model worker",
        "Run the coding worker on a CUDA GPU",
        "Deploy a local model on the RTX GPU",
        "Включи локальный inference через Ollama для autonomous delivery",
        "Запускай coding worker на CUDA GPU",
        "Разверни локальную модель на RTX GPU",
    ),
}

_TASK_OWNER_GATE_FALSE_POSITIVES = (
    "Fix a typo in docs/architecture.md",
    "Add a link to ADR-031 in README",
    "Remove an unused import from the token parser",
    "Remove the obsolete test fixture",
    "Add a regression test for credential redaction",
    "Update README with the OPENAI_API_KEY environment-variable name",
    "Add a negative test for rejected Claude routing",
    "Remove the obsolete Ollama paragraph from README",
    "Add dry-run coverage to the cleanup command",
    "Create a fake secret fixture for unit tests",
    "Configure the RBAC validator test",
    "Add an Anthropic provider mock for unit tests",
    "Add unit-test coverage for the mocked GPU path",
    "Remove Claude provider support",
    "Remove the obsolete Ollama fallback",
    "Remove cluster-admin access from the worker",
    "Update docs: delete the production database instructions from README",
    "Исправь опечатку в docs/architecture.md",
    "Добавь ссылку на ADR-031 в README",
    "Удали неиспользуемый import из token parser",
    "Удали устаревшую test fixture",
    "Добавь regression test для credential redaction",
    "Обнови README, указав имя переменной OPENAI_API_KEY",
    "Добавь negative test для отклонённого Claude routing",
    "Удали устаревший абзац про Ollama из README",
    "Добавь dry-run coverage для cleanup command",
    "Создай fake secret fixture для unit tests",
    "Настрой RBAC validator test",
    "Добавь Anthropic provider mock для unit tests",
    "Добавь unit-test coverage для mocked GPU path",
    "Удали поддержку Claude provider",
    "Удали устаревший Ollama fallback",
    "Удали cluster-admin доступ у worker",
    "Обнови docs: удали инструкции по production database из README",
)

_TASK_OWNER_GATE_MIXED_SAFE_AND_PROTECTED = {
    "credentials_or_external_authority": (
        "Create a fake secret fixture for unit tests, then rotate the production API key"
    ),
    "destructive": (
        "Update docs: delete production database instructions from README, "
        "then reset the production cluster"
    ),
    "local_or_gpu": (
        "Add a mocked GPU path test, then deploy an Ollama local model"
    ),
    "new_provider": (
        "Add an Anthropic provider mock for tests, then switch delivery to OpenRouter"
    ),
}


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


def test_conversational_admission_requires_explicit_execution_intent() -> None:
    for discussion in (
        "Посмотри сценарий и скажи, можем ли мы это интегрировать в суфлёр?",
        "Какие риски у настройки этого проекта?",
        "Analyze the repository and tell me how we should integrate this",
        "Find the latest test API documentation",
        "Я вижу, что он запустил CI",
        "Я обновил только README",
        "Почему задача выполняется",
        "I already updated the README",
        "Run tests and report the result",
        "/run Run tests and report the result",
        "/run read-only status",
        "/run тесты",
        "/run статус CI",
        "/run диагностика CI",
        "Read https://example.invalid/spec.md and summarize it",
        (
            "Давай вернёмся к задаче по суфлёру. Найди файл handoff с описанием "
            "тестов и скажи, что ты его нашёл. После этого мы продолжим."
        ),
        "/discuss Настройка проекта",
        "/discuss Задай 3–5 коротких вопросов, которые нужны, чтобы настроить этот проект.",
    ):
        assert not missions.is_execution_goal(discussion), discussion
    for execution in (
        "Интегрируй новую модель в суфлёр",
        "Посмотри сценарий и исправь найденные проблемы",
        "Configure this existing project",
        "Сделай эту интеграцию",
        "Я обновил README, теперь исправь тест",
        "I updated the README, now fix the test",
        "Run tests and fix any failures",
        "Create a regression test and run it",
        "Update the test and run it",
        "Update the README link to https://example.invalid/reference",
        "Update the source URL to https://example.invalid/reference",
        "Implement the plan from https://example.invalid/spec.md",
        "Implement https://example.invalid/spec.md",
        "Build https://example.invalid/spec.md",
        "Implement per https://example.invalid/spec.md",
        "Follow https://example.invalid/spec.md and implement it",
        "Open https://example.invalid/spec.md and implement it",
        "Реализуй план на основе https://example.invalid/handoff.md",
        "/run теперь делаем это",
    ):
        assert missions.is_execution_goal(execution), execution
    assert not missions.is_execution_goal(None)

    for execution in (
        "Посмотри код и внеси правку",
        "Look at the implementation and then update it",
    ):
        assert missions.is_execution_goal(execution), execution
    assert missions.routine_docs_file_limit("Обнови только README") == 2
    assert missions.routine_docs_file_limit("Update README only") == 2
    assert missions.routine_docs_file_limit(
        "По читай handoff и создай себе plan реализации в суфлер репо"
    ) == 1
    assert missions.routine_docs_file_limit(
        "Create an implementation plan and then implement it"
    ) is None
    assert missions.routine_docs_file_limit("Обнови README и код") is None
    assert missions.routine_docs_file_limit("Обнови только README и код") is None
    assert missions.routine_docs_file_limit("Я обновил только README") is None
    assert missions.routine_docs_file_limit("Исправь простой баг") is None


def test_owner_turn_admission_is_authoritative_before_project_routing() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        for index, discussion in enumerate((
            "Какие риски у настройки этого проекта?",
            "Я вижу, что он запустил CI",
            "I already updated the README",
            "Run tests and report the result",
        )):
            try:
                store.ingest_owner_turn(
                    discussion,
                    platform="workspace",
                    source_message_id=f"discussion-{index}",
                    session_id="discussion-session",
                )
                raise AssertionError("discussion was accepted as an execution mission")
            except missions.MissionError as error:
                assert str(error) == "owner turn is not an execution goal"
        assert store.latest() is None

        # A goal that requires a source is admitted as exactly one durable
        # mission (never rejected pre-mission).  A non-GitHub URL source cannot
        # be represented exactly, so it sets source_required and leaves
        # source_request unset; the coordinator raises the idempotent question.
        unresolvable, created = store.ingest_owner_turn(
            "Implement the plan from https://example.invalid/spec.md",
            platform="workspace",
            source_message_id="external-source",
            session_id="external-source-session",
        )
        assert created
        assert unresolvable["payload"].get("source_required") is True
        assert unresolvable["payload"].get("source_request") is None

        # Natural-language source descriptions behave the same: admitted with
        # source_required=True and no exact source_request.
        for index, vague in enumerate((
            "реализуй точно по handoff-файлу ~/handoff/plan.md с ops-1",
            "implement exactly per the design-doc from the vpnrouter repository",
        )):
            assert missions.requires_external_source(vague), vague
            assert missions.parse_source_request(vague) is None, vague
            accepted_vague, created_vague = store.ingest_owner_turn(
                vague,
                platform="workspace",
                source_message_id=f"vague-source-{index}",
                session_id="external-source-session",
            )
            assert created_vague, vague
            assert accepted_vague["payload"].get("source_required") is True, vague
            assert accepted_vague["payload"].get("source_request") is None, vague

        # An exact GitHub source reference is parsed into the immutable
        # source_request (and does not set source_required).
        github_source = (
            "Implement per https://github.com/PavelLizunov/unified-agent-platform/"
            "blob/main/docs/spec.md"
        )
        assert missions.requires_external_source(github_source)
        assert missions.parse_source_request(github_source) == {
            "repo": "PavelLizunov/unified-agent-platform",
            "ref": "main",
            "path": "docs/spec.md",
        }
        accepted_exact, created_exact = store.ingest_owner_turn(
            github_source,
            platform="workspace",
            source_message_id="exact-source",
            session_id="external-source-session",
        )
        assert created_exact
        assert accepted_exact["payload"]["source_request"] == {
            "repo": "PavelLizunov/unified-agent-platform",
            "ref": "main",
            "path": "docs/spec.md",
        }
        assert accepted_exact["payload"].get("source_required") is None

        accepted, created = store.ingest_owner_turn(
            "/run Обнови только README",
            platform="workspace",
            source_message_id="explicit-run",
            session_id="discussion-session",
        )
        assert created
        assert accepted["payload"]["execution_class"] == "routine_docs"


def test_task_owner_gate_classifier_has_closed_ru_en_corpus() -> None:
    assert missions.task_owner_gate_flags(None) == ()
    assert missions.task_owner_gate_flag(None) is None

    for expected, goals in _TASK_OWNER_GATE_POSITIVES.items():
        for goal in goals:
            assert missions.task_owner_gate_flags(goal) == (expected,), goal
            if expected == "architecture_change":
                assert missions.task_owner_gate_flag(goal) == expected, goal
            else:
                try:
                    missions.task_owner_gate_flag(goal)
                    raise AssertionError(f"unsupported task capability was allowed: {goal}")
                except missions.MissionError as error:
                    assert str(error) == (
                        f"task requires separate capability setup: {expected}"
                    )

    mixed = (
        "Delete production data, create a GitHub write token, "
        "add Anthropic as a new provider, "
        "and enable Ollama GPU inference"
    )
    assert missions.task_owner_gate_flags(mixed) == (
        "credentials_or_external_authority",
        "destructive",
        "local_or_gpu",
        "new_provider",
    )
    try:
        missions.task_owner_gate_flag(mixed)
        raise AssertionError("mixed unsupported task capabilities were allowed")
    except missions.MissionError as error:
        assert str(error) == (
            "task requires separate capability setup: "
            "credentials_or_external_authority, destructive, local_or_gpu, new_provider"
        )

    for goal in _TASK_OWNER_GATE_FALSE_POSITIVES:
        assert missions.is_execution_goal(goal), goal
        assert missions.task_owner_gate_flags(goal) == (), goal
        assert missions.task_owner_gate_flag(goal) is None, goal

    for expected, goal in _TASK_OWNER_GATE_MIXED_SAFE_AND_PROTECTED.items():
        assert missions.task_owner_gate_flags(goal) == (expected,), goal
        assert missions.is_execution_goal(goal), goal

    for goal in (
        "Add a link to ADR-031 and a new source of truth",
        "Fix the accepted architecture and a typo in docs/architecture.md",
        "Delete the production database, then remove the obsolete instructions from README",
        "Remove the production database and its instructions from README",
        "Remove production database and documentation instructions from README",
        "Remove production database plus documentation instructions from README",
        "Remove production database & documentation instructions from README",
        "Remove production database as well as documentation instructions from README",
        "Delete prod db instructions, wipe prod db, README",
        "Delete prod db instructions and wipe prod db in README",
        "Delete production database documentation; destroy prod db; docs",
        "Delete production db instructions then wipe prod db README",
        "Delete production database instructions from README and the production database",
        "Remove prod db documentation from docs and the prod db",
        "Delete production database instructions from README plus production data",
        "Delete production database instructions from README, production database, and old comments",
        "Grant RBAC permissions; validator test",
        "Create a fake secret fixture and a production API key",
        "Integrate Claude, then add an Anthropic provider mock test",
        "Integrate Claude and add an Anthropic provider mock test",
        "Integrate Claude plus add an Anthropic provider mock test",
        "Integrate Claude as well as add an Anthropic provider mock test",
        "Integrate Claude also add an Anthropic provider mock test",
        "Add an Anthropic provider mock and OpenRouter as the model provider",
        "Deploy Ollama; then add a mocked GPU path test",
        "Deploy a mocked GPU path and an Ollama local model",
        "I updated README, now delete the production database",
        "We already fixed docs; now grant cluster-admin permissions",
    ):
        assert missions.task_owner_gate_flags(goal), goal
        assert missions.is_execution_goal(goal), goal


def test_task_owner_gate_is_durable_or_rejected_before_mission_acceptance() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    architecture_goals = (
        "Replace the accepted architecture and update ADR-031",
        "Замени принятую архитектуру и обнови ADR-031",
        "Update README only to replace the accepted architecture in ADR-031",
    )
    for index, goal in enumerate(architecture_goals):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
        ):
            path = Path(temp) / "missions.sqlite3"
            store = missions.MissionStore(path)
            accepted, created = store.ingest_owner_turn(
                goal,
                platform="workspace",
                source_message_id=f"architecture-{index}",
                session_id=f"architecture-session-{index}",
            )
            assert created
            assert accepted["payload"]["owner_gate_flag"] == "architecture_change"
            if goal.startswith("Update README only"):
                assert accepted["payload"]["execution_class"] == "routine_docs"
            projection = store.projection(accepted["mission_id"])
            assert projection["owner_gate_flag"] == "architecture_change"

            restarted = missions.MissionStore(path)
            replayed, replay_created = restarted.ingest_owner_turn(
                goal,
                platform="workspace",
                source_message_id=f"architecture-{index}",
                session_id=f"architecture-session-{index}",
            )
            assert not replay_created
            assert replayed == accepted
            assert restarted.projection(accepted["mission_id"]) == projection

    rejected = {
        "destructive": "Delete the production database and all customer records",
        "credentials_or_external_authority": (
            "Create a new GitHub write token for the worker"
        ),
        "new_provider": "Add Anthropic as a new model provider",
        "local_or_gpu": "Enable Ollama local inference for autonomous delivery",
    }
    for index, (flag, goal) in enumerate(rejected.items()):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
        ):
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            try:
                store.ingest_owner_turn(
                    goal,
                    platform="workspace",
                    source_message_id=f"unsupported-{index}",
                    session_id=f"unsupported-session-{index}",
                )
                raise AssertionError(f"unsupported task capability was accepted: {flag}")
            except missions.MissionError as error:
                assert str(error) == (
                    f"task requires separate capability setup: {flag}"
                )
            assert store.latest() is None

    for index, goal in enumerate(_TASK_OWNER_GATE_FALSE_POSITIVES):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
        ):
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            accepted, created = store.ingest_owner_turn(
                goal,
                platform="workspace",
                source_message_id=f"safe-sensitive-word-{index}",
                session_id=f"safe-sensitive-word-session-{index}",
            )
            assert created
            assert "owner_gate_flag" not in accepted["payload"]
            assert store.projection(accepted["mission_id"])["status"] == "active"

    discussion = "Should we integrate Claude as a new provider?"
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        try:
            store.ingest_owner_turn(
                discussion,
                platform="workspace",
                source_message_id="provider-discussion",
                session_id="provider-discussion-session",
            )
            raise AssertionError("provider discussion was accepted as a mission")
        except missions.MissionError as error:
            assert str(error) == "owner turn is not an execution goal"
        assert store.latest() is None

        try:
            store.ingest_owner_goal(
                "Add Anthropic as a new model provider",
                platform="workspace",
                source_message_id="direct-provider-execution",
                session_id="provider-discussion-session",
            )
            raise AssertionError("direct execution path bypassed task risk classification")
        except missions.MissionError as error:
            assert str(error) == (
                "task requires separate capability setup: new_provider"
            )
        assert store.latest() is None

        try:
            store.accept(
                "Forged task capability",
                mission_id="mission-forged-task-capability",
                owner_gate_flag="destructive",
            )
            raise AssertionError("non-architecture owner_gate_flag was persisted")
        except missions.MissionError as error:
            assert str(error) == "invalid mission owner gate flag"
        assert store.latest() is None


def test_routine_docs_class_is_durable_and_closed() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.ingest_owner_goal(
            "Обнови только README",
            platform="workspace",
            source_message_id="routine-docs-1",
            session_id="routine-session",
        )
        assert created
        assert accepted["payload"]["execution_class"] == "routine_docs"
        assert accepted["payload"]["expected_changed_files"] == 2
        projection = store.projection(accepted["mission_id"])
        assert projection["execution_class"] == "routine_docs"
        assert projection["expected_changed_files"] == 2

        replay, replay_created = store.ingest_owner_goal(
            "Обнови только README",
            platform="workspace",
            source_message_id="routine-docs-1",
            session_id="routine-session",
        )
        assert not replay_created and replay == accepted

        ordinary, ordinary_created = store.ingest_owner_goal(
            "Исправь простой баг",
            platform="workspace",
            source_message_id="ordinary-code-1",
            session_id="routine-session",
        )
        assert ordinary_created
        assert "execution_class" not in ordinary["payload"]

        for index, (execution_class, expected_changed_files) in enumerate((
            ("routine_docs", None),
            (None, 2),
            ("routine_docs", 3),
            ("arbitrary", 1),
        )):
            try:
                store.accept(
                    "Invalid execution class",
                    mission_id=f"mission-invalid-class-{index}",
                    execution_class=execution_class,
                    expected_changed_files=expected_changed_files,
                )
                raise AssertionError("invalid mission execution class was accepted")
            except missions.MissionError as error:
                assert "execution class" in str(error)


def test_routine_docs_on_deploy_target_gets_effective_none_mode() -> None:
    """routine_docs intake on a deploy-capable target must accept delivery_mode=none."""
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl",
                "summary": "VPN control daemon", "aliases": ["vpnctl"],
                "dispatch_profile": "build1-vpnctl-registered-v4",
                "delivery_mode": "deploy", "platforms": ["workspace", "telegram"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")

        # routine_docs goal on deploy-capable target → delivery_mode=none
        accepted, created = store.ingest_owner_goal(
            "Обнови только README",
            platform="workspace",
            source_message_id="routine-deploy-1",
            session_id="routine-deploy-session",
            project_id="vpnctl",
        )
        assert created
        assert accepted["payload"]["execution_class"] == "routine_docs"
        assert accepted["payload"]["delivery_mode"] == "none"
        projection = store.projection(accepted["mission_id"])
        assert projection["delivery_mode"] == "none"
        assert projection["execution_class"] == "routine_docs"

        # Idempotent replay returns the same acceptance
        replay, replay_created = store.ingest_owner_goal(
            "Обнови только README",
            platform="workspace",
            source_message_id="routine-deploy-1",
            session_id="routine-deploy-session",
            project_id="vpnctl",
        )
        assert not replay_created
        assert replay == accepted

        # Normal code mission on the same deploy-capable target keeps deploy
        code_accepted, code_created = store.ingest_owner_goal(
            "Исправь баг в маршрутизаторе",
            platform="workspace",
            source_message_id="code-deploy-1",
            session_id="routine-deploy-session",
            project_id="vpnctl",
        )
        assert code_created
        assert "execution_class" not in code_accepted["payload"]
        assert code_accepted["payload"]["delivery_mode"] == "deploy"

        # New routine_docs acceptance requires the exact effective none mode.
        for index, invalid_mode in enumerate((None, "deploy")):
            try:
                store.accept(
                    "Обнови только README",
                    mission_id=f"mission-invalid-routine-mode-{index}",
                    execution_class="routine_docs",
                    expected_changed_files=2,
                    delivery_mode=invalid_mode,
                )
                raise AssertionError("invalid routine_docs delivery mode was accepted")
            except missions.MissionError as error:
                assert "routine_docs" in str(error)

    # Historical terminal events remain readable after the stricter new admission.
    historical_id = "mission-historical-routine-deploy"
    historical = missions._validate_submission(historical_id, {
        "schema_version": missions.SCHEMA_VERSION,
        "mission_id": historical_id,
        "type": "mission.accepted",
        "source": "central-hermes",
        "correlation": {},
        "payload": {
            "goal": "Legacy documentation mission",
            "delivery_mode": "deploy",
            "execution_class": "routine_docs",
            "expected_changed_files": 2,
        },
    })
    historical.update(sequence=1, occurred_at="2026-07-01T00:00:00Z")
    terminal = {
        "schema_version": missions.SCHEMA_VERSION,
        "mission_id": historical_id,
        "sequence": 2,
        "type": "mission.completed",
        "source": "central-hermes",
        "correlation": {},
        "payload": {"result": "Legacy completion"},
        "occurred_at": "2026-07-01T00:01:00Z",
    }
    historical_view = missions.project([historical, terminal])
    assert historical_view["status"] == "completed"
    assert historical_view["delivery_mode"] == "deploy"

    # Terminal wording for routine_docs shows documentation-only
    result_text = missions._completion_result({
        "delivery_mode": "none",
        "execution_class": "routine_docs",
    })
    assert "не требуется" in result_text
    assert "документации" in result_text

    # Normal none mission keeps the original wording
    normal_text = missions._completion_result({"delivery_mode": "none"})
    assert "не настроен" in normal_text


def test_source_request_is_immutable_and_survives_project_selection() -> None:
    # Target project is Suflyor; the goal hints a source in local-llm-lab.  The
    # parsed source_request must be preserved verbatim (it can never silently
    # switch to the target repo) and replayed deterministically.
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "suflyor", "label": "Suflyor",
                "repository": "PavelLizunov/suflyor",
                "summary": "Prompter", "aliases": ["suflyor"],
                "dispatch_profile": "build1-suflyor-registered-v4",
                "delivery_mode": "none", "platforms": ["workspace"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
            {
                "project_id": "local-llm-lab", "label": "Local LLM Lab",
                "repository": "PavelLizunov/local-llm-evaluation-lab",
                "summary": "LLM lab", "aliases": ["llm lab"],
                "dispatch_profile": None,
                "delivery_mode": "none", "platforms": ["workspace"],
                "category": "research", "status": "setup_required",
                "test_targets": ["desktop-m922ij2"],
            },
        ],
    })
    goal = (
        "Implement per https://github.com/PavelLizunov/local-llm-evaluation-lab/"
        "blob/main/spec.md"
    )
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.ingest_owner_turn(
            goal,
            platform="workspace",
            source_message_id="source-replay",
            session_id="source-replay-session",
            project_id="suflyor",
        )
        assert created
        # Target is Suflyor, but the immutable source request keeps local-llm-lab.
        assert accepted["payload"]["project_id"] == "suflyor"
        assert accepted["payload"]["source_request"] == {
            "repo": "PavelLizunov/local-llm-evaluation-lab",
            "ref": "main",
            "path": "spec.md",
        }
        projection = store.projection(accepted["mission_id"])
        assert projection["source_request"]["repo"] == (
            "PavelLizunov/local-llm-evaluation-lab"
        )

        # Replay of the exact same turn is idempotent and preserves the source.
        replayed, replay_created = store.ingest_owner_turn(
            goal,
            platform="workspace",
            source_message_id="source-replay",
            session_id="source-replay-session",
            project_id="suflyor",
        )
        assert not replay_created
        assert replayed["payload"]["source_request"] == (
            accepted["payload"]["source_request"]
        )

        # Reusing the same source identity with a different (switched) source is
        # rejected as a collision; the source can never be silently swapped.
        switched = (
            "Implement per https://github.com/PavelLizunov/suflyor/blob/main/spec.md"
        )
        try:
            store.ingest_owner_turn(
                switched,
                platform="workspace",
                source_message_id="source-replay",
                session_id="source-replay-session",
                project_id="suflyor",
            )
            raise AssertionError("switched source was accepted on replay")
        except missions.MissionError as error:
            assert "already accepted" in str(error)


def test_fresh_direct_accept_derives_source_request() -> None:
    # P1-C: a fresh direct MissionStore.accept (the producer/API path) must not
    # create a mission with an exact GitHub source URL but source_request=None;
    # the source_request is derived centrally from the accepted goal.
    goal = (
        "Implement per https://github.com/PavelLizunov/unified-agent-platform/"
        "blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/docs/spec.md"
    )
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": ""}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.accept(
            goal,
            mission_id="mission-direct-source",
            dispatch_profile="build1-direct",
        )
        assert created
        assert accepted["payload"]["source_request"] == {
            "repo": "PavelLizunov/unified-agent-platform",
            "ref": "a" * 40,
            "path": "docs/spec.md",
        }
        assert accepted["payload"].get("source_required") is None

        # A fresh accept of a required-but-unrepresentable source sets
        # source_required and leaves source_request unset.
        vague, vague_created = store.accept(
            "implement exactly per the handoff file ~/handoff/plan.md",
            mission_id="mission-direct-vague",
            dispatch_profile="build1-direct",
        )
        assert vague_created
        assert vague["payload"].get("source_required") is True
        assert vague["payload"].get("source_request") is None


def test_legacy_pre_feature_accept_replays_without_collision() -> None:
    # P1-C: a mission accepted before this feature (stored without
    # source_request/source_required) replays deterministically and is never
    # silently retrofitted or collided when the same goal is accepted again.
    goal = (
        "Implement per https://github.com/PavelLizunov/unified-agent-platform/"
        "blob/main/docs/spec.md"
    )
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": ""}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-legacy-source"
        # Simulate a pre-feature accepted event: no source_request/source_required.
        store._append(mission_id, {
            "schema_version": missions.SCHEMA_VERSION,
            "mission_id": mission_id,
            "type": "mission.accepted",
            "source": "central-hermes",
            "correlation": {},
            "payload": {"goal": goal, "dispatch_profile": "build1-legacy"},
        })
        replayed, created = store.accept(
            goal, mission_id=mission_id, dispatch_profile="build1-legacy",
        )
        assert not created
        # The stored legacy event is returned verbatim: no retrofit.
        assert replayed["payload"].get("source_request") is None
        assert replayed["payload"].get("source_required") is None
        assert store.projection(mission_id)["source_request"] is None


def test_owner_visible_terminal_result_carries_source_provenance() -> None:
    # P1-D: the owner-visible terminal result (used by Telegram and Workspace)
    # carries bounded source provenance — repo, resolved full commit SHA,
    # normalized path and content SHA-256; no URL/token/body.
    view = missions.empty_projection()
    view["delivery_mode"] = "none"
    view["source_binding"] = {
        "repo": "PavelLizunov/unified-agent-platform",
        "resolved_ref": "a" * 40,
        "path": "docs/spec.md",
        "content_sha256": "b" * 64,
    }
    result = missions._completion_result(view)
    assert "PavelLizunov/unified-agent-platform" in result
    assert "a" * 40 in result
    assert "docs/spec.md" in result
    assert "b" * 64 in result
    assert "http" not in result
    assert "token" not in result


def test_source_preflight_answer_binds_same_mission_idempotently() -> None:
    # Answering the source-preflight question with a canonical same-target GitHub
    # URL pinned to a full commit SHA binds an immutable source.request to the
    # SAME mission (no new mission, no second accepted event); invalid answers
    # fail closed and leave the mission blocked; replay is idempotent.
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "suflyor", "label": "Suflyor",
                "repository": "PavelLizunov/suflyor",
                "summary": "Prompter", "aliases": ["suflyor"],
                "dispatch_profile": "build1-suflyor-registered-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
        ],
    })
    sha = "a" * 40
    question_id = "source-preflight:" + "b" * 24
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.ingest_owner_turn(
            "implement exactly per the handoff file ~/handoff/plan.md",
            platform="workspace",
            source_message_id="src-answer",
            session_id="src-answer-session",
            project_id="suflyor",
        )
        assert created
        mission_id = accepted["mission_id"]
        assert accepted["payload"].get("source_required") is True
        before_count = len(store.list(100))
        # The coordinator publishes the canonical source-preflight question.
        store.append_central(mission_id, {
            "schema_version": missions.SCHEMA_VERSION,
            "mission_id": mission_id,
            "type": "mission.question",
            "source": "central-hermes",
            "correlation": {"producer_event_id": "central:q:source-preflight"},
            "payload": {"question_id": question_id, "text": "provide an exact source"},
        })
        # Invalid answers fail closed: non-URL, branch ref, cross-repo, malformed.
        cross = f"https://github.com/PavelLizunov/other/blob/{sha}/docs/spec.md"
        for bad in (
            "not a url at all",
            "https://github.com/PavelLizunov/suflyor/blob/main/docs/spec.md",
            cross,
            "https://example.invalid/spec.md",
            f"https://github.com/PavelLizunov/suflyor/blob/{sha}/../etc/passwd",
        ):
            try:
                store.answer(mission_id, question_id, bad)
                raise AssertionError(f"invalid source answer accepted: {bad}")
            except missions.MissionError:
                pass
        assert store.projection(mission_id).get("source_request") is None
        assert store.projection(mission_id).get("source_required") is True
        assert len(store.list(100)) == before_count  # no new mission created

        # A valid same-target answer pinned to a full SHA binds the source.
        valid = f"Use https://github.com/PavelLizunov/suflyor/blob/{sha}/docs/spec.md please"
        store.answer(
            mission_id, question_id, valid,
            source_message_id="ans-1", source_platform="workspace",
        )
        proj = store.projection(mission_id)
        assert proj["mission_id"] == mission_id  # same mission, not a new one
        assert proj["source_request"] == {
            "repo": "PavelLizunov/suflyor", "ref": sha, "path": "docs/spec.md",
        }
        assert proj.get("source_required") is None  # resolved truthfully
        assert len(store.list(100)) == before_count  # still exactly one mission

        # Idempotent replay of the same answer dedups cleanly.
        store.answer(
            mission_id, question_id, valid,
            source_message_id="ans-1", source_platform="workspace",
        )
        # A changed answer to the same question is a producer-event collision:
        # it is rejected and the first recorded answer/source binding stands
        # (no terminal corruption, no second source.request).
        changed = f"Use https://github.com/PavelLizunov/suflyor/blob/{sha}/other/path.md"
        try:
            store.answer(mission_id, question_id, changed)
            raise AssertionError("changed source answer did not collide")
        except missions.MissionError as error:
            assert "collision" in str(error)
        proj = store.projection(mission_id)
        assert proj["source_request"] == {
            "repo": "PavelLizunov/suflyor", "ref": sha, "path": "docs/spec.md",
        }
        # Exactly one source.request event was committed.
        events = store.events(mission_id)
        assert sum(1 for e in events if e["type"] == "source.request") == 1

        # Telegram-style answer path binds identically on its own mission/question.
        tg_accepted, tg_created = store.ingest_owner_turn(
            "implement exactly per the design-doc from the vpnrouter repository",
            platform="telegram",
            source_message_id="src-answer-tg",
            session_id="src-answer-tg-session",
            chat_id="-1004377555987",
            thread_id="2",
            project_id="suflyor",
        )
        assert tg_created
        tg_mission_id = tg_accepted["mission_id"]
        tg_question_id = "source-preflight:" + "c" * 24
        store.append_central(tg_mission_id, {
            "schema_version": missions.SCHEMA_VERSION,
            "mission_id": tg_mission_id,
            "type": "mission.question",
            "source": "central-hermes",
            "correlation": {"producer_event_id": "central:q:source-preflight-tg"},
            "payload": {"question_id": tg_question_id, "text": "provide an exact source"},
        })
        store.answer(
            tg_mission_id, tg_question_id, valid,
            source_message_id="tg-ans-1", source_platform="telegram",
        )
        tg_proj = store.projection(tg_mission_id)
        assert tg_proj["source_request"] == {
            "repo": "PavelLizunov/suflyor", "ref": sha, "path": "docs/spec.md",
        }
        tg_answer = next(
            e for e in store.events(tg_mission_id) if e["type"] == "mission.answer"
        )
        assert tg_answer["payload"]["source_platform"] == "telegram"


def test_source_answer_replaces_only_the_unbound_intake_request() -> None:
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [{
            "project_id": "suflyor", "label": "Suflyor",
            "repository": "PavelLizunov/suflyor", "summary": "Prompter",
            "aliases": ["suflyor"],
            "dispatch_profile": "build1-suflyor-registered-v4",
            "delivery_mode": "none", "platforms": ["workspace"],
            "category": "active-maintained", "status": "ready",
            "test_targets": ["uap-build-1"],
        }],
    })
    sha = "a" * 40
    question_id = "source-preflight:" + "f" * 24
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, _ = store.ingest_owner_turn(
            "Implement per "
            "https://github.com/PavelLizunov/suflyor/blob/missing/docs/spec.md",
            platform="workspace", source_message_id="replace-unbound-source",
            session_id="replace-unbound-source", project_id="suflyor",
        )
        mission_id = accepted["mission_id"]
        assert accepted["payload"]["source_request"]["ref"] == "missing"
        store.append_central(mission_id, {
            "schema_version": missions.SCHEMA_VERSION,
            "mission_id": mission_id,
            "type": "mission.question",
            "source": "central-hermes",
            "correlation": {"producer_event_id": "central:q:replace-unbound-source"},
            "payload": {"question_id": question_id, "text": "provide exact source"},
        })
        exact = (
            "https://github.com/PavelLizunov/suflyor/blob/"
            f"{sha}/docs/spec.md"
        )
        store.answer(mission_id, question_id, exact)
        assert store.projection(mission_id)["source_request"] == {
            "repo": "PavelLizunov/suflyor",
            "ref": sha,
            "path": "docs/spec.md",
        }
        events = store.events(mission_id)
        assert sum(event["type"] == "source.request" for event in events) == 1


def test_source_answer_atomicity_and_fault_regression() -> None:
    # P1-1/P1-2 fault regression: mission.answer + source.request commit atomically
    # (an injected failure between the two insertions rolls back BOTH); a missing
    # project_repository fails closed committing zero events; replay converges with
    # exactly one mission.answer and one source.request; invalid/cross-repo/changed
    # answers commit zero new events.
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "suflyor", "label": "Suflyor",
                "repository": "PavelLizunov/suflyor",
                "summary": "Prompter", "aliases": ["suflyor"],
                "dispatch_profile": "build1-suflyor-registered-v4",
                "delivery_mode": "none", "platforms": ["workspace"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
        ],
    })
    sha = "a" * 40
    question_id = "source-preflight:" + "d" * 24
    valid = f"https://github.com/PavelLizunov/suflyor/blob/{sha}/docs/spec.md"

    def _open_source_mission(store, mid, qid):
        store.append_central(mid, {
            "schema_version": missions.SCHEMA_VERSION, "mission_id": mid,
            "type": "mission.question", "source": "central-hermes",
            "correlation": {"producer_event_id": f"central:q:{qid}"},
            "payload": {"question_id": qid, "text": "provide an exact source"},
        })

    def _counts(store, mid):
        events = store.events(mid)
        return (
            sum(1 for e in events if e["type"] == "mission.answer"),
            sum(1 for e in events if e["type"] == "source.request"),
        )

    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, _ = store.ingest_owner_turn(
            "implement exactly per the handoff file ~/handoff/plan.md",
            platform="workspace", source_message_id="fault-src",
            session_id="fault-src-session", project_id="suflyor",
        )
        mission_id = accepted["mission_id"]
        _open_source_mission(store, mission_id, question_id)

        # (1) Injected failure BETWEEN the two insertions rolls back BOTH events.
        real_project = missions.project

        def failing_project(events):
            if any(e.get("type") == "mission.answer" for e in events):
                raise RuntimeError("injected failure between insertions")
            return real_project(events)

        with mock.patch.object(missions, "project", failing_project):
            try:
                store.answer(mission_id, question_id, valid)
                raise AssertionError("injected failure did not propagate")
            except RuntimeError as error:
                assert "injected failure" in str(error)
        assert _counts(store, mission_id) == (0, 0)  # neither event committed

        # (2) Invalid / cross-repo / branch-ref answers commit zero new events.
        cross = f"https://github.com/PavelLizunov/other/blob/{sha}/docs/spec.md"
        for bad in (
            "not a url",
            "https://github.com/PavelLizunov/suflyor/blob/main/docs/spec.md",
            cross,
        ):
            try:
                store.answer(mission_id, question_id, bad)
                raise AssertionError(f"invalid answer accepted: {bad}")
            except missions.MissionError:
                pass
            assert _counts(store, mission_id) == (0, 0)

        # (3) A valid answer commits exactly one mission.answer + one source.request.
        store.answer(mission_id, question_id, valid)
        assert _counts(store, mission_id) == (1, 1)

        # (4) Same-answer replay converges: still exactly one of each (idempotent).
        store.answer(mission_id, question_id, valid)
        assert _counts(store, mission_id) == (1, 1)

        # (5) Changed answer fails closed as a collision; counts unchanged.
        changed = f"https://github.com/PavelLizunov/suflyor/blob/{sha}/other/path.md"
        try:
            store.answer(mission_id, question_id, changed)
            raise AssertionError("changed answer did not collide")
        except missions.MissionError as error:
            assert "collision" in str(error)
        assert _counts(store, mission_id) == (1, 1)

        # (6) P1-2: a mission with NO project_repository fails closed committing
        # zero events (same-target authority cannot be verified).
        no_repo_id = "mission-no-repo-source"
        store.accept(
            "implement exactly per the handoff file ~/handoff/plan.md",
            mission_id=no_repo_id, dispatch_profile="build1-suflyor-registered-v4",
        )
        no_repo_qid = "source-preflight:" + "e" * 24
        _open_source_mission(store, no_repo_id, no_repo_qid)
        assert store.projection(no_repo_id).get("project_repository") is None
        try:
            store.answer(no_repo_id, no_repo_qid, valid)
            raise AssertionError("source answer accepted without target repository")
        except missions.MissionError as error:
            assert "target repository" in str(error)
        assert _counts(store, no_repo_id) == (0, 0)


def test_routine_small_classifier_has_closed_ru_en_corpus() -> None:
    classify = missions.routine_small_expected_paths
    # Positive: explicit limiter + narrow one-line operation + one/two exact files.
    # Only ordinary docs/source paths are eligible; root manifests/locks and
    # control-surface prefixes are forbidden (see near_miss below).
    positives = {
        "Fix typo only in README.md": ("README.md",),
        "Fix the typo only in src/config.py": ("src/config.py",),
        "Fix typo only in docs/note.md": ("docs/note.md",),
        "Update the changelog only in CHANGELOG.md": ("CHANGELOG.md",),
        "fix typo only in path/to/file.ext": ("path/to/file.ext",),
        "Fix typo only in 123.md": ("123.md",),         # numeric-named file still admitted
        "Fix typo only in README.md and CHANGELOG.md": (
            "CHANGELOG.md", "README.md",
        ),
        "Обнови версию только в src/config.py": ("src/config.py",),
        "Исправь опечатку только в src/main.py": ("src/main.py",),
        "Обнови версию только в src/config.py и CHANGELOG.md": (
            "CHANGELOG.md", "src/config.py",
        ),
        # Dotted version tokens are not bound; the real file still is.
        "Update the version to 1.2.3 only in src/config.py": ("src/config.py",),
        "Update the changelog for v2.0 only in CHANGELOG.md": ("CHANGELOG.md",),
        "Обнови версию до 1.2.3 только в src/config.py": ("src/config.py",),
        # Email/@host fragments are not bound; the real file still is.
        "Fix typo only in README.md, cc user@example.com": ("README.md",),
        "Notify user @example.com and fix typo only in README.md": (
            "README.md",
        ),
    }
    for goal, expected in positives.items():
        assert classify(goal) == expected, goal

    # Near-miss: never infer routine_small from simple/small/quick wording,
    # ambiguous or unbounded filenames, or any risky/external/multi-file scope.
    near_miss = (
        "Исправь простой баг",                          # simple bug, no exact file
        "Make a small quick fix",                       # simple/small/quick wording
        "Make it quick only in README.md",              # no narrow operation
        "Update README only",                           # docs-only (routine_docs class)
        "Fix typo only in README.md and CHANGELOG.md and src/config.py",  # 3 files
        "Fix typo only in *.toml",                      # wildcard
        "Fix typo only in /etc/hosts",                  # POSIX absolute path
        "Fix typo only in C:/Windows/system.ini",       # Windows absolute drive
        "Fix typo only in ../etc/foo.txt",              # traversal
        "Fix typo only in https://example.com/x.toml",  # URL
        "Delete production data only in README.md",     # destructive risk flag
        "Change the accepted security boundary only in README.md",  # owner gate
        "Fix typo only in README.md; rm -rf /",         # shell syntax
        "Fix typo only in README.md | tee x",           # shell pipe
        "Add a new dependency only in README.md",       # dependency change
        "Update the version to 1.2.3 only",             # bare version token, no file
        "Set the version to v2.0 only",                 # bare version token, no file
        "Обнови версию до 1.2.3 только",                # bare version token, no file
        "Fix typo only in user@example.com",            # email is not a file
        "Fix typo only in user @example.com",           # @host fragment is not a file
        # --- Forbidden prefixes: CI, infra, tests, UAP orchestration ---
        "Fix typo only in .git/hooks/pre-commit.sample",            # git internals / hooks
        "Fix typo only in .github/workflows/ci.yml",                # CI workflow
        "Fix typo only in .github/workflows/deploy.yaml",           # CI workflow (yaml)
        "Fix typo only in .github/actions/setup/action.yml",        # custom action
        "Fix typo only in .github/CODEOWNERS",                      # repo-config
        "Fix typo only in .agents/profile.json",                    # UAP orchestration
        "Fix typo only in clusters/prod/infra/hermes-mission-runtime.yaml",  # infra control
        "Fix typo only in clusters/prod/apps/foo.yaml",             # infra control (apps)
        "Fix typo only in infra/terraform/main.tf",                 # IaC
        "Fix typo only in tests/static/test_foo.py",                # test suite
        "Fix typo only in tools/hermes-mission/runtime.py",         # classifier/runtime
        "Fix typo only in tools/hermes-workspace/server.py",        # workspace tooling
        "Fix typo only in tools/swarm/delivery_coordinator.py",     # delivery coordinator
        "Fix typo only in tools/swarm/flow_contract.py",            # flow contract
        # --- Forbidden prefixes: autonomous agent config surfaces ---
        "Fix typo only in .claude/settings.json",                   # agent config
        "Fix typo only in .claude/commands/deploy.md",              # agent command
        "Fix typo only in .codex/config.yaml",                      # agent config
        "Fix typo only in .qwen/settings.json",                     # agent config
        "Fix typo only in .cursor/rules.json",                      # agent config
        # --- Case-insensitive prefix matching ---
        "Fix typo only in .GitHub/workflows/ci.yml",                # capitalized prefix
        "Fix typo only in .GITHUB/workflows/ci.yml",                # uppercase prefix
        "Fix typo only in .Claude/settings.json",                   # capitalized agent
        "Fix typo only in .AGENTS/profile.json",                    # uppercase agent
        "Fix typo only in Clusters/prod/foo.yaml",                  # capitalized infra
        "Fix typo only in TESTS/test_foo.py",                       # uppercase tests
        # --- Forbidden basenames at root: repo-config / security ---
        "Fix typo only in .gitattributes",                          # repo-config
        "Fix typo only in .gitignore",                              # repo-config
        "Fix typo only in .gitlab-ci.yml",                          # GitLab CI
        "Fix typo only in .gitleaks.toml",                          # security config
        "Fix typo only in .ragignore",                              # repo-config
        "Fix typo only in .sops.yaml",                              # security config
        # --- Forbidden basenames at root: dependency manifests ---
        "Fix typo only in requirements.txt",                        # dependency manifest
        "Fix typo only in requirements-dev.txt",                    # dependency manifest
        # --- Forbidden basenames at root: build/dependency manifests and locks ---
        "Fix typo only in Cargo.toml",                              # Rust manifest
        "Fix typo only in Cargo.lock",                              # Rust lock
        "Fix typo only in Dockerfile",                              # container build
        "Fix typo only in Makefile",                                # build system
        "Fix typo only in go.mod",                                  # Go manifest
        "Fix typo only in go.sum",                                  # Go lock
        "Fix typo only in package.json",                            # Node manifest
        "Fix typo only in package-lock.json",                       # Node lock
        "Fix typo only in pnpm-lock.yaml",                          # pnpm lock
        "Fix typo only in poetry.lock",                             # Poetry lock
        "Fix typo only in pyproject.toml",                          # Python manifest
        "Fix typo only in setup.cfg",                               # Python config
        "Fix typo only in setup.py",                                # Python build
        "Fix typo only in tox.ini",                                 # Python test config
        "Fix typo only in uv.lock",                                 # uv lock
        "Fix typo only in yarn.lock",                               # Yarn lock
        # --- Forbidden basenames at ANY depth (nested) ---
        "Fix typo only in sub/pyproject.toml",                      # nested Python manifest
        "Fix typo only in service/Dockerfile.dev",                  # Dockerfile variant
        "Fix typo only in service/Dockerfile.prod",                 # Dockerfile variant
        "Fix typo only in app/package-lock.json",                   # nested Node lock
        "Fix typo only in lib/Cargo.lock",                          # nested Rust lock
        "Fix typo only in lib/Cargo.toml",                          # nested Rust manifest
        "Fix typo only in svc/requirements.txt",                    # nested dependency
        "Fix typo only in svc/requirements-prod.txt",               # nested req variant
        "Fix typo only in deep/nested/go.mod",                      # nested Go manifest
        "Fix typo only in web/package.json",                        # nested Node manifest
        "Fix typo only in build/Makefile",                          # nested build system
        "Fix typo only in build/makefile",                          # nested lowercase make
        "Fix typo only in ci/.gitlab-ci.yml",                       # nested GitLab CI
        "Fix typo only in sub/.gitignore",                          # nested repo-config
        "Fix typo only in sub/.gitleaks.toml",                      # nested security
        "Fix typo only in sub/setup.py",                            # nested Python build
        "Fix typo only in sub/tox.ini",                             # nested test config
        # --- Case-insensitive basename matching ---
        "Fix typo only in REQUIREMENTS.TXT",                        # uppercase dependency
        "Fix typo only in Requirements.txt",                        # capitalized dependency
        "Fix typo only in PYPROJECT.TOML",                          # uppercase manifest
        "Fix typo only in DOCKERFILE",                              # uppercase container
        "Fix typo only in MAKEFILE",                                # uppercase build
        "Fix typo only in sub/REQUIREMENTS.TXT",                    # nested uppercase dep
        "Fix typo only in sub/PYPROJECT.TOML",                      # nested uppercase
        # --- Mixed safe+forbidden: the forbidden path poisons the whole goal ---
        "Fix typo only in README.md and .github/workflows/ci.yml",  # safe + workflow
        "Fix typo only in .github/workflows/ci.yml and CHANGELOG.md",  # workflow + safe
        "Fix typo only in src/main.py and requirements.txt",        # safe + dependency
        "Fix typo only in docs/note.md and pyproject.toml",         # safe + manifest
        "Fix typo only in README.md and tests/test_foo.py",         # safe + test
        "Fix typo only in infra/main.tf and src/config.py",         # IaC + safe
        "Fix typo only in README.md and .claude/settings.json",     # safe + agent config
        "Fix typo only in src/main.py and sub/pyproject.toml",      # safe + nested manifest
        "Fix typo only in README.md and service/Dockerfile.dev",    # safe + Dockerfile var
        "Fix typo only in docs/note.md and .GitHub/workflows/ci.yml",  # safe + case prefix
        "Исправь опечатку только в .github/workflows/ci.yml",       # RU: CI workflow
        "Исправь опечатку только в requirements.txt",               # RU: dependency
        "Исправь опечатку только в pyproject.toml",                 # RU: manifest
        "Исправь опечатку только в .claude/settings.json",          # RU: agent config
        "Исправь опечатку только в sub/pyproject.toml",             # RU: nested manifest
    )
    for goal in near_miss:
        assert classify(goal) is None, goal
    assert classify(None) is None

    # Version tokens and email hosts are never extracted, even alongside a file.
    assert missions.closed_repo_path("1.2.3") is None
    assert missions.closed_repo_path("v2.0") is None
    assert missions.closed_repo_path("dir/2.0.1") is None
    assert missions.closed_repo_path("123.md") == "123.md"
    for goal in (
        "Update the version to 1.2.3 only in src/config.py",
        "Fix typo only in README.md, cc user@example.com",
    ):
        result = classify(goal)
        assert result is not None
        assert all("@" not in path for path in result), goal
        assert result == ("src/config.py",) or result == ("README.md",), goal


def test_routine_small_class_is_durable_and_closed() -> None:
    routes = json.dumps({
        "workspace": {
            "dispatch_profile": "build1-registered",
            "delivery_mode": "none",
        },
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_INTAKE_ROUTES": routes}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.ingest_owner_goal(
            "Fix typo only in README.md",
            platform="workspace",
            source_message_id="routine-small-1",
            session_id="routine-small-session",
        )
        assert created
        assert accepted["payload"]["execution_class"] == "routine_small"
        assert accepted["payload"]["expected_changed_files"] == 1
        assert accepted["payload"]["expected_changed_paths"] == ["README.md"]
        projection = store.projection(accepted["mission_id"])
        assert projection["execution_class"] == "routine_small"
        assert projection["expected_changed_files"] == 1
        assert projection["expected_changed_paths"] == ["README.md"]

        # Idempotent replay returns the exact same acceptance.
        replay, replay_created = store.ingest_owner_goal(
            "Fix typo only in README.md",
            platform="workspace",
            source_message_id="routine-small-1",
            session_id="routine-small-session",
        )
        assert not replay_created and replay == accepted

        # A two-file goal binds both exact paths immutably.
        two, two_created = store.ingest_owner_goal(
            "Fix typo only in README.md and CHANGELOG.md",
            platform="workspace",
            source_message_id="routine-small-2",
            session_id="routine-small-session",
        )
        assert two_created
        assert two["payload"]["expected_changed_files"] == 2
        assert two["payload"]["expected_changed_paths"] == [
            "CHANGELOG.md", "README.md",
        ]

        # Ordinary code missions stay unclassed.
        ordinary, ordinary_created = store.ingest_owner_goal(
            "Исправь простой баг",
            platform="workspace",
            source_message_id="ordinary-small-1",
            session_id="routine-small-session",
        )
        assert ordinary_created
        assert "execution_class" not in ordinary["payload"]

        # A different replay (changed paths) collides instead of mutating.
        try:
            store.accept(
                "Fix typo only in README.md",
                mission_id=accepted["mission_id"],
                execution_class="routine_small",
                expected_changed_files=1,
                expected_changed_paths=["OTHER.md"],
                delivery_mode="none",
            )
            raise AssertionError("changed routine_small paths were accepted as a replay")
        except missions.MissionError as error:
            assert str(error) == "mission already accepted with different parameters"

        # Closed validation rejects malformed execution-class triples.
        for index, (execution_class, expected_changed_files, paths) in enumerate((
            ("routine_small", 1, None),
            ("routine_small", 3, ["a.toml"]),
            ("routine_small", 1, ["a.toml", "a.toml"]),
            ("routine_small", 1, ["../a.toml"]),
            ("routine_small", 1, ["/etc/a.toml"]),
            ("routine_small", 1, ["1.2.3"]),            # version token, not a file
            ("routine_small", 1, ["v2.0"]),             # version token, not a file
            ("routine_small", 1, ["user@example.com"]),  # email, not a file
            ("routine_docs", 2, ["a.toml"]),
            ("arbitrary", 1, ["a.toml"]),
            # Closed non-routine surfaces are rejected at the accept() boundary too.
            ("routine_small", 1, [".github/workflows/ci.yml"]),          # CI workflow
            ("routine_small", 1, [".github/actions/setup/action.yml"]),  # custom action
            ("routine_small", 1, [".agents/profile.json"]),              # UAP orchestration
            ("routine_small", 1, ["clusters/prod/infra/foo.yaml"]),      # infra control
            ("routine_small", 1, ["infra/terraform/main.tf"]),           # IaC
            ("routine_small", 1, ["tests/static/test_foo.py"]),          # test suite
            ("routine_small", 1, ["tools/hermes-mission/runtime.py"]),   # classifier
            ("routine_small", 1, ["tools/hermes-workspace/server.py"]),  # workspace
            ("routine_small", 1, ["tools/swarm/delivery_coordinator.py"]),  # coordinator
            ("routine_small", 1, ["tools/swarm/flow_contract.py"]),      # flow contract
            ("routine_small", 1, [".gitattributes"]),                    # repo-config
            ("routine_small", 1, [".gitignore"]),                        # repo-config
            ("routine_small", 1, [".gitlab-ci.yml"]),                    # GitLab CI
            ("routine_small", 1, [".gitleaks.toml"]),                    # security config
            ("routine_small", 1, [".ragignore"]),                        # repo-config
            ("routine_small", 1, [".sops.yaml"]),                        # security config
            ("routine_small", 1, ["requirements.txt"]),                  # dependency
            ("routine_small", 1, ["requirements-dev.txt"]),              # dependency
            ("routine_small", 1, ["pyproject.toml"]),                    # Python manifest
            ("routine_small", 1, ["Cargo.toml"]),                        # Rust manifest
            ("routine_small", 1, ["Dockerfile"]),                        # container build
            ("routine_small", 1, ["Makefile"]),                          # build system
            ("routine_small", 1, ["go.mod"]),                            # Go manifest
            ("routine_small", 1, ["package.json"]),                      # Node manifest
            # Agent config prefixes
            ("routine_small", 1, [".claude/settings.json"]),             # agent config
            ("routine_small", 1, [".codex/config.yaml"]),                # agent config
            ("routine_small", 1, [".qwen/settings.json"]),               # agent config
            ("routine_small", 1, [".cursor/rules.json"]),                # agent config
            # Case-insensitive prefix/basename matching
            ("routine_small", 1, [".GitHub/workflows/ci.yml"]),          # capitalized
            ("routine_small", 1, ["REQUIREMENTS.TXT"]),                  # uppercase dep
            ("routine_small", 1, ["PYPROJECT.TOML"]),                    # uppercase manifest
            # Nested forbidden basenames at any depth
            ("routine_small", 1, ["sub/pyproject.toml"]),                # nested manifest
            ("routine_small", 1, ["service/Dockerfile.dev"]),            # Dockerfile var
            ("routine_small", 1, ["app/package-lock.json"]),             # nested lock
            ("routine_small", 1, ["lib/Cargo.lock"]),                    # nested Rust lock
            ("routine_small", 1, ["svc/requirements.txt"]),              # nested dep
            ("routine_small", 1, ["svc/requirements-prod.txt"]),         # nested req var
            ("routine_small", 1, ["build/makefile"]),                    # nested lowercase
            ("routine_small", 1, ["ci/.gitlab-ci.yml"]),                 # nested GitLab CI
            ("routine_small", 1, ["sub/.gitignore"]),                    # nested config
            # Mixed safe+forbidden two-file goals
            ("routine_small", 2, ["README.md", ".github/workflows/ci.yml"]),  # mixed
            ("routine_small", 2, ["docs/note.md", "pyproject.toml"]),    # mixed manifest
            ("routine_small", 2, ["README.md", ".claude/settings.json"]),  # mixed agent
            ("routine_small", 2, ["src/main.py", "sub/pyproject.toml"]),  # mixed nested
            ("routine_small", 2, ["README.md", "service/Dockerfile.dev"]),  # mixed Docker
        )):
            try:
                store.accept(
                    "Invalid routine_small class",
                    mission_id=f"mission-invalid-small-{index}",
                    execution_class=execution_class,
                    expected_changed_files=expected_changed_files,
                    expected_changed_paths=paths,
                    delivery_mode="none",
                )
                raise AssertionError("invalid routine_small execution class was accepted")
            except missions.MissionError as error:
                assert "execution class" in str(error)


def test_routine_small_keeps_profile_delivery_mode() -> None:
    """routine_small keeps the target delivery mode; deploy is never skipped."""
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl",
                "summary": "VPN control daemon", "aliases": ["vpnctl"],
                "dispatch_profile": "build1-vpnctl-registered-v4",
                "delivery_mode": "deploy", "platforms": ["workspace", "telegram"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}
    ):
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        accepted, created = store.ingest_owner_goal(
            "Fix typo only in src/config.py",
            platform="workspace",
            source_message_id="routine-small-deploy-1",
            session_id="routine-small-deploy-session",
            project_id="vpnctl",
        )
        assert created
        assert accepted["payload"]["execution_class"] == "routine_small"
        assert accepted["payload"]["delivery_mode"] == "deploy"
        projection = store.projection(accepted["mission_id"])
        assert projection["delivery_mode"] == "deploy"
        assert projection["execution_class"] == "routine_small"
        assert projection["expected_changed_paths"] == ["src/config.py"]

        # routine_docs on the same target still forces effective none mode.
        docs, docs_created = store.ingest_owner_goal(
            "Обнови только README",
            platform="workspace",
            source_message_id="routine-small-deploy-2",
            session_id="routine-small-deploy-session",
            project_id="vpnctl",
        )
        assert docs_created
        assert docs["payload"]["execution_class"] == "routine_docs"
        assert docs["payload"]["delivery_mode"] == "none"


def test_existing_project_setup_context_is_catalog_owned_and_fail_closed() -> None:
    catalog = json.dumps({
        "schema_version": 2,
        "projects": [
            {
                "project_id": "uap", "label": "UAP",
                "repository": "PavelLizunov/unified-agent-platform",
                "summary": "Platform", "aliases": ["platform"],
                "dispatch_profile": "build1-uap-registered-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
                "category": "active-maintained", "status": "ready",
                "test_targets": ["uap-build-1"],
            },
            {
                "project_id": "existing", "label": "Existing Project",
                "repository": "PavelLizunov/existing", "summary": "Existing app",
                "aliases": ["existing app"], "dispatch_profile": None,
                "delivery_mode": "none", "platforms": ["workspace"],
                "category": "active-maintained", "status": "setup_required",
                "test_targets": ["github-linux"],
            },
        ],
    })
    with mock.patch.dict(os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True):
        target = missions.project_setup_target("workspace", "existing")
        prompt = missions.project_setup_system_prompt(target)
        assert "UAP_SETUP_PROJECT_ID: existing" in prompt
        assert "PavelLizunov/existing" in prompt
        assert "только на чтение" in prompt and "setup_required" in prompt
        assert missions.project_setup_target_from_system_prompt(
            "workspace", prompt
        )["project_id"] == "existing"
        assert missions.project_setup_target_from_system_prompt(
            "workspace", "ordinary prompt"
        ) is None
        goal = missions.project_setup_execution_goal(target, "настраивай")
        assert "project_id=existing" in goal
        assert "status=setup_required" in goal
        assert "реальный canary" in goal
        for invalid in ("uap", "missing", "../existing"):
            try:
                missions.project_setup_target("workspace", invalid)
                raise AssertionError(f"invalid setup target was accepted: {invalid}")
            except missions.MissionError:
                pass


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

            progress = {
                **notice,
                "correlation": {
                    **notice["correlation"],
                    "producer_event_id": "flow:mission-capacity:progress",
                },
                "payload": {
                    "code": "progress_detail",
                    "message": (
                        "Цикл 3 из 7. Автор gpt-5.6-terra исправляет замечания. "
                        "Следом — автоматические проверки и CI."
                    ),
                    "owner_action_required": False,
                    "phase": "needs_fix",
                    "cycle": 3,
                    "cycle_limit": 7,
                    "url": "https://github.com/owner/repo/pull/7",
                },
            }
            store.append_producer("mission-capacity", progress)
            view = store.projection("mission-capacity")
            rendered = missions.telegram_text(view)
            assert progress["payload"]["message"] in rendered
            assert "Цикл: 3 из 7" in rendered
            assert "https://github.com/owner/repo/pull/7" in rendered
            assert "От вас ничего не требуется." in rendered

            invalid_url = {
                **progress,
                "correlation": {
                    **progress["correlation"],
                    "producer_event_id": "flow:mission-capacity:invalid-url",
                },
                "payload": {**progress["payload"], "url": "javascript:alert(1)"},
            }
            try:
                store.append_producer("mission-capacity", invalid_url)
                raise AssertionError("unsafe notice URL was accepted")
            except missions.MissionError as error:
                assert "notice URL" in str(error)

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


def test_notification_checkpoint_isolated_across_a_mission_rebind() -> None:
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
                assert await missions.notify_subscribers(store, old_event, sender) == 1
            finally:
                store.pending_subscriptions = pending_subscriptions
            assert len(stale_sends) == 1

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
            '{"workspace":{"dispatch_profile":"first","delivery_mode":"release"}}',
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


def test_project_target_conflict_fails_closed_before_acceptance() -> None:
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "dashboard", "label": "Dashboard",
                "repository": "PavelLizunov/dashboard", "summary": "Dashboard",
                "aliases": ["dash board"], "dispatch_profile": "dashboard-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)

        # Selecting vpnctl while the goal names vpnrouter's exact repository is a
        # conflict and fails closed before any mission or event is accepted.
        try:
            store.ingest_owner_turn(
                "Add a deterministic status command to PavelLizunov/VPNRouter",
                platform="workspace",
                project_id="vpnctl",
                source_message_id="conflict-exact-other",
                session_id="conflict-session",
            )
            raise AssertionError("exact other-repository goal was accepted")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "vpnctl"
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert store.list(100) == []

        # Multiple distinct exact repository references fail closed (never pass).
        try:
            store.ingest_owner_turn(
                "Add a status command to PavelLizunov/VPNRouter and PavelLizunov/dashboard",
                platform="workspace",
                project_id="vpnctl",
                source_message_id="conflict-exact-multi",
                session_id="conflict-session",
            )
            raise AssertionError("multiple exact-repository goal was accepted")
        except missions.MissionProjectConflict as error:
            assert sorted(p["project_id"] for p in error.mentioned) == [
                "dashboard", "vpnrouter",
            ]
        assert store.list(100) == []

        # A unique alias of exactly one other project is also a conflict.
        try:
            store.ingest_owner_turn(
                "vpn router add a deterministic status command",
                platform="workspace",
                project_id="vpnctl",
                source_message_id="conflict-alias",
                session_id="conflict-session",
            )
            raise AssertionError("unique alias-mismatch goal was accepted")
        except missions.MissionProjectConflict as error:
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert store.list(100) == []

        # Naming the selected project's exact repository succeeds.
        accepted, created = store.ingest_owner_turn(
            "Add a deterministic status command to PavelLizunov/vpnctl",
            platform="workspace",
            project_id="vpnctl",
            source_message_id="conflict-exact-same",
            session_id="conflict-session",
        )
        assert created and accepted["payload"]["project_id"] == "vpnctl"

        # A goal with no repository reference succeeds for the selected project.
        accepted, created = store.ingest_owner_turn(
            "Add a deterministic status command",
            platform="workspace",
            project_id="vpnctl",
            source_message_id="conflict-no-repo",
            session_id="conflict-session",
        )
        assert created and accepted["payload"]["project_id"] == "vpnctl"

        # The selected exact repository plus a separate alias of another project
        # still fails closed: the repository strengthens the selected span but
        # does not suppress a separate other-project mention.
        try:
            store.ingest_owner_turn(
                "Add a deterministic status command for PavelLizunov/vpnctl (vpn router compat)",
                platform="workspace",
                project_id="vpnctl",
                source_message_id="conflict-exact-plus-alias",
                session_id="conflict-session",
            )
            raise AssertionError("selected repo + separate other alias must fail closed")
        except missions.MissionProjectConflict as error:
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]

        assert len(store.list(100)) == 2


def test_project_target_conflict_uses_bounded_repo_tokens() -> None:
    """Regression: vpnrouter-gateway must not false-match VPNRouter (P1)."""
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnrouter-gateway", "label": "vpnrouter-gateway",
                "repository": "PavelLizunov/vpnrouter-gateway",
                "summary": "VPN gateway",
                "aliases": ["vpn gateway"], "dispatch_profile": "gateway-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)

        # Selected vpnrouter-gateway, goal names its exact repo → succeeds and
        # does NOT false-match PavelLizunov/VPNRouter via substring.
        accepted, created = store.ingest_owner_turn(
            "Add health check to PavelLizunov/vpnrouter-gateway",
            platform="workspace",
            project_id="vpnrouter-gateway",
            source_message_id="bound-exact-gateway",
            session_id="bound-session",
        )
        assert created and accepted["payload"]["project_id"] == "vpnrouter-gateway"

        # Selected vpnrouter-gateway, goal names PavelLizunov/VPNRouter → conflict.
        try:
            store.ingest_owner_turn(
                "Add health check to PavelLizunov/VPNRouter",
                platform="workspace",
                project_id="vpnrouter-gateway",
                source_message_id="bound-exact-vpnrouter",
                session_id="bound-session",
            )
            raise AssertionError("exact VPNRouter goal was accepted for gateway")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "vpnrouter-gateway"
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert len(store.list(100)) == 1

    # Unregistered longer suffix must not count as the registered shorter repo.
    catalog_short = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "vpnrouter", "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter", "summary": "VPN router",
                "aliases": ["vpn router"], "dispatch_profile": "vpnrouter-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnctl", "label": "vpnctl",
                "repository": "PavelLizunov/vpnctl", "summary": "VPN control",
                "aliases": ["vpn ctl"], "dispatch_profile": "vpnctl-v4",
                "delivery_mode": "none", "platforms": ["workspace", "telegram"],
            },
        ],
    })
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog_short}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)

        # Goal mentions PavelLizunov/vpnrouter-gateway (NOT registered) alongside
        # the selected repo.  The longer token must not match PavelLizunov/VPNRouter
        # as an exact other-repo reference.
        accepted, created = store.ingest_owner_turn(
            "Add PavelLizunov/vpnrouter-gateway health check to PavelLizunov/vpnctl",
            platform="workspace",
            project_id="vpnctl",
            source_message_id="bound-longer-suffix",
            session_id="bound-session-2",
        )
        assert created and accepted["payload"]["project_id"] == "vpnctl"


def test_project_target_conflict_selected_project_id_precedence() -> None:
    """Regression: selected project_id embedded alias must not false-trigger.

    Live bug: selected project_id is uap-macos-onboarding-proof-20260720 and
    the goal says "В проекте uap-macos-onboarding-proof-20260720 измени только
    src/lib.rs …".  The Unified Agent Platform project has short alias "uap"
    which is a prefix of the selected project_id.  The normalized alias matcher
    splits on hyphens, producing a false "uap" token.  The fix: an exact bounded
    mention of the selected project_id takes precedence over shorter embedded
    aliases of other projects.
    """
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "uap",
                "label": "Unified Agent Platform",
                "repository": "PavelLizunov/unified-agent-platform",
                "summary": "Self-hosted AI platform",
                "aliases": ["uap"],
                "dispatch_profile": "build1-uap-v4",
                "delivery_mode": "deploy",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "uap-macos-onboarding-proof-20260720",
                "label": "macOS Onboarding Proof",
                "repository": "PavelLizunov/uap-macos-onboarding-proof-20260720",
                "summary": "macOS onboarding proof of concept",
                "aliases": ["macos onboarding"],
                "dispatch_profile": "build1-macos-onboarding-v1",
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

        # 1. Exact live Russian string: selected project_id mentioned explicitly.
        #    The short alias "uap" of the other project is embedded in the
        #    selected project_id and must NOT trigger a conflict.
        accepted, created = store.ingest_owner_turn(
            "В проекте uap-macos-onboarding-proof-20260720 измени только src/lib.rs "
            "и добавь unit-тест для новой функции",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="live-russian-string",
            session_id="precedence-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        # 2. Overlapping ids/aliases: bare "uap" as a standalone word in the goal
        #    while the selected project is the longer id → conflict (the bare
        #    "uap" is an explicit project_id of the other project).
        try:
            store.ingest_owner_turn(
                "В проекте uap-macos-onboarding-proof-20260720 и uap измени src/lib.rs",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="overlap-two-ids",
                session_id="precedence-session",
            )
            raise AssertionError("two explicit project targets must fail closed")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "uap-macos-onboarding-proof-20260720"
            assert [p["project_id"] for p in error.mentioned] == ["uap"]

        # 3. Selected full repository mentioned → succeeds.
        accepted, created = store.ingest_owner_turn(
            "Add health check to PavelLizunov/uap-macos-onboarding-proof-20260720",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="selected-full-repo",
            session_id="precedence-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        # 4. Explicit other full repository → conflict.
        try:
            store.ingest_owner_turn(
                "Add health check to PavelLizunov/unified-agent-platform",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="other-full-repo",
                session_id="precedence-session",
            )
            raise AssertionError("explicit other repository must fail closed")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "uap-macos-onboarding-proof-20260720"
            assert [p["project_id"] for p in error.mentioned] == ["uap"]

        # 5. Two explicit project targets (both project_ids as bounded tokens).
        try:
            store.ingest_owner_turn(
                "Add uap-macos-onboarding-proof-20260720 config into uap runtime",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="two-explicit-ids",
                session_id="precedence-session",
            )
            raise AssertionError("two explicit distinct targets must fail closed")
        except missions.MissionProjectConflict as error:
            assert [p["project_id"] for p in error.mentioned] == ["uap"]

        # 6. Source-request exclusion: a GitHub source URL referencing the other
        #    project's repository is a cross-repo source, not a target conflict.
        accepted, created = store.ingest_owner_turn(
            "Implement per https://github.com/PavelLizunov/unified-agent-platform/"
            "blob/abc123/README.md in uap-macos-onboarding-proof-20260720",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="source-request-exclusion",
            session_id="precedence-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        assert len(store.list(100)) == 3


def test_project_target_conflict_embedding_aware_alias_label() -> None:
    """Embedding-aware alias/label conflict detection.

    A shorter other-project alias is ignored only when wholly embedded inside
    a longer selected-project identifier span.  A separate occurrence of
    another project's alias or label still fails closed.  Shared aliases do
    not create embedding spans.
    """
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "uap",
                "label": "Unified Agent Platform",
                "repository": "PavelLizunov/unified-agent-platform",
                "summary": "Self-hosted AI platform",
                "aliases": ["uap"],
                "dispatch_profile": "build1-uap-v4",
                "delivery_mode": "deploy",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "uap-macos-onboarding-proof-20260720",
                "label": "macOS Onboarding Proof",
                "repository": "PavelLizunov/uap-macos-onboarding-proof-20260720",
                "summary": "macOS onboarding proof of concept",
                "aliases": ["macos onboarding"],
                "dispatch_profile": "build1-macos-onboarding-v1",
                "delivery_mode": "none",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnrouter",
                "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter",
                "summary": "VPN router",
                "aliases": ["vpn router"],
                "dispatch_profile": "vpnrouter-v4",
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

        # 1. Selected alias plus distinct other alias: "macos onboarding" is the
        #    selected alias, "vpn router" is a separate other alias → conflict.
        try:
            store.ingest_owner_turn(
                "Add macos onboarding and vpn router integration status command",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="embed-alias-plus-other",
                session_id="embed-session",
            )
            raise AssertionError("selected alias + distinct other alias must fail closed")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "uap-macos-onboarding-proof-20260720"
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert store.list(100) == []

        # 2. Selected label containing a shorter other alias: the label
        #    "macOS Onboarding Proof" normalizes to "macos onboarding proof"
        #    which embeds "onboarding" — but "uap" is embedded in the selected
        #    project_id span.  No separate other mention → succeeds.
        accepted, created = store.ingest_owner_turn(
            "Add a status command to macos onboarding proof",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="embed-label-contains-shorter",
            session_id="embed-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        # 3. Separate other label: "VPNRouter" label as a separate mention
        #    alongside the selected project → conflict.
        try:
            store.ingest_owner_turn(
                "Add uap-macos-onboarding-proof-20260720 status to vpnrouter",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="embed-separate-other-label",
                session_id="embed-session",
            )
            raise AssertionError("separate other label must fail closed")
        except missions.MissionProjectConflict as error:
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert len(store.list(100)) == 1

        # 4. Shared alias ambiguity: when an alias appears in both the selected
        #    and another project's alias list, it must NOT create an embedding
        #    span.  Catalog validation normally prevents shared aliases on one
        #    platform, so test the defense-in-depth via direct call.
        shared_projects = [
            {
                "project_id": "proj-a",
                "label": "Project A",
                "repository": "owner/proj-a",
                "summary": "First",
                "aliases": ["shared", "alpha"],
                "dispatch_profile": "a-v1",
                "delivery_mode": "none",
                "platforms": ["workspace"],
            },
            {
                "project_id": "proj-b",
                "label": "Project B",
                "repository": "owner/proj-b",
                "summary": "Second",
                "aliases": ["shared", "beta"],
                "dispatch_profile": "b-v1",
                "delivery_mode": "none",
                "platforms": ["workspace"],
            },
        ]
        with mock.patch.object(
            missions, "registered_intake_projects", return_value=shared_projects
        ):
            try:
                missions._check_project_target_conflict(
                    "workspace", "proj-a", "Add a shared status command"
                )
                raise AssertionError("shared alias must not create an embedding span")
            except missions.MissionProjectConflict as error:
                assert error.selected["project_id"] == "proj-a"
                assert [p["project_id"] for p in error.mentioned] == ["proj-b"]

    # 5. Selected id plus separate other alias: the selected project_id span
    #    embeds the first "uap", but a second standalone "uap" is separate.
    with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
        os.environ, {"HERMES_MISSION_PROJECTS": catalog}, clear=True
    ):
        database = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(database)
        try:
            store.ingest_owner_turn(
                "Add uap-macos-onboarding-proof-20260720 config into uap runtime",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="embed-id-plus-separate-alias",
                session_id="embed-session-2",
            )
            raise AssertionError("separate other alias alongside selected id must fail closed")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "uap-macos-onboarding-proof-20260720"
            assert [p["project_id"] for p in error.mentioned] == ["uap"]
        assert store.list(100) == []


def test_project_target_conflict_repo_span_and_multi_other() -> None:
    """Selected repository is a span, not a suppressor; multiple others fail closed."""
    catalog = json.dumps({
        "schema_version": 1,
        "projects": [
            {
                "project_id": "uap",
                "label": "Unified Agent Platform",
                "repository": "PavelLizunov/unified-agent-platform",
                "summary": "Self-hosted AI platform",
                "aliases": ["uap"],
                "dispatch_profile": "build1-uap-v4",
                "delivery_mode": "deploy",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "uap-macos-onboarding-proof-20260720",
                "label": "macOS Onboarding Proof",
                "repository": "PavelLizunov/uap-macos-onboarding-proof-20260720",
                "summary": "macOS onboarding proof of concept",
                "aliases": ["macos onboarding"],
                "dispatch_profile": "build1-macos-onboarding-v1",
                "delivery_mode": "none",
                "platforms": ["workspace", "telegram"],
            },
            {
                "project_id": "vpnrouter",
                "label": "VPNRouter",
                "repository": "PavelLizunov/VPNRouter",
                "summary": "VPN router",
                "aliases": ["vpn router"],
                "dispatch_profile": "vpnrouter-v4",
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

        # 1. Selected full repository plus separate other project_id → conflict.
        try:
            store.ingest_owner_turn(
                "Add PavelLizunov/uap-macos-onboarding-proof-20260720 status to vpnrouter",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="repo-span-other-id",
                session_id="repo-span-session",
            )
            raise AssertionError("selected repo + separate other project_id must fail closed")
        except missions.MissionProjectConflict as error:
            assert error.selected["project_id"] == "uap-macos-onboarding-proof-20260720"
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert store.list(100) == []

        # 2. Selected full repository plus separate other alias → conflict.
        try:
            store.ingest_owner_turn(
                "Add PavelLizunov/uap-macos-onboarding-proof-20260720 and vpn router status",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="repo-span-other-alias",
                session_id="repo-span-session",
            )
            raise AssertionError("selected repo + separate other alias must fail closed")
        except missions.MissionProjectConflict as error:
            assert [p["project_id"] for p in error.mentioned] == ["vpnrouter"]
        assert store.list(100) == []

        # 3. Selected project_id plus two distinct other aliases/labels → conflict
        #    with BOTH mentioned projects included.
        try:
            store.ingest_owner_turn(
                "Add uap-macos-onboarding-proof-20260720 status to uap and vpn router",
                platform="workspace",
                project_id="uap-macos-onboarding-proof-20260720",
                source_message_id="two-distinct-others",
                session_id="repo-span-session",
            )
            raise AssertionError("two distinct other mentions must fail closed")
        except missions.MissionProjectConflict as error:
            assert sorted(p["project_id"] for p in error.mentioned) == [
                "uap", "vpnrouter",
            ]
        assert store.list(100) == []

        # 4. Only embedded shorter aliases in selected repository/project_id
        #    still accepted (the live bug case).
        accepted, created = store.ingest_owner_turn(
            "В проекте uap-macos-onboarding-proof-20260720 измени только src/lib.rs",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="embedded-only-accepted",
            session_id="repo-span-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        # 5. Source URL referencing another project's repo plus selected target
        #    still accepted (source-request exclusion intact).
        accepted, created = store.ingest_owner_turn(
            "Implement per https://github.com/PavelLizunov/VPNRouter/"
            "blob/abc123/README.md in uap-macos-onboarding-proof-20260720",
            platform="workspace",
            project_id="uap-macos-onboarding-proof-20260720",
            source_message_id="source-url-plus-selected",
            session_id="repo-span-session",
        )
        assert created
        assert accepted["payload"]["project_id"] == "uap-macos-onboarding-proof-20260720"

        assert len(store.list(100)) == 2


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
        assert store.owner_turn_continues_mission(
            platform="telegram",
            source_message_id="telegram-answer-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
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
        assert restarted.owner_turn_continues_mission(
            platform="telegram",
            source_message_id="telegram-answer-1",
            session_id="session-telegram",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
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


def test_owner_answer_cannot_add_task_capabilities_and_survives_restart() -> None:
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
            "Update the registered project",
            platform="telegram",
            source_message_id="capability-goal",
            session_id="capability-session",
            chat_id="owner-chat",
            thread_id="owner-thread",
        )
        assert created
        mission_id = accepted["mission_id"]
        question_id = "capability-question"
        store.append_producer(
            mission_id,
            {
                "schema_version": 1,
                "mission_id": mission_id,
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:capability-question:1"},
                "payload": {
                    "question_id": question_id,
                    "text": "Which implementation should be used?",
                },
            },
        )

        for candidate in (store, missions.MissionStore(database)):
            try:
                candidate.ingest_owner_turn(
                    "Delete the production database",
                    platform="telegram",
                    source_message_id="capability-answer",
                    session_id="capability-session",
                    chat_id="owner-chat",
                    thread_id="owner-thread",
                )
                raise AssertionError("owner answer added a destructive capability")
            except missions.MissionError as error:
                assert str(error) == (
                    "owner answer cannot add task capabilities: destructive"
                )
            projection = candidate.projection(mission_id)
            assert projection["status"] == "waiting_owner"
            assert projection["question"]["question_id"] == question_id
            assert projection["answer"] is None
            assert not any(
                event["type"] == "mission.answer"
                for event in candidate.events(mission_id)
            )


def test_task_risk_preflight_revalidates_legacy_durable_events() -> None:
    with tempfile.TemporaryDirectory() as temp:
        architecture_database = Path(temp) / "legacy-architecture.sqlite3"
        store = missions.MissionStore(architecture_database)
        accepted, _ = store.accept(
            "Update the documentation",
            mission_id="mission-legacy-architecture",
        )
        connection = sqlite3.connect(architecture_database)
        try:
            payload = json.loads(connection.execute(
                """SELECT payload_json FROM mission_events
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (accepted["mission_id"],),
            ).fetchone()[0])
            payload["goal"] = "Replace the accepted architecture and update ADR-031"
            connection.execute(
                """UPDATE mission_events SET payload_json = ?
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (json.dumps(payload), accepted["mission_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        restarted = missions.MissionStore(architecture_database)
        assert (
            restarted.projection(accepted["mission_id"])["owner_gate_flag"]
            == "architecture_change"
        )

        terminal_database = Path(temp) / "legacy-terminal.sqlite3"
        store = missions.MissionStore(terminal_database)
        accepted, _ = store.accept(
            "Update the documentation",
            mission_id="mission-legacy-terminal",
        )
        store.append_producer(
            accepted["mission_id"],
            {
                "schema_version": 1,
                "mission_id": accepted["mission_id"],
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:terminal-question:1"},
                "payload": {
                    "question_id": "terminal-question",
                    "text": "Which implementation should be used?",
                },
            },
        )
        store.answer(
            accepted["mission_id"], "terminal-question", "Preserve current behavior"
        )
        store.append_central(
            accepted["mission_id"],
            {
                "schema_version": 1,
                "mission_id": accepted["mission_id"],
                "type": "mission.failed",
                "source": "central-hermes",
                "correlation": {},
                "payload": {"error": "Historical failure"},
            },
        )
        connection = sqlite3.connect(terminal_database)
        try:
            accepted_payload = json.loads(connection.execute(
                """SELECT payload_json FROM mission_events
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (accepted["mission_id"],),
            ).fetchone()[0])
            accepted_payload["goal"] = "Delete the production database"
            answer_payload = json.loads(connection.execute(
                """SELECT payload_json FROM mission_events
                   WHERE mission_id = ? AND type = 'mission.answer'""",
                (accepted["mission_id"],),
            ).fetchone()[0])
            answer_payload["text"] = "Grant cluster-admin access"
            connection.execute(
                """UPDATE mission_events SET payload_json = ?
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (json.dumps(accepted_payload), accepted["mission_id"]),
            )
            connection.execute(
                """UPDATE mission_events SET payload_json = ?
                   WHERE mission_id = ? AND type = 'mission.answer'""",
                (json.dumps(answer_payload), accepted["mission_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        restarted = missions.MissionStore(terminal_database)
        assert restarted.projection(accepted["mission_id"])["status"] == "failed"

        unsupported_database = Path(temp) / "legacy-unsupported.sqlite3"
        store = missions.MissionStore(unsupported_database)
        accepted, _ = store.accept(
            "Update the documentation",
            mission_id="mission-legacy-unsupported",
        )
        connection = sqlite3.connect(unsupported_database)
        try:
            payload = json.loads(connection.execute(
                """SELECT payload_json FROM mission_events
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (accepted["mission_id"],),
            ).fetchone()[0])
            payload["goal"] = "Delete the production database"
            connection.execute(
                """UPDATE mission_events SET payload_json = ?
                   WHERE mission_id = ? AND type = 'mission.accepted'""",
                (json.dumps(payload), accepted["mission_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        try:
            missions.MissionStore(unsupported_database)
            raise AssertionError("legacy unsupported mission passed preflight")
        except missions.MissionError as error:
            assert str(error) == (
                "stored mission requires separate capability setup: destructive"
            )

        answer_database = Path(temp) / "legacy-answer.sqlite3"
        store = missions.MissionStore(answer_database)
        accepted, _ = store.accept(
            "Update the documentation",
            mission_id="mission-legacy-answer",
        )
        store.append_producer(
            accepted["mission_id"],
            {
                "schema_version": 1,
                "mission_id": accepted["mission_id"],
                "type": "mission.question",
                "source": "build1-flow",
                "correlation": {"producer_event_id": "flow:legacy-question:1"},
                "payload": {
                    "question_id": "legacy-question",
                    "text": "Which implementation should be used?",
                },
            },
        )
        store.answer(
            accepted["mission_id"], "legacy-question", "Preserve current behavior"
        )
        connection = sqlite3.connect(answer_database)
        try:
            payload = json.loads(connection.execute(
                """SELECT payload_json FROM mission_events
                   WHERE mission_id = ? AND type = 'mission.answer'""",
                (accepted["mission_id"],),
            ).fetchone()[0])
            payload["text"] = "Grant cluster-admin access"
            connection.execute(
                """UPDATE mission_events SET payload_json = ?
                   WHERE mission_id = ? AND type = 'mission.answer'""",
                (json.dumps(payload), accepted["mission_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        try:
            missions.MissionStore(answer_database)
            raise AssertionError("legacy capability-bearing answer passed preflight")
        except missions.MissionError as error:
            assert str(error) == (
                "stored owner answer adds task capabilities: "
                "credentials_or_external_authority"
            )


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
        assert store.owner_turn_continues_mission(
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-workspace",
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
        assert restarted.owner_turn_continues_mission(
            platform="workspace",
            source_message_id="workspace-answer-1",
            session_id="session-workspace",
        )
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
        try:
            restarted.ingest_owner_turn(
                "The same source ID belongs to another Central session",
                platform="workspace",
                source_message_id="workspace-answer-1",
                session_id="session-other",
            )
            raise AssertionError("non-execution turn created an unrelated mission")
        except missions.MissionError as error:
            assert str(error) == "owner turn is not an execution goal"
        assert restarted.latest() == next_goal["mission_id"]


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
        assert "РЕЗУЛЬТАТ\nImplemented the requested change and covered it with tests." in result_text
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


def test_deployment_delivery_is_closed_and_required_for_deploy_mode() -> None:
    event = {
        "schema_version": 1,
        "mission_id": "mission-deploy",
        "type": "delivery.upsert",
        "source": "build1-flow",
        "correlation": {"producer_event_id": "deploy:verified"},
        "payload": {
            "kind": "deployment",
            "status": "verified",
            "url": "http://vpnctld:18402/api/v1/health",
            "environment": "vpnctl-production",
            "artifact_sha256": "a" * 64,
            "deployed_revision": "b" * 40,
        },
    }
    missions._validate_submission("mission-deploy", event)
    for mutate in (
        lambda payload: payload.pop("artifact_sha256"),
        lambda payload: payload.update(deployed_revision="bad"),
        lambda payload: payload.update(kind="default_branch"),
    ):
        changed = json.loads(json.dumps(event))
        mutate(changed["payload"])
        try:
            missions._validate_submission("mission-deploy", changed)
            raise AssertionError("invalid deployment evidence was accepted")
        except missions.MissionError:
            pass

    base = {
        "status": "active",
        "question": None,
        "tasks": [{"status": "done"}],
        "workers": [{"worker_id": "task:run:1", "status": "completed"}],
        "delivery_mode": "deploy",
        "gates": [
            {"gate_id": name, "status": "passed"}
            for name in ("tests", "review", "ci", "post-verify", "deployment", "cleanup")
        ],
        "deliveries": [
            {"kind": "pull_request", "status": "merged"},
            {"kind": "default_branch", "status": "verified"},
            event["payload"],
        ],
    }
    assert missions.completion_ready(base)
    incomplete = json.loads(json.dumps(base))
    incomplete["deliveries"].pop()
    assert not missions.completion_ready(incomplete)

    failed = json.loads(json.dumps(base))
    failed["gates"] = [
        {"gate_id": name, "status": status}
        for name, status in (
            ("tests", "passed"), ("review", "passed"), ("ci", "passed"),
            ("post-verify", "passed"), ("deployment", "failed"),
            ("cleanup", "passed"),
        )
    ]
    failed["deliveries"][-1] = {**event["payload"], "status": "failed"}
    failed["deliveries"][-1].pop("artifact_sha256")
    assert missions.rejection_ready(failed)
    terminal = missions._rejection_terminal(failed)
    assert terminal and terminal[0] == "central:auto-deployment-failed:v1"


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
        terminal_sequence = store.projection("mission-retention-2")["sequence"]
        subscription = store.pending_subscriptions(
            "mission-retention-2", terminal_sequence
        )[0]
        token = store.claim_notification(subscription, terminal_sequence)
        assert token and store.finish_notification(
            subscription, terminal_sequence, token, delivered=True
        )
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
                    """UPDATE mission_notification_targets
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
            connection.execute(
                """INSERT INTO mission_subscriptions(
                       platform, chat_id, thread_id, mission_id,
                       last_notified_sequence
                   ) VALUES ('telegram', '42', '7', 'mission-existing', 9)"""
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
        connection = sqlite3.connect(database)
        try:
            target_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(mission_notification_targets)"
                )
            }
        finally:
            connection.close()
        assert {
            "platform", "chat_id", "thread_id", "mission_id",
            "last_notified_sequence", "notification_lease",
            "notification_lease_sequence", "notification_lease_until",
        } <= target_columns
        connection = sqlite3.connect(database)
        try:
            assert connection.execute(
                """SELECT mission_id, last_notified_sequence
                   FROM mission_notification_targets
                   WHERE platform = 'telegram' AND chat_id = '42' AND thread_id = '7'"""
            ).fetchone() == ("mission-existing", 9)
        finally:
            connection.close()


def test_workspace_mission_uses_default_telegram_target_without_stealing_binding() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {
                "HERMES_MISSION_TELEGRAM_CHAT_ID": "-10042",
                "HERMES_MISSION_TELEGRAM_THREAD_ID": "7",
            },
            clear=True,
        ):
            store = missions.MissionStore(Path(temp) / "missions.sqlite3")
            source_key_sha = hashlib.sha256(b"workspace:session:message").hexdigest()
            mission_id = f"mission-intake-{source_key_sha[:32]}"
            store.accept(
                "Deliver from Workspace",
                mission_id=mission_id,
                project_id="local-llm-lab",
                project_label="Local LLM Evaluation Lab",
                project_repository="PavelLizunov/local-llm-evaluation-lab",
                input_platform="workspace",
                input_source_key_sha256=source_key_sha,
                input_source_message_sha256=hashlib.sha256(b"goal").hexdigest(),
            )
            assert store.bound_mission("telegram", "-10042", "7") is None
            assert store.channel_evidence(mission_id)["telegram"] == {
                "subscriber_count": 1,
                "cursor": 0,
                "projection_id": None,
            }

            other = "mission-other-project"
            store.accept("Deliver another project", mission_id=other)
            store.bind(other, "telegram", "-10042", "7")
            assert store.bound_mission("telegram", "-10042", "7") == other

            event, _ = store.append_central(
                mission_id,
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "type": "mission.stage",
                    "source": "central-hermes",
                    "correlation": {},
                    "payload": {"stage": "testing", "progress_percent": 50},
                },
            )
            sent: list[str] = []

            async def send(_target: dict, text: str) -> None:
                sent.append(text)

            assert await missions.notify_subscribers(store, event, send) == 1
            assert len(sent) == 1
            assert sent[0].startswith(
                "#local_llm_lab · Local LLM Evaluation Lab "
                "(PavelLizunov/local-llm-evaluation-lab)"
            )
            assert store.channel_evidence(mission_id)["telegram"]["cursor"] == 2

    asyncio.run(scenario())


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


def _gate_event(
    mission_id: str,
    gate_id: str,
    status: str,
    producer_event_id: str,
    *,
    task_id: str = "task-1",
    worker_id: str | None = None,
) -> dict:
    """Build a gate.upsert the way the build-1 flow does.

    The incremental checkpoint publish carries correlation ``{task_id}``; the
    terminal batch replay adds ``worker_id``. Both share ``producer_event_id``
    because the adapter hashes only ``{type, payload, task_id}`` for worker events.
    """
    correlation: dict = {"task_id": task_id, "producer_event_id": producer_event_id}
    if worker_id is not None:
        correlation["worker_id"] = worker_id
    return {
        "schema_version": 1,
        "mission_id": mission_id,
        "type": "gate.upsert",
        "source": "build1-flow",
        "correlation": correlation,
        "payload": {"gate_id": gate_id, "status": status},
    }


def test_incremental_gate_evidence_reconciles_with_terminal_batch() -> None:
    """The critical finding: incremental and terminal gate events share one
    producer_event_id but differ in correlation routing; they must reconcile."""
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        mission_id = "mission-gate-reconcile"
        store.accept("Deliver the change", mission_id=mission_id)
        store.append_producer(mission_id, {
            "schema_version": 1, "mission_id": mission_id,
            "type": "task.upsert", "source": "build1-flow",
            "correlation": {"task_id": "task-1", "producer_event_id": "reconcile:task"},
            "payload": {"task_id": "task-1", "title": "Root", "status": "running"},
        })

        producer_id = "build1-flow:gate-tests-passed"
        incremental = _gate_event(mission_id, "tests", "passed", producer_id)
        terminal = _gate_event(
            mission_id, "tests", "passed", producer_id, worker_id="task-1:run:7"
        )
        # Same identity, different routing metadata.
        assert incremental["correlation"]["producer_event_id"] == terminal["correlation"]["producer_event_id"]
        assert incremental["payload"] == terminal["payload"]
        assert incremental["correlation"] != terminal["correlation"]

        # Incremental first, terminal batch replay reconciles (no collision, no dup).
        stored, created = store.append_producer(mission_id, incremental)
        assert created
        replayed, replay_created = store.append_producer(mission_id, terminal)
        assert not replay_created
        assert replayed["sequence"] == stored["sequence"]
        tests_rows = [
            gate for gate in store.projection(mission_id)["gates"]
            if gate["gate_id"] == "tests"
        ]
        assert tests_rows == [{"gate_id": "tests", "status": "passed"}]
        assert sum(
            1 for event in store.events(mission_id)
            if event["correlation"].get("producer_event_id") == producer_id
        ) == 1

        # Reverse order on a fresh gate also reconciles (terminal first).
        review_id = "build1-flow:gate-review-passed"
        terminal_review = _gate_event(
            mission_id, "review", "passed", review_id, worker_id="task-1:run:7"
        )
        incremental_review = _gate_event(mission_id, "review", "passed", review_id)
        first, first_created = store.append_producer(mission_id, terminal_review)
        assert first_created
        second, second_created = store.append_producer(mission_id, incremental_review)
        assert not second_created and second["sequence"] == first["sequence"]

        # A genuine forgery (same id, different payload) still fails closed.
        forgery = _gate_event(mission_id, "tests", "failed", producer_id)
        try:
            store.append_producer(mission_id, forgery)
            raise AssertionError("producer event id collision was accepted")
        except missions.MissionError as error:
            assert "collision" in str(error)

        # Identity is still guarded: same id but a different task_id collides.
        ci_id = "build1-flow:gate-ci-passed"
        store.append_producer(mission_id, _gate_event(mission_id, "ci", "passed", ci_id))
        try:
            store.append_producer(
                mission_id, _gate_event(mission_id, "ci", "passed", ci_id, task_id="task-2")
            )
            raise AssertionError("task_id identity mismatch was accepted")
        except missions.MissionError as error:
            assert "collision" in str(error)


def test_incremental_gate_evidence_survives_restart_lost_response_and_retry() -> None:
    """No collision, no semantic duplicate, no progress regression across a
    restart, a lost response, and a discarded retry run."""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "missions.sqlite3"
        store = missions.MissionStore(path)
        mission_id = "mission-gate-fault"
        store.accept("Deliver the change", mission_id=mission_id)
        store.append_producer(mission_id, {
            "schema_version": 1, "mission_id": mission_id,
            "type": "task.upsert", "source": "build1-flow",
            "correlation": {"task_id": "task-1", "producer_event_id": "fault:task"},
            "payload": {"task_id": "task-1", "title": "Root", "status": "running"},
        })

        def stage(progress: int, producer_id: str) -> None:
            store.append_producer(mission_id, {
                "schema_version": 1, "mission_id": mission_id,
                "type": "mission.stage", "source": "build1-flow",
                "correlation": {"task_id": "task-1", "producer_event_id": producer_id},
                "payload": {"stage": "testing", "progress_percent": progress},
            })

        # Incremental gate evidence published during the first run (run:7).
        for gate in ("tests", "review", "ci"):
            store.append_producer(
                mission_id, _gate_event(mission_id, gate, "passed", f"fault:gate:{gate}")
            )
        stage(50, "fault:stage:50")
        stage(65, "fault:stage:65")

        # Restart: reopen the store from disk.
        reopened = missions.MissionStore(path)
        before = reopened.projection(mission_id)
        assert before["progress_percent"] == 65
        assert {gate["gate_id"] for gate in before["gates"]} == {"tests", "review", "ci"}

        # Terminal batch replays the same gates under the FINAL run (run:9, the
        # discarded retry replaced run:7) -> correlation now carries worker_id.
        for gate in ("tests", "review", "ci", "post-verify", "cleanup"):
            _, created = reopened.append_producer(
                mission_id,
                _gate_event(
                    mission_id, gate, "passed", f"fault:gate:{gate}",
                    worker_id="task-1:run:9",
                ),
            )
            # Replayed gates reconcile; only the two new gates are appended.
            assert created == (gate in {"post-verify", "cleanup"})

        after = reopened.projection(mission_id)
        assert sorted(gate["gate_id"] for gate in after["gates"]) == [
            "ci", "cleanup", "post-verify", "review", "tests",
        ]
        assert after["progress_percent"] == 65  # no progress regression
        gate_ids = [
            event["correlation"].get("producer_event_id")
            for event in reopened.events(mission_id)
            if event["type"] == "gate.upsert"
        ]
        assert len(gate_ids) == len(set(gate_ids)) == 5  # no semantic duplicate

        # Lost response: the whole terminal batch is re-published -> idempotent.
        snapshot = after["projection_id"]
        for gate in ("tests", "review", "ci", "post-verify", "cleanup"):
            _, created = reopened.append_producer(
                mission_id,
                _gate_event(
                    mission_id, gate, "passed", f"fault:gate:{gate}",
                    worker_id="task-1:run:9",
                ),
            )
            assert not created
        assert reopened.projection(mission_id)["projection_id"] == snapshot

        # A genuinely lower progress stage with a NEW identity still fails closed.
        try:
            reopened.append_producer(mission_id, {
                "schema_version": 1, "mission_id": mission_id,
                "type": "mission.stage", "source": "build1-flow",
                "correlation": {"task_id": "task-1", "producer_event_id": "fault:stage:regress"},
                "payload": {"stage": "testing", "progress_percent": 40},
            })
            raise AssertionError("progress regression was accepted")
        except missions.MissionError as error:
            assert "progress decreased" in str(error)


def test_pr_closed_accepts_stale_stale_completed_recovery_history() -> None:
    """A clean crash-recovered canonical history (stale, stale, completed) must
    gate the PR-closed terminal: exactly one mission.failed, no duplicate."""
    with tempfile.TemporaryDirectory() as directory:
        store = missions.MissionStore(Path(directory) / "missions.sqlite3")
        mission_id = "mission-pr-closed-stale-recovery"
        store.accept(
            "Fix issue 39", mission_id=mission_id,
            dispatch_profile="build1-vpnrouter-a7-3",
        )

        def publish(event_type: str, payload: dict, number: int) -> None:
            store.append_producer(mission_id, {
                "schema_version": 1, "mission_id": mission_id,
                "type": event_type, "source": "build1-flow",
                "correlation": {"producer_event_id": f"flow:prclosed:{number}"},
                "payload": payload,
            })

        publish("task.upsert", {
            "task_id": "task-1", "title": "Root", "status": "done",
            "assignee": "coordinator",
        }, 1)
        # Canonical crash-recovered worker history: stale, stale, completed.
        publish("worker.upsert", {
            "worker_id": "task-1:run:76", "run_id": "76",
            "profile": "coordinator", "status": "stale",
        }, 2)
        publish("worker.upsert", {
            "worker_id": "task-1:run:77", "run_id": "77",
            "profile": "coordinator", "status": "stale",
        }, 3)
        publish("worker.upsert", {
            "worker_id": "task-1:run:82", "run_id": "82",
            "profile": "coordinator", "status": "completed",
        }, 4)
        publish("gate.upsert", {"gate_id": "pull-request", "status": "failed"}, 5)
        publish("gate.upsert", {"gate_id": "cleanup", "status": "passed"}, 6)
        publish("delivery.upsert", {
            "kind": "pull_request", "status": "failed",
            "url": "https://github.com/PavelLizunov/suflyor/pull/23",
        }, 7)

        failed = store.complete_if_ready(mission_id)
        assert failed is not None and failed[1]
        assert failed[0]["type"] == "mission.failed"
        assert failed[0]["source"] == "central-hermes"
        assert failed[0]["correlation"]["producer_event_id"] == "central:auto-pr-closed:v1"
        assert store.projection(mission_id)["status"] == "failed"
        # Replay does not append a duplicate terminal event.
        assert store.complete_if_ready(mission_id) is None
        assert store.projection(mission_id)["status"] == "failed"


def test_pr_closed_worker_history_negatives_remain_nonterminal() -> None:
    """Last worker not terminal, or an earlier completed/success/running/unknown
    canonical worker, must keep the mission nonterminal."""
    cases = {
        "last-stale": (["stale", "stale"], "stale"),
        "earlier-completed": (["completed"], "completed"),
        "earlier-success": (["success"], "completed"),
        "earlier-running": (["running"], "completed"),
        "earlier-unknown": (["bogus-status"], "completed"),
    }
    for name, (earlier, last) in cases.items():
        with tempfile.TemporaryDirectory() as directory:
            store = missions.MissionStore(Path(directory) / "missions.sqlite3")
            mission_id = f"mission-pr-closed-neg-{name}"
            store.accept(
                "Fix issue 39", mission_id=mission_id,
                dispatch_profile="build1-vpnrouter-a7-3",
            )
            seq = {"n": 0}

            def publish(event_type: str, payload: dict) -> None:
                seq["n"] += 1
                store.append_producer(mission_id, {
                    "schema_version": 1, "mission_id": mission_id,
                    "type": event_type, "source": "build1-flow",
                    "correlation": {"producer_event_id": f"flow:neg:{seq['n']}"},
                    "payload": payload,
                })

            publish("task.upsert", {
                "task_id": "task-1", "title": "Root", "status": "done",
                "assignee": "coordinator",
            })
            for index, status in enumerate(earlier):
                publish("worker.upsert", {
                    "worker_id": f"task-1:run:{index}", "run_id": str(index),
                    "profile": "coordinator", "status": status,
                })
            publish("worker.upsert", {
                "worker_id": f"task-1:run:{len(earlier)}",
                "run_id": str(len(earlier)),
                "profile": "coordinator", "status": last,
            })
            publish("gate.upsert", {"gate_id": "pull-request", "status": "failed"})
            publish("gate.upsert", {"gate_id": "cleanup", "status": "passed"})
            publish("delivery.upsert", {
                "kind": "pull_request", "status": "failed",
                "url": "https://github.com/PavelLizunov/suflyor/pull/23",
            })

            assert store.complete_if_ready(mission_id) is None
            assert store.projection(mission_id)["status"] == "active"


def test_completion_accepts_stale_then_completed_recovery_history() -> None:
    """A successful crash-recovered mission (earlier canonical worker stale, final
    completed) must complete through the real MissionStore: exactly one
    mission.completed, no duplicate on replay, and the normal owner result valid.
    Mirrors the exact existing successful task/gates/deliveries contract."""
    with tempfile.TemporaryDirectory() as directory:
        store = missions.MissionStore(Path(directory) / "missions.sqlite3")
        mission_id = "mission-completion-stale-recovery"
        store.accept(
            "Fix issue 39", mission_id=mission_id,
            dispatch_profile="build1-vpnrouter-a7-3",
        )
        seq = {"n": 0}

        def publish(event_type: str, payload: dict) -> None:
            seq["n"] += 1
            store.append_producer(mission_id, {
                "schema_version": 1, "mission_id": mission_id,
                "type": event_type, "source": "build1-flow",
                "correlation": {"producer_event_id": f"flow:complete:{seq['n']}"},
                "payload": payload,
            })

        publish("task.upsert", {
            "task_id": "task-1", "title": "Root", "status": "done",
            "assignee": "coordinator",
        })
        # Canonical crash-recovered history: stale (run 76), completed (run 82).
        publish("worker.upsert", {
            "worker_id": "task-1:run:76", "run_id": "76",
            "profile": "coordinator", "status": "stale",
        })
        publish("worker.upsert", {
            "worker_id": "task-1:run:82", "run_id": "82",
            "profile": "coordinator", "status": "completed",
        })
        # Exact existing successful delivery contract.
        for gate_id in missions._COMPLETION_GATES:
            publish("gate.upsert", {"gate_id": gate_id, "status": "passed"})
        for kind, status in missions._COMPLETION_DELIVERIES.items():
            payload = {"kind": kind, "status": status, "url": f"https://example.invalid/{kind}"}
            if kind == "pull_request":
                payload["summary"] = "Merged the fix."
            publish("delivery.upsert", payload)

        completed = store.complete_if_ready(mission_id)
        assert completed is not None and completed[1]
        assert completed[0]["type"] == "mission.completed"
        assert completed[0]["source"] == "central-hermes"
        assert completed[0]["correlation"]["producer_event_id"] == "central:auto-complete:v1"
        # Normal owner result remains valid.
        result = completed[0]["payload"]["result"]
        assert isinstance(result, str) and "РЕЗУЛЬТАТ" in result
        assert store.projection(mission_id)["status"] == "completed"
        # Replay adds no duplicate terminal event.
        assert store.complete_if_ready(mission_id) is None
        assert store.projection(mission_id)["status"] == "completed"


def main() -> None:
    test_research_only_goal_bypasses_coding_mission_intake()
    test_conversational_admission_requires_explicit_execution_intent()
    test_owner_turn_admission_is_authoritative_before_project_routing()
    test_source_request_is_immutable_and_survives_project_selection()
    test_fresh_direct_accept_derives_source_request()
    test_legacy_pre_feature_accept_replays_without_collision()
    test_owner_visible_terminal_result_carries_source_provenance()
    test_source_preflight_answer_binds_same_mission_idempotently()
    test_source_answer_replaces_only_the_unbound_intake_request()
    test_source_answer_atomicity_and_fault_regression()
    test_task_owner_gate_classifier_has_closed_ru_en_corpus()
    test_task_owner_gate_is_durable_or_rejected_before_mission_acceptance()
    test_routine_docs_class_is_durable_and_closed()
    test_routine_docs_on_deploy_target_gets_effective_none_mode()
    test_routine_small_classifier_has_closed_ru_en_corpus()
    test_routine_small_class_is_durable_and_closed()
    test_routine_small_keeps_profile_delivery_mode()
    test_existing_project_setup_context_is_catalog_owned_and_fail_closed()
    test_project_onboarding_is_idempotent_restart_safe_and_forward_only()
    test_reconnect_projects_one_canonical_state()
    test_producer_retry_and_notification_checkpoint_are_idempotent()
    test_capacity_notice_projects_to_workspace_and_telegram_without_owner_gate()
    test_notification_can_repeat_after_delivery_before_checkpoint()
    test_notification_checkpoint_isolated_across_a_mission_rebind()
    test_producer_cannot_end_mission_or_decrease_progress()
    test_dispatch_profile_is_projected_and_immutable()
    test_registered_owner_intake_is_deterministic_and_fail_closed()
    test_project_target_conflict_fails_closed_before_acceptance()
    test_project_target_conflict_uses_bounded_repo_tokens()
    test_project_target_conflict_selected_project_id_precedence()
    test_project_target_conflict_embedding_aware_alias_label()
    test_project_target_conflict_repo_span_and_multi_other()
    test_registered_project_selection_is_durable_and_restart_safe()
    test_bound_ordinary_owner_turn_answers_once_and_survives_restart()
    test_owner_gate_accepts_only_exact_approval_without_clearing_question()
    test_owner_answer_cannot_add_task_capabilities_and_survives_restart()
    test_task_risk_preflight_revalidates_legacy_durable_events()
    test_session_ordinary_owner_turn_answers_once_and_survives_restart()
    test_session_owner_turn_fails_closed_for_multiple_open_questions()
    test_concurrent_owner_intake_converges_on_one_acceptance()
    test_dispatch_candidates_do_not_starve_behind_newer_missions()
    test_producer_schema_is_closed_and_all_strings_are_redacted()
    test_terminal_authority_is_loopback_only()
    test_owner_answer_capability_is_separate_from_the_producer_key()
    test_central_auto_completion_requires_the_full_delivery_contract()
    test_deployment_delivery_is_closed_and_required_for_deploy_mode()
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
    test_workspace_mission_uses_default_telegram_target_without_stealing_binding()
    test_repair_mission_inherits_and_restores_telegram_binding()
    test_terminal_failure_contracts_include_preserved_pr_ci_and_post_verify()
    test_failure_terminal_commits_before_telegram_and_retries_delivery()
    test_disk_space_notice_contract_through_runtime_validation_and_store()
    test_worker_upsert_schema_accepts_telemetry_fields()
    test_worker_upsert_schema_rejects_invalid_tokens()
    test_accepted_schema_project_label_repository()
    test_incremental_gate_evidence_reconciles_with_terminal_batch()
    test_incremental_gate_evidence_survives_restart_lost_response_and_retry()
    test_pr_closed_accepts_stale_stale_completed_recovery_history()
    test_pr_closed_worker_history_negatives_remain_nonterminal()
    test_completion_accepts_stale_then_completed_recovery_history()
    print("hermes mission runtime checks passed")


def test_worker_upsert_schema_accepts_telemetry_fields() -> None:
    """worker.upsert accepts bounded runtime usage and activity counters."""
    with tempfile.TemporaryDirectory() as temp:
        store = missions.MissionStore(Path(temp) / "missions.sqlite3")
        store.accept("Schema test", mission_id="mission-schema-worker")
        store.append_producer("mission-schema-worker", {
            "schema_version": 1, "mission_id": "mission-schema-worker",
            "type": "worker.upsert", "source": "build1-flow",
            "correlation": {"producer_event_id": "schema:w1"},
            "payload": {"worker_id": "w1", "status": "completed",
                        "model": "gpt-5.6-sol", "effort": "high",
                        "input_tokens": 1000, "cached_input_tokens": 800,
                        "output_tokens": 500, "reasoning_output_tokens": 300,
                        "model_requests": 6, "max_request_input_tokens": 400,
                        "command_calls": 9, "failed_commands": 2,
                        "web_search_calls": 1},
        })
        view = store.projection("mission-schema-worker")
        assert view["workers"][0]["model"] == "gpt-5.6-sol"
        assert view["workers"][0]["input_tokens"] == 1000
        assert view["workers"][0]["cached_input_tokens"] == 800
        assert view["workers"][0]["model_requests"] == 6
        assert view["workers"][0]["command_calls"] == 9


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
        for payload in (
            {"input_tokens": 10, "cached_input_tokens": 11},
            {"output_tokens": 10, "reasoning_output_tokens": 11},
            {"command_calls": 2, "failed_commands": 3},
        ):
            try:
                store.append_producer("mission-schema-reject", {
                    "schema_version": 1, "mission_id": "mission-schema-reject",
                    "type": "worker.upsert", "source": "build1-flow",
                    "correlation": {"producer_event_id": f"schema:cross:{sorted(payload.items())}"},
                    "payload": {"worker_id": "w1", "status": "completed", **payload},
                })
                raise AssertionError(f"invalid telemetry relation {payload} was accepted")
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


if __name__ == "__main__":
    main()
