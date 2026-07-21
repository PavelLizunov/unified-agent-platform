"""Central Hermes mission log and the two owner-facing projections.

This module is copied into the pinned Hermes checkout by ``apply_overlay.py``.
It intentionally uses only the Python standard library already present in
Hermes: SQLite is the authority, Workspace receives the structured view, and
Telegram renders that same view as compact text.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable


SCHEMA_VERSION = 1
STAGES = (
    "accepted",
    "planning",
    "implementing",
    "testing",
    "reviewing",
    "delivering",
    "verifying",
    "complete",
)
TERMINAL_TYPES = {"mission.completed", "mission.failed", "mission.cancelled"}
NOTIFY_TYPES = {
    "mission.stage", "mission.notice", "mission.question", "mission.answer",
    *TERMINAL_TYPES,
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
    "artifact.upsert": {
        "artifact_id", "kind", "name", "media_type", "size_bytes", "sha256",
    },
    "mission.completed": {"result"},
    "mission.failed": {"error"},
    "mission.cancelled": {"reason"},
}
PAYLOAD_FIELDS = {
    **REQUIRED_PAYLOAD,
    "mission.accepted": {
        "goal", "project_id", "dispatch_profile", "delivery_mode", "parent_mission_id",
        "capability",
        "input_platform", "input_source_key_sha256", "input_source_message_sha256",
    },
    "mission.notice": {
        "code", "message", "owner_action_required", "next_attempt_at",
    },
    "mission.answer": {
        "question_id", "text", "source_message_id", "source_platform",
    },
    "task.upsert": {"task_id", "title", "status", "assignee"},
    "worker.upsert": {"worker_id", "status", "run_id", "profile"},
    "terminal.append": {"stream", "text", "offset"},
    "delivery.upsert": {"kind", "status", "url"},
    "artifact.upsert": {
        "artifact_id", "kind", "name", "media_type", "size_bytes", "sha256",
    },
}
CORRELATION_FIELDS = {"session_id", "run_id", "task_id", "worker_id", "producer_event_id"}
PRODUCER_TYPES = set(REQUIRED_PAYLOAD) - {
    "mission.accepted", "mission.answer", "artifact.upsert", *TERMINAL_TYPES,
}
_EVENT_FIELDS = {"schema_version", "mission_id", "type", "source", "correlation", "payload"}
_NULLABLE_PAYLOAD = {("task.upsert", "assignee"), ("worker.upsert", "profile")}
_ID_PAYLOAD_FIELDS = {
    "artifact_id", "assignee", "capability", "code", "delivery_mode", "dispatch_profile", "gate_id", "input_platform", "kind", "parent_mission_id", "profile", "project_id", "question_id", "source_platform",
    "run_id", "status", "stream", "task_id", "worker_id",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_EVENT_JSON = 65_536
_MAX_OWNER_GOAL_CHARS = 16_384
_MAX_TERMINAL_ENTRIES = 200
_MAX_TERMINAL_CHARS = 65_536
_MAX_OWNER_ANSWER_CHARS = 4_000
_MAX_COMPLETION_RESULT_CHARS = 3_000
_MAX_MEDIA_BYTES = 25 * 1024 * 1024
_MEDIA_CAPABILITY = "media.image.generate"
_MEDIA_DISPATCH_PROFILE = "central-imagegen"
_MEDIA_LEASE_SECONDS = 600
_OWNER_GATE_QUESTION_PREFIX = "owner-gate:"
_OWNER_GATE_APPROVAL = "APPROVE"
_MAX_RETAINED_TERMINAL_MISSIONS = 100
_RESEARCH_INTENT = re.compile(
    r"\b(?:research(?:_session)?|look\s+up|web\s+search|search\s+the\s+web|"
    r"find\s+(?:the\s+)?(?:current|latest)|(?:current|latest)\s+documentation)\b|"
    r"(?:исслед\w*|поищ\w*|веб[- ]?поиск\w*|поиск\s+(?:в\s+)?(?:интернете|сети)|"
    r"найд\w*\s+(?:актуальн\w*|в\s+интернете|в\s+сети|документац\w*))",
    re.IGNORECASE,
)
_MUTATION_INTENT = re.compile(
    r"\b(?:implement|fix|modify|add|remove|refactor|build|deploy|commit|push|"
    r"open\s+(?:a\s+)?pr|create\s+(?:a\s+)?pr|"
    r"реализ\w*|исправ\w*|измени\w*|добав\w*|удали\w*|рефактор\w*|"
    r"собер\w*|задепло\w*|закоммит\w*|запуш\w*)\b",
    re.IGNORECASE,
)
_COMPLETION_GATES = {"tests", "review", "ci", "post-verify", "cleanup"}
_COMPLETION_DELIVERIES = {
    "pull_request": "merged",
    "default_branch": "verified",
}
_STAGE_LABELS = {
    "accepted": "Цель принята",
    "planning": "Планирование",
    "implementing": "Внесение изменений",
    "testing": "Автоматические проверки",
    "reviewing": "Независимая проверка",
    "delivering": "PR, CI и слияние",
    "verifying": "Проверка после слияния",
    "complete": "Готово",
}
_STATUS_LABELS = {
    "active": "в работе",
    "waiting_owner": "нужен ваш ответ",
    "completed": "завершено",
    "failed": "завершено с ошибкой",
    "cancelled": "отменено",
}
_NOTICE_LABELS = {
    "capacity_wait": "Модель OpenAI временно занята. Повтор запланирован автоматически.",
    "capacity_recovered": "Модель OpenAI снова доступна. Выполнение продолжилось автоматически.",
    "execution_reconciling": (
        "Проверяю прерванный запуск модели. Новый исполнитель не запускается; "
        "восстановление продолжится автоматически."
    ),
    "disk_space_wait": (
        "Недостаточно свободного места на выделенном томе. "
        "Доставка приостановлена до освобождения пространства."
    ),
    "disk_space_recovered": (
        "Место на выделенном томе освобождено. Доставка продолжилась автоматически."
    ),
}
_INTAKE_CANCEL_ALIASES = {"cancel", "отмена", "отменить"}
_PROJECT_ONBOARDING_OWNER = "PavelLizunov"
_PROJECT_ONBOARDING_PRESETS = {"rust", "go", "python", "web"}
_PROJECT_ONBOARDING_CHECKPOINTS = (
    "requested",
    "repository_ready",
    "runtime_ready",
    "canary_passed",
    "ready",
)
_PROJECT_ONBOARDING_PROGRESS = {
    checkpoint: index * 25
    for index, checkpoint in enumerate(_PROJECT_ONBOARDING_CHECKPOINTS)
}
_PROJECT_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
NOTIFICATION_SEND_TIMEOUT_SECONDS = 240
# ponytail: lease exceeds the bounded send; a crash releases binding after five minutes.
_NOTIFICATION_LEASE_SECONDS = 300


def is_controlled_research_goal(text: object) -> bool:
    """Route research-only owner turns to the bounded Central search tool."""
    if not isinstance(text, str):
        return False
    normalized = " ".join(text.split())[:4_000]
    return bool(_RESEARCH_INTENT.search(normalized)) and not _MUTATION_INTENT.search(
        normalized
    )


class MissionError(ValueError):
    """A mission request violated the v1 contract."""


class MissionProjectRequired(MissionError):
    """The owner must choose one registered project before intake can continue."""

    def __init__(self, projects: list[dict[str, Any]]) -> None:
        super().__init__("choose a registered project")
        self.projects = projects


class MissionIntakeCancelled(MissionError):
    """An uncommitted Telegram project-selection draft was cancelled."""

    def __init__(self) -> None:
        super().__init__("выбор проекта отменён")


class MissionProjectUnavailable(MissionError):
    """The repository is known, but its reviewed delivery profile is not ready."""

    def __init__(self, project: dict[str, Any]) -> None:
        super().__init__(
            f"проект {project['label']} пока нельзя выполнять автоматически: "
            "для него ещё не установлен проверенный профиль сборки и тестов"
        )
        self.project = project


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _require_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise MissionError(f"invalid {name}")
    return text


def _require_source_value(value: Any, name: str, *, optional: bool = False) -> str:
    if value is None and optional:
        return ""
    if not isinstance(value, str):
        raise MissionError(f"invalid {name}")
    text = value.strip()
    if not text and optional:
        return ""
    if not text or len(text) > 256 or re.search(r"[\x00-\x1f\x7f]", text):
        raise MissionError(f"invalid {name}")
    return text


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MissionError("invalid mission intake configuration")
        result[key] = value
    return result


def _project_alias(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))


def image_generation_prompt(value: str) -> str | None:
    """Return a conservative text-to-image prompt, never guess edit intent."""
    text = str(value or "").strip()
    explicit = re.match(r"^(?:\$imagegen|/image|/imagine)\s*[:\-]?\s*(.+)$", text, re.I | re.S)
    if explicit:
        return explicit.group(1).strip() or None
    natural = re.match(
        r"^(?:(?:создай|сгенерируй|нарисуй)\s+(?:мне\s+)?(?:изображение|картинку|иллюстрацию|фото)|"
        r"(?:create|generate|draw|make)\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|illustration|photo))"
        r"\s*[:\-]?\s*(.+)$",
        text,
        re.I | re.S,
    )
    return natural.group(1).strip() if natural and natural.group(1).strip() else None


def image_edit_requested(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.search(
        r"(?:^|\s)(?:отредактируй|измени|замени|удали|добавь|edit|modify|replace|remove)"
        r"(?:\s+\S+){0,5}\s+(?:изображени\w*|картин\w*|фото\w*|image|picture|photo)\b",
        text,
        re.I,
    ))


def media_topic_pairs() -> set[tuple[str, str]]:
    """Return the exact Telegram ``(chat_id, thread_id)`` pairs that route to media.

    Telegram's ``message_thread_id`` is unique within a chat, not globally,
    so the allowlist must scope by both.  Configuration is a JSON array of
    objects with exactly ``chat_id`` and ``thread_id`` string fields in the
    ``HERMES_MISSION_MEDIA_TOPICS`` environment variable.  Empty or absent
    means no topic routing (fail-closed default).  Only
    ``media.image.generate`` is implied; there is no generic capability
    registry.
    """
    raw = os.environ.get("HERMES_MISSION_MEDIA_TOPICS", "").strip()
    if not raw:
        return set()
    if len(raw.encode("utf-8")) > 4_096:
        raise MissionError("invalid mission media topic configuration")
    try:
        topics = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, MissionError) as error:
        raise MissionError("invalid mission media topic configuration") from error
    if not isinstance(topics, list) or len(topics) > 16:
        raise MissionError("invalid mission media topic configuration")
    result: set[tuple[str, str]] = set()
    for item in topics:
        if not isinstance(item, dict) or set(item) != {"chat_id", "thread_id"}:
            raise MissionError("invalid mission media topic configuration")
        pair: list[str] = []
        for field in ("chat_id", "thread_id"):
            value = item[field]
            if not isinstance(value, str):
                raise MissionError("invalid mission media topic configuration")
            value = value.strip()
            if not value or len(value) > 256 or re.search(r"[\x00-\x1f\x7f]", value):
                raise MissionError("invalid mission media topic configuration")
            pair.append(value)
        key = (pair[0], pair[1])
        if key in result:
            raise MissionError("invalid mission media topic configuration")
        result.add(key)
    return result


def registered_intake_projects(platform: str) -> list[dict[str, Any]]:
    """Return the closed server-owned project catalog for one owner channel."""
    if not isinstance(platform, str):
        raise MissionError("invalid intake platform")
    platform = _require_id(platform, "intake platform")
    raw = os.environ.get("HERMES_MISSION_PROJECTS", "").strip()
    if raw:
        if len(raw.encode("utf-8")) > 65_536:
            raise MissionError("invalid mission project catalog")
        try:
            catalog = json.loads(raw, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, MissionError) as error:
            raise MissionError("invalid mission project catalog") from error
        if (
            not isinstance(catalog, dict)
            or set(catalog) != {"schema_version", "projects"}
            or catalog.get("schema_version") not in {1, 2}
            or isinstance(catalog.get("schema_version"), bool)
            or not isinstance(catalog.get("projects"), list)
            or not 1 <= len(catalog["projects"]) <= 64
        ):
            raise MissionError("invalid mission project catalog")
        projects: list[dict[str, Any]] = []
        ids: set[str] = set()
        aliases: set[str] = set()
        legacy_fields = {
            "project_id", "label", "repository", "summary", "aliases",
            "dispatch_profile", "delivery_mode", "platforms",
        }
        inventory_fields = legacy_fields | {"category", "status", "test_targets"}
        for item in catalog["projects"]:
            expected_fields = (
                legacy_fields if catalog["schema_version"] == 1 else inventory_fields
            )
            if not isinstance(item, dict) or set(item) != expected_fields:
                raise MissionError("invalid mission project catalog")
            project_id = _require_id(item.get("project_id"), "project_id")
            if project_id in ids:
                raise MissionError("invalid mission project catalog")
            ids.add(project_id)
            label = _require_source_value(item.get("label"), "project label")
            repository = _require_source_value(
                item.get("repository"), "project repository"
            )
            summary = _require_source_value(item.get("summary"), "project summary")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                raise MissionError("invalid project repository")
            if item.get("delivery_mode") != "none":
                raise MissionError("unsupported mission delivery mode")
            status = item.get("status", "ready")
            category = item.get("category", "registered")
            test_targets = item.get("test_targets", [])
            if (
                status not in {"ready", "setup_required", "read_only", "archived"}
                or category not in {
                    "registered", "pilot", "active-maintained", "support-only",
                    "research", "mirror/fork", "release-only", "archived",
                }
                or not isinstance(test_targets, list)
                or len(test_targets) > 8
                or any(
                    not isinstance(value, str) or not _ID.fullmatch(value)
                    for value in test_targets
                )
                or len(set(test_targets)) != len(test_targets)
            ):
                raise MissionError("invalid mission project catalog")
            dispatch_profile = item.get("dispatch_profile")
            if status == "ready":
                dispatch_profile = _require_id(
                    dispatch_profile, "dispatch_profile"
                )
            elif dispatch_profile is not None:
                raise MissionError("unavailable project has a dispatch profile")
            item_aliases = item.get("aliases")
            item_platforms = item.get("platforms")
            if (
                not isinstance(item_aliases, list)
                or not 1 <= len(item_aliases) <= 12
                or not isinstance(item_platforms, list)
                or not item_platforms
                or len(item_platforms) > 2
                or any(value not in {"workspace", "telegram"} for value in item_platforms)
                or len(set(item_platforms)) != len(item_platforms)
            ):
                raise MissionError("invalid mission project catalog")
            normalized_aliases: list[str] = []
            for alias in [project_id, label, repository, repository.rsplit("/", 1)[-1], *item_aliases]:
                alias = _project_alias(_require_source_value(alias, "project alias"))
                if not alias:
                    raise MissionError("invalid project alias")
                if alias not in normalized_aliases:
                    normalized_aliases.append(alias)
            if platform in item_platforms:
                for alias in normalized_aliases:
                    if alias in aliases:
                        raise MissionError("ambiguous project alias")
                    aliases.add(alias)
                projects.append({
                    "project_id": project_id,
                    "label": label,
                    "repository": repository,
                    "summary": summary,
                    "aliases": normalized_aliases,
                    "dispatch_profile": dispatch_profile,
                    "delivery_mode": "none",
                    "category": category,
                    "status": status,
                    "test_targets": test_targets,
                })
        if not projects:
            raise MissionError("owner channel has no registered delivery route")
        return projects

    # Backward-compatible single-profile configuration.
    raw = os.environ.get("HERMES_MISSION_INTAKE_ROUTES", "").strip()
    if not raw or len(raw.encode("utf-8")) > 16_384:
        raise MissionError("mission intake is not configured")
    try:
        routes = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, MissionError) as error:
        raise MissionError("invalid mission intake routes") from error
    if not isinstance(routes, dict) or not routes or len(routes) > 16:
        raise MissionError("invalid mission intake routes")
    normalized: dict[str, dict[str, str | None]] = {}
    for route_platform, target in routes.items():
        route_platform = _require_id(route_platform, "intake platform")
        if route_platform in normalized:
            raise MissionError("invalid mission intake routes")
        if isinstance(target, str):
            normalized[route_platform] = {
                "dispatch_profile": _require_id(target, "dispatch_profile"),
                "delivery_mode": None,
            }
            continue
        if not isinstance(target, dict) or set(target) != {
            "dispatch_profile", "delivery_mode"
        }:
            raise MissionError("invalid mission intake routes")
        mode = target.get("delivery_mode")
        if mode != "none":
            raise MissionError("unsupported mission delivery mode")
        normalized[route_platform] = {
            "dispatch_profile": _require_id(
                target.get("dispatch_profile"), "dispatch_profile"
            ),
            "delivery_mode": mode,
        }
    try:
        target = normalized[platform]
    except KeyError as error:
        raise MissionError("owner channel has no registered delivery route") from error
    return [{
        "project_id": None,
        "label": "Default project",
        "repository": "registered/default",
        "summary": "Legacy registered delivery profile",
        "aliases": ["default project"],
        "category": "registered",
        "status": "ready",
        "test_targets": [],
        **target,
    }]


def public_intake_projects(platform: str) -> list[dict[str, Any]]:
    """Expose only owner-safe project metadata, never runtime paths or commands."""
    return [
        {
            **{name: str(project[name]) for name in (
                "project_id", "label", "repository", "summary", "delivery_mode",
                "category", "status",
            ) if project.get(name) is not None},
            "test_targets": list(project.get("test_targets", [])),
        }
        for project in registered_intake_projects(platform)
    ]


def registered_intake_target(
    platform: str, *, project_id: str | None = None, goal: str | None = None
) -> dict[str, Any]:
    """Resolve an explicit project or an unambiguous alias to its exact profile."""
    projects = registered_intake_projects(platform)
    if project_id is not None:
        project_id = _require_id(project_id, "project_id")
        matches = [item for item in projects if item["project_id"] == project_id]
    elif len(projects) == 1:
        matches = projects
    elif isinstance(goal, str) and goal.strip():
        normalized = f" {_project_alias(goal)} "
        matches = [
            item for item in projects
            if any(f" {alias} " in normalized for alias in item["aliases"])
        ]
    else:
        matches = []
    if len(matches) != 1:
        ready = [
            project for project in public_intake_projects(platform)
            if project.get("status") == "ready"
        ]
        raise MissionProjectRequired(ready)
    if matches[0].get("status") != "ready":
        raise MissionProjectUnavailable(
            next(
                project for project in public_intake_projects(platform)
                if project.get("project_id") == matches[0]["project_id"]
            )
        )
    return matches[0]


def registered_intake_route(platform: str) -> str:
    """Return the legacy exact profile view of a registered intake target."""
    return str(registered_intake_target(platform)["dispatch_profile"])


def _validate_submission(mission_id: str, submission: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(submission, dict)
        or isinstance(submission.get("schema_version"), bool)
        or submission.get("schema_version") != SCHEMA_VERSION
    ):
        raise MissionError("invalid mission event version")
    if unknown := set(submission) - _EVENT_FIELDS:
        raise MissionError(f"unknown mission event fields: {', '.join(sorted(unknown))}")
    if submission.get("mission_id") != mission_id:
        raise MissionError("mission event identity mismatch")
    event_type = str(submission.get("type") or "").strip()
    source = str(submission.get("source") or "").strip()
    correlation = submission.get("correlation", {})
    payload = submission.get("payload", {})
    if not event_type or len(event_type) > 64 or not source or len(source) > 64:
        raise MissionError("invalid mission event type/source")
    if event_type not in REQUIRED_PAYLOAD:
        raise MissionError("unsupported mission event type")
    if not isinstance(correlation, dict) or not isinstance(payload, dict):
        raise MissionError("correlation and payload must be objects")
    if unknown := set(correlation) - CORRELATION_FIELDS:
        raise MissionError(f"unknown correlation fields: {', '.join(sorted(unknown))}")
    if unknown := set(payload) - PAYLOAD_FIELDS[event_type]:
        raise MissionError(f"unknown payload fields: {', '.join(sorted(unknown))}")
    missing = REQUIRED_PAYLOAD[event_type] - payload.keys()
    if missing:
        raise MissionError(f"missing payload fields: {', '.join(sorted(missing))}")
    for name, value in correlation.items():
        _require_id(value, f"correlation.{name}")
    for name, value in payload.items():
        if value is None and (event_type, name) in _NULLABLE_PAYLOAD:
            continue
        if name == "owner_action_required":
            if not isinstance(value, bool):
                raise MissionError("invalid payload.owner_action_required")
            continue
        if name == "progress_percent":
            continue
        if name == "size_bytes":
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 < value <= _MAX_MEDIA_BYTES
            ):
                raise MissionError("invalid payload.size_bytes")
            continue
        if name == "offset":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MissionError("invalid payload.offset")
            continue
        if not isinstance(value, str) or not value.strip():
            raise MissionError(f"invalid payload.{name}")
        if name in _ID_PAYLOAD_FIELDS:
            _require_id(value, f"payload.{name}")
    if event_type == "mission.stage":
        if payload.get("stage") not in STAGES:
            raise MissionError("invalid mission stage")
        progress = payload.get("progress_percent")
        if not isinstance(progress, int) or isinstance(progress, bool) or not 0 <= progress <= 100:
            raise MissionError("invalid mission progress")
    if event_type == "mission.notice":
        if payload.get("code") not in {
            "capacity_wait", "capacity_recovered", "execution_reconciling",
            "disk_space_wait", "disk_space_recovered",
        }:
            raise MissionError("invalid mission notice code")
        next_attempt = payload.get("next_attempt_at")
        if next_attempt is not None:
            try:
                parsed = datetime.fromisoformat(next_attempt.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as error:
                raise MissionError("invalid mission notice timestamp") from error
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise MissionError("invalid mission notice timestamp")
    if event_type == "mission.answer" and "source_message_id" in payload:
        _require_source_value(payload.get("source_message_id"), "source_message_id")
    if event_type == "mission.answer" and "source_platform" in payload:
        if payload.get("source_platform") not in {"workspace", "telegram"}:
            raise MissionError("invalid owner answer platform")
        if "source_message_id" not in payload:
            raise MissionError("owner answer platform requires source message identity")
    if event_type == "mission.accepted" and "dispatch_profile" in payload:
        _require_id(payload.get("dispatch_profile"), "dispatch_profile")
    if event_type == "mission.accepted" and "delivery_mode" in payload:
        if payload.get("delivery_mode") != "none":
            raise MissionError("invalid mission delivery mode")
    if event_type == "mission.accepted" and "capability" in payload:
        if payload.get("capability") != _MEDIA_CAPABILITY:
            raise MissionError("invalid mission capability")
    if event_type == "mission.accepted":
        input_fields = (
            payload.get("input_platform"),
            payload.get("input_source_key_sha256"),
            payload.get("input_source_message_sha256"),
        )
        if any(value is not None for value in input_fields):
            platform, source_key_sha256, source_message_sha256 = input_fields
            if (
                platform not in {"workspace", "telegram"}
                or not isinstance(source_key_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_key_sha256)
                or not isinstance(source_message_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_message_sha256)
                or mission_id != f"mission-intake-{source_key_sha256[:32]}"
            ):
                raise MissionError("invalid mission input lineage")
    if event_type == "delivery.upsert":
        not_applicable = (
            payload.get("kind") == "delivery"
            and payload.get("status") == "not_applicable"
        )
        if not_applicable:
            if "url" in payload:
                raise MissionError("not-applicable delivery must not have a URL")
        elif "url" not in payload:
            raise MissionError("delivery URL is required")
    if event_type == "artifact.upsert":
        if (
            payload.get("kind") != "image"
            or payload.get("media_type") not in {"image/png", "image/jpeg", "image/webp"}
            or not re.fullmatch(r"[0-9a-f]{64}", payload.get("sha256", ""))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", payload.get("name", ""))
        ):
            raise MissionError("invalid image artifact metadata")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "type": event_type,
        "source": source,
        "correlation": correlation,
        "payload": payload,
    }
    if len(_json(normalized).encode("utf-8")) > _MAX_EVENT_JSON:
        raise MissionError("mission event too large")
    return normalized


def _producer_submission(mission_id: str, submission: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_submission(mission_id, submission)
    if normalized["type"] not in PRODUCER_TYPES or normalized["source"] != "build1-flow":
        raise MissionError("producer cannot publish this mission event")
    _require_id(normalized["correlation"].get("producer_event_id"), "producer_event_id")
    return normalized


def sanitize_producer_submission(
    mission_id: str,
    submission: dict[str, Any],
    redactor: Callable[[str], str],
) -> dict[str, Any]:
    """Validate the closed producer schema and protect every producer string."""
    normalized = _producer_submission(mission_id, submission)
    for group in ("correlation", "payload"):
        normalized[group] = dict(normalized[group])
        for name, value in normalized[group].items():
            if isinstance(value, str):
                redacted = redactor(value)
                if not isinstance(redacted, str):
                    raise MissionError("producer redactor returned a non-string")
                if group == "correlation" and name == "producer_event_id":
                    if redacted != value:
                        raise MissionError("sensitive producer_event_id is not allowed")
                    continue
                normalized[group][name] = redacted
    return _producer_submission(mission_id, normalized)


def empty_projection() -> dict[str, Any]:
    return {
        "mission_id": None,
        "sequence": 0,
        "status": None,
        "stage": None,
        "progress_percent": 0,
        "notice": None,
        "goal": None,
        "project_id": None,
        "dispatch_profile": None,
        "capability": None,
        "delivery_mode": None,
        "parent_mission_id": None,
        "input_platform": None,
        "input_source_key_sha256": None,
        "input_source_message_sha256": None,
        "question": None,
        "answer": None,
        "result": None,
        "error": None,
        "tasks": [],
        "workers": [],
        "terminal": [],
        "changes": [],
        "gates": [],
        "deliveries": [],
        "artifacts": [],
    }


def project(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce one ordered log. Unknown event types are retained by SQLite but ignored here."""
    view = empty_projection()
    tasks: OrderedDict[str, dict[str, Any]] = OrderedDict()
    workers: OrderedDict[str, dict[str, Any]] = OrderedDict()
    changes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    gates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    deliveries: OrderedDict[str, dict[str, Any]] = OrderedDict()
    artifacts: OrderedDict[str, dict[str, Any]] = OrderedDict()
    terminal: list[dict[str, Any]] = []
    expected = 1
    terminal_chars = 0

    for event in events:
        if event.get("sequence") != expected:
            raise MissionError("mission event sequence gap")
        expected += 1
        if view["mission_id"] not in (None, event.get("mission_id")):
            raise MissionError("projection mission mismatch")
        view["mission_id"] = event["mission_id"]
        view["sequence"] = event["sequence"]
        kind, payload = event["type"], event["payload"]
        if kind == "mission.accepted":
            view.update(
                status="active",
                stage="accepted",
                goal=payload["goal"],
                project_id=payload.get("project_id"),
                dispatch_profile=payload.get("dispatch_profile"),
                capability=payload.get("capability"),
                delivery_mode=payload.get("delivery_mode"),
                parent_mission_id=payload.get("parent_mission_id"),
                input_platform=payload.get("input_platform"),
                input_source_key_sha256=payload.get("input_source_key_sha256"),
                input_source_message_sha256=payload.get("input_source_message_sha256"),
            )
        elif kind == "mission.stage":
            progress = payload["progress_percent"]
            if progress < view["progress_percent"]:
                raise MissionError("mission progress decreased")
            view.update(stage=payload["stage"], progress_percent=progress, notice=None)
            if view.get("question") is None:
                view["status"] = "active"
        elif kind == "mission.notice":
            view["notice"] = dict(payload)
            if view.get("question") is None:
                view["status"] = "active"
        elif kind == "mission.question":
            view.update(
                status="waiting_owner",
                question={"question_id": payload["question_id"], "text": payload["text"]},
                answer=None,
                notice=None,
            )
        elif kind == "mission.answer":
            question = view.get("question")
            if (
                view.get("status") != "waiting_owner"
                or not isinstance(question, dict)
                or question.get("question_id") != payload["question_id"]
            ):
                raise MissionError("mission answer does not match the open question")
            view.update(status="active", question=None, answer=dict(payload))
        elif kind == "task.upsert":
            tasks[str(payload["task_id"])] = dict(payload)
        elif kind == "worker.upsert":
            workers[str(payload["worker_id"])] = dict(payload)
        elif kind == "terminal.append":
            text = str(payload["text"])
            entry = {"sequence": event["sequence"], "stream": payload["stream"], "text": text}
            terminal.append(entry)
            terminal_chars += len(text)
            while len(terminal) > _MAX_TERMINAL_ENTRIES or terminal_chars > _MAX_TERMINAL_CHARS:
                terminal_chars -= len(terminal.pop(0)["text"])
        elif kind == "change.upsert":
            changes[str(payload["path"])] = dict(payload)
        elif kind == "gate.upsert":
            gates[str(payload["gate_id"])] = dict(payload)
        elif kind == "delivery.upsert":
            deliveries[str(payload["kind"])] = dict(payload)
        elif kind == "artifact.upsert":
            artifacts[str(payload["artifact_id"])] = dict(payload)
        elif kind == "mission.completed":
            view.update(
                status="completed", stage="complete", progress_percent=100,
                result=payload["result"], notice=None,
            )
        elif kind == "mission.failed":
            view.update(status="failed", error=payload["error"], notice=None)
        elif kind == "mission.cancelled":
            view.update(status="cancelled", error=payload["reason"], notice=None)

    view.update(
        tasks=list(tasks.values()),
        workers=list(workers.values()),
        terminal=terminal,
        changes=list(changes.values()),
        gates=list(gates.values()),
        deliveries=list(deliveries.values()),
        artifacts=list(artifacts.values()),
    )
    stable = {key: value for key, value in view.items() if key != "projection_id"}
    view["projection_id"] = hashlib.sha256(_json(stable).encode("utf-8")).hexdigest()[:16]
    return view


def telegram_text(view: dict[str, Any]) -> str:
    """Render the compact Telegram view from the exact Workspace projection."""
    status = view.get("status") or "unknown"
    stage = view.get("stage") or "unknown"
    lines = [
        f"Задача {view.get('mission_id') or 'неизвестна'}",
        f"Этап: {_STAGE_LABELS.get(stage, stage)} · {view.get('progress_percent', 0)}%",
        f"Статус: {_STATUS_LABELS.get(status, status)}",
    ]
    if view.get("question"):
        question = view["question"]
        text = question["text"]
        if str(question.get("question_id", "")).startswith(_OWNER_GATE_QUESTION_PREFIX):
            text = (
                "Задача меняет утверждённую архитектурную границу. Чтобы разрешить "
                "это изменение только для этой задачи, ответьте обычным сообщением "
                "(не командой): APPROVE."
            )
        lines.append(f"Нужен ваш ответ: {text}")
    if view.get("answer"):
        lines.append(f"Ответ принят: {view['answer']['text']}")
    if view.get("notice"):
        notice = view["notice"]
        lines.append(f"Обновление: {_NOTICE_LABELS.get(notice['code'], notice['message'])}")
        if notice.get("next_attempt_at"):
            lines.append(f"Следующая автоматическая попытка (UTC): {notice['next_attempt_at']}")
        lines.append(
            "Требуется ваше действие."
            if notice["owner_action_required"]
            else "От вас ничего не требуется."
        )
    if view.get("result"):
        lines.append(f"Итог: {view['result']}")
    if view.get("error"):
        lines.append(f"Ошибка: {view['error']}")
    lines.append(
        "Задачи {tasks} · Исполнители {workers} · Проверки {gates} · Результаты {deliveries}".format(
            tasks=len(view.get("tasks", [])),
            workers=len(view.get("workers", [])),
            gates=len(view.get("gates", [])),
            deliveries=len(view.get("deliveries", [])),
        )
    )
    return "\n".join(lines)


def _one_terminal_worker(
    workers: Any, terminal_statuses: set[str]
) -> bool:
    if (
        not isinstance(workers, list)
        or not workers
        or not all(isinstance(worker, dict) for worker in workers)
    ):
        return False
    statuses = [worker.get("status") for worker in workers]
    return (
        statuses[-1] in terminal_statuses
        and all(status == "scheduled" for status in statuses[:-1])
    )


def _completion_result(view: dict[str, Any]) -> str:
    """Render one bounded owner result from the already verified projection."""
    def compact(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

    deliveries = {
        item.get("kind"): item
        for item in view.get("deliveries", [])
        if isinstance(item, dict)
    }
    lines = [f"Выполнено: {compact(view.get('goal'), 700)}"]
    for label, kind in (("PR", "pull_request"), ("Merge-коммит", "default_branch")):
        url = deliveries.get(kind, {}).get("url")
        if isinstance(url, str) and url.strip():
            lines.append(f"{label}: {compact(url, 512)}")
    lines.append("Проверки: тесты, независимое ревью, CI, post-verify и очистка пройдены")
    if view.get("delivery_mode") == "none":
        lines.append("Деплой: не требуется для этого проекта")
    paths = sorted({
        item.get("path")
        for item in view.get("changes", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    })
    if paths:
        visible = ", ".join(compact(path, 120) for path in paths[:8])
        if len(paths) > 8:
            visible += f", ещё {len(paths) - 8}"
        lines.append(f"Изменённые файлы ({len(paths)}): {visible}")
    result = "\n".join(lines)
    return (
        result
        if len(result) <= _MAX_COMPLETION_RESULT_CHARS
        else result[:_MAX_COMPLETION_RESULT_CHARS - 1].rstrip() + "…"
    )


def completion_ready(view: dict[str, Any]) -> bool:
    """Apply the narrow A7.3 one-task delivery completion policy."""
    if (
        view.get("status") != "active"
        or view.get("question") is not None
    ):
        return False
    tasks = view.get("tasks")
    workers = view.get("workers")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or tasks[0].get("status") not in {"done", "archived"}
        or not _one_terminal_worker(workers, {"success", "completed"})
    ):
        return False
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    if any(gates.get(gate_id) != "passed" for gate_id in _COMPLETION_GATES):
        return False
    deliveries = {
        item.get("kind"): item.get("status")
        for item in view.get("deliveries", [])
        if isinstance(item, dict)
    }
    if not all(
        deliveries.get(kind) == status
        for kind, status in _COMPLETION_DELIVERIES.items()
    ):
        return False
    mode = view.get("delivery_mode")
    if mode is None:
        return True
    return mode == "none" and deliveries.get("delivery") == "not_applicable"


def rejection_ready(view: dict[str, Any]) -> bool:
    """Apply the narrow A7.3 exhausted-cycle failure policy."""
    if (
        view.get("status") != "active"
        or view.get("question") is not None
    ):
        return False
    tasks = view.get("tasks")
    workers = view.get("workers")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or tasks[0].get("status") not in {"done", "archived"}
        or not _one_terminal_worker(workers, {"completed"})
    ):
        return False
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    deliveries = {
        item.get("kind"): item.get("status")
        for item in view.get("deliveries", [])
        if isinstance(item, dict)
    }
    if gates in (
        {"tests": "passed", "review": "failed", "cleanup": "passed"},
        {"tests": "failed", "cleanup": "passed"},
        {"execution": "failed", "cleanup": "passed"},
    ):
        return not deliveries or deliveries == {"pull_request": "failed"}
    if gates == {
        "tests": "passed", "review": "passed", "ci": "failed", "cleanup": "passed",
    }:
        return deliveries == {"pull_request": "failed"}
    return gates == {
        "tests": "passed", "review": "passed", "ci": "passed",
        "post-verify": "failed", "cleanup": "passed",
    } and deliveries == {"pull_request": "merged"}


def _rejection_terminal(view: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    if not rejection_ready(view):
        return None
    gates = {
        item.get("gate_id"): item.get("status")
        for item in view.get("gates", [])
        if isinstance(item, dict)
    }
    if gates.get("execution") == "failed":
        return "central:auto-execution-state-failed:v1", {
            "error": "Прерванное выполнение потеряло рабочую копию и безопасно остановлено",
        }
    if gates.get("tests") == "failed":
        return "central:auto-author-checks-failed:v1", {
            "error": "Автоматические проверки не прошли после разрешённого числа попыток",
        }
    if gates.get("post-verify") == "failed":
        return "central:auto-post-verify-failed:v1", {
            "error": "Проверка после слияния не прошла после автоматического исправления",
        }
    if gates.get("ci") == "failed":
        return "central:auto-ci-failed:v1", {
            "error": "Обязательный CI не прошёл после разрешённого числа попыток",
        }
    return "central:auto-review-rejected:v1", {
        "error": "Независимое ревью отклонило результат",
    }


class MissionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
            self.path.touch(mode=0o600, exist_ok=True)
            os.chmod(self.path, 0o600)
        self._init_schema()

    def _harden_permissions(self) -> None:
        if os.name != "posix":
            return
        os.chmod(self.path.parent, 0o700)
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
        ):
            if candidate.exists():
                os.chmod(candidate, 0o600)

    @classmethod
    def default(cls) -> "MissionStore":
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        return cls(home / "missions-v1.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        self._harden_permissions()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_permissions()

    def _init_schema(self) -> None:
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mission_events (
                    mission_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    producer_event_id TEXT,
                    PRIMARY KEY (mission_id, sequence),
                    UNIQUE (mission_id, event_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS mission_producer_event
                    ON mission_events(mission_id, producer_event_id)
                    WHERE producer_event_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS mission_tombstones (
                    mission_id TEXT PRIMARY KEY,
                    pruned_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_subscriptions (
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    last_notified_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease TEXT,
                    notification_lease_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease_until REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (platform, chat_id, thread_id)
                );
                CREATE TABLE IF NOT EXISTS mission_subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    previous_mission_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    related_mission_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    UNIQUE (
                        platform, chat_id, thread_id, previous_mission_id,
                        mission_id, reason, related_mission_id
                    )
                );
                CREATE TABLE IF NOT EXISTS mission_intake_drafts (
                    platform TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    selected_project_id TEXT,
                    selection_message_id TEXT,
                    mission_id TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (platform, scope_key)
                );
                CREATE TABLE IF NOT EXISTS mission_intake_selection_receipts (
                    platform TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    source_text_sha256 TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (platform, scope_key, source_message_id)
                );
                CREATE TABLE IF NOT EXISTS mission_intake_cancel_receipts (
                    platform TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    source_text_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (platform, scope_key, source_message_id)
                );
                CREATE TABLE IF NOT EXISTS mission_media_jobs (
                    mission_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    lease_until REAL NOT NULL,
                    thread_id TEXT,
                    artifact_json TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_onboarding_requests (
                    request_id TEXT PRIMARY KEY,
                    owner_scope_sha256 TEXT NOT NULL,
                    project_id TEXT NOT NULL UNIQUE,
                    repository TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    preset TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    error_code TEXT,
                    invocations_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(mission_subscriptions)")
            }
            if "notification_lease" not in columns:
                connection.execute(
                    "ALTER TABLE mission_subscriptions ADD COLUMN notification_lease TEXT"
                )
            if "notification_lease_sequence" not in columns:
                connection.execute(
                    """ALTER TABLE mission_subscriptions
                       ADD COLUMN notification_lease_sequence INTEGER NOT NULL DEFAULT 0"""
                )
            if "notification_lease_until" not in columns:
                connection.execute(
                    """ALTER TABLE mission_subscriptions
                       ADD COLUMN notification_lease_until REAL NOT NULL DEFAULT 0"""
                )
            onboarding_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(project_onboarding_requests)"
                )
            }
            if "invocations_json" not in onboarding_columns:
                connection.execute(
                    "ALTER TABLE project_onboarding_requests ADD COLUMN invocations_json TEXT"
                )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission_id": row["mission_id"],
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "occurred_at": row["occurred_at"],
            "type": row["type"],
            "source": row["source"],
            "correlation": json.loads(row["correlation_json"]),
            "payload": json.loads(row["payload_json"]),
        }

    def events(self, mission_id: str, after: int = 0) -> list[dict[str, Any]]:
        mission_id = _require_id(mission_id, "mission_id")
        if not isinstance(after, int) or after < 0:
            raise MissionError("invalid mission cursor")
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? AND sequence > ? ORDER BY sequence",
                (mission_id, after),
            ).fetchall()
        return [self._row(row) for row in rows]

    def projection(self, mission_id: str) -> dict[str, Any]:
        events = self.events(mission_id)
        if not events:
            raise MissionError("mission not found")
        return project(events)

    def claim_media_job(self, mission_id: str) -> dict[str, Any]:
        """Claim one media generation; an expired active claim never retries."""
        mission_id = _require_id(mission_id, "mission_id")
        view = self.projection(mission_id)
        if view.get("capability") != _MEDIA_CAPABILITY:
            raise MissionError("mission is not an image generation task")
        now = time.time()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mission_media_jobs WHERE mission_id = ?", (mission_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO mission_media_jobs(
                           mission_id, state, lease_until, updated_at
                       ) VALUES (?, 'running', ?, ?)""",
                    (mission_id, now + _MEDIA_LEASE_SECONDS, _utc_now()),
                )
                return {"state": "claimed"}
            current = dict(row)
            if current["state"] == "running" and current["lease_until"] <= now:
                error = (
                    "Предыдущий image-generation turn был прерван с неоднозначным результатом; "
                    "автоматический повтор отключён, чтобы не создать второе изображение."
                )
                connection.execute(
                    """UPDATE mission_media_jobs
                       SET state = 'failed', error = ?, updated_at = ?
                       WHERE mission_id = ? AND state = 'running'""",
                    (error, _utc_now(), mission_id),
                )
                current.update(state="failed", error=error)
            return current

    def set_media_thread(self, mission_id: str, thread_id: str) -> None:
        thread_id = _require_id(thread_id, "media thread_id")
        with self._db() as connection:
            updated = connection.execute(
                """UPDATE mission_media_jobs
                   SET thread_id = ?, updated_at = ?
                   WHERE mission_id = ? AND state = 'running' AND thread_id IS NULL""",
                (thread_id, _utc_now(), mission_id),
            )
            if updated.rowcount != 1:
                raise MissionError("media generation claim is no longer active")

    def record_media_success(self, mission_id: str, artifact: dict[str, Any]) -> None:
        public = {
            key: artifact.get(key)
            for key in (
                "artifact_id", "name", "media_type", "size_bytes", "sha256",
                "model", "provider", "thread_id", "path",
            )
        }
        if not all(public.values()):
            raise MissionError("incomplete media artifact")
        with self._db() as connection:
            updated = connection.execute(
                """UPDATE mission_media_jobs
                   SET state = 'succeeded', lease_until = 0, thread_id = ?,
                       artifact_json = ?, error = NULL, updated_at = ?
                   WHERE mission_id = ? AND state = 'running'""",
                (
                    public["thread_id"], _json(public), _utc_now(), mission_id,
                ),
            )
            if updated.rowcount != 1:
                raise MissionError("media generation claim is no longer active")

    def record_media_failure(self, mission_id: str, error: str) -> None:
        message = " ".join(str(error or "image generation failed").split())[:3_000]
        with self._db() as connection:
            connection.execute(
                """UPDATE mission_media_jobs
                   SET state = 'failed', lease_until = 0, error = ?, updated_at = ?
                   WHERE mission_id = ? AND state = 'running'""",
                (message, _utc_now(), mission_id),
            )

    def media_artifact(self, mission_id: str) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT artifact_json FROM mission_media_jobs WHERE mission_id = ?",
                (_require_id(mission_id, "mission_id"),),
            ).fetchone()
        return json.loads(row["artifact_json"]) if row and row["artifact_json"] else None

    def media_artifact_file(
        self, mission_id: str, artifact_id: str
    ) -> tuple[Path, dict[str, Any]]:
        artifact_id = _require_id(artifact_id, "artifact_id")
        artifact = self.media_artifact(mission_id)
        if not artifact or artifact.get("artifact_id") != artifact_id:
            raise MissionError("artifact not found")
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").resolve()
        root = (home / "media-artifacts" / _require_id(mission_id, "mission_id")).resolve()
        path = Path(str(artifact.get("path") or "")).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise MissionError("invalid artifact path") from error
        if (
            not path.is_file()
            or path.stat().st_size != artifact.get("size_bytes")
            or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256")
        ):
            raise MissionError("artifact integrity check failed")
        return path, artifact

    def finalize_media_job(self, mission_id: str) -> dict[str, Any]:
        """Project one stored media outcome idempotently into the mission log."""
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM mission_media_jobs WHERE mission_id = ?",
                (_require_id(mission_id, "mission_id"),),
            ).fetchone()
        if row is None or row["state"] == "running":
            return self.projection(mission_id)

        def append(event_type: str, suffix: str, payload: dict[str, Any]) -> None:
            submission = {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": event_type,
                "source": "central-hermes",
                "correlation": {"producer_event_id": f"central:media:{suffix}:v1"},
                "payload": payload,
            }
            if event_type == "mission.completed":
                self._append(mission_id, submission)
            else:
                self.append_central(mission_id, submission)

        if row["state"] == "succeeded":
            artifact = json.loads(row["artifact_json"])
            append("mission.stage", "stage", {"stage": "verifying", "progress_percent": 90})
            append("artifact.upsert", "artifact", {
                "artifact_id": artifact["artifact_id"],
                "kind": "image",
                "name": artifact["name"],
                "media_type": artifact["media_type"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
            })
            append("task.upsert", "task-done", {
                "task_id": "media-image", "title": "Generate image", "status": "done",
            })
            append("worker.upsert", "worker-done", {
                "worker_id": "codex-imagegen", "status": "completed",
                "run_id": artifact["thread_id"], "profile": "gpt-image-2",
            })
            append("mission.completed", "complete", {
                "result": f"Изображение готово: {artifact['name']} ({artifact['media_type']}, {artifact['size_bytes']} bytes).",
            })
        else:
            append("task.upsert", "task-failed", {
                "task_id": "media-image", "title": "Generate image", "status": "failed",
            })
            append("worker.upsert", "worker-failed", {
                "worker_id": "codex-imagegen", "status": "failed",
                "run_id": row["thread_id"] or "unknown", "profile": "gpt-image-2",
            })
            append("mission.failed", "failed", {"error": row["error"] or "Image generation failed"})
        return self.projection(mission_id)

    def start_media_projection(self, mission_id: str) -> None:
        for event_type, suffix, payload in (
            ("mission.stage", "planning", {"stage": "planning", "progress_percent": 10}),
            ("task.upsert", "task-running", {
                "task_id": "media-image", "title": "Generate image", "status": "running",
            }),
            ("worker.upsert", "worker-scheduled", {
                "worker_id": "codex-imagegen", "status": "scheduled", "profile": "gpt-image-2",
            }),
        ):
            self.append_central(mission_id, {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": event_type,
                "source": "central-hermes",
                "correlation": {"producer_event_id": f"central:media:{suffix}:v1"},
                "payload": payload,
            })

    def media_thread_started(self, mission_id: str, thread_id: str) -> None:
        self.set_media_thread(mission_id, thread_id)
        self.append_central(mission_id, {
            "schema_version": SCHEMA_VERSION,
            "mission_id": mission_id,
            "type": "worker.upsert",
            "source": "central-hermes",
            "correlation": {"producer_event_id": "central:media:worker-running:v1"},
            "payload": {
                "worker_id": "codex-imagegen", "status": "running",
                "run_id": thread_id, "profile": "gpt-image-2",
            },
        })

    def workspace_payload(self, mission_id: str, after: int = 0) -> dict[str, Any]:
        view = self.projection(mission_id)
        return {
            "mission": view,
            "events": self.events(mission_id, after),
            "cursor": view["sequence"],
        }

    def channel_evidence(self, mission_id: str) -> dict[str, Any]:
        """Return privacy-safe authoritative channel convergence state."""
        view = self.projection(mission_id)
        with self._db() as connection:
            rows = connection.execute(
                """SELECT last_notified_sequence FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (mission_id,),
            ).fetchall()
        telegram_cursor = min(
            (int(row["last_notified_sequence"]) for row in rows), default=None
        )
        telegram_converged = (
            telegram_cursor is not None and telegram_cursor == view["sequence"]
        )
        return {
            "workspace": {
                "cursor": view["sequence"],
                "projection_id": view["projection_id"],
            },
            "telegram": {
                "subscriber_count": len(rows),
                "cursor": telegram_cursor,
                "projection_id": (
                    view["projection_id"] if telegram_converged else None
                ),
            },
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._db() as connection:
            rows = connection.execute(
                """SELECT mission_id, MAX(rowid) AS last_row
                   FROM mission_events GROUP BY mission_id
                   ORDER BY last_row DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self.projection(row["mission_id"]) for row in rows]

    @staticmethod
    def _project_onboarding_row(row: sqlite3.Row) -> dict[str, Any]:
        checkpoint = str(row["checkpoint"])
        return {
            "request_id": row["request_id"],
            "project_id": row["project_id"],
            "repository": row["repository"],
            "name": row["name"],
            "description": row["description"],
            "preset": row["preset"],
            "checkpoint": checkpoint,
            "invocations": (
                json.loads(row["invocations_json"])
                if row["invocations_json"] is not None
                else None
            ),
            "progress_percent": _PROJECT_ONBOARDING_PROGRESS.get(checkpoint, 0),
            "error_code": row["error_code"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def request_project_onboarding(
        self, name: str, description: str, preset: str
    ) -> tuple[dict[str, Any], bool]:
        """Create or replay one server-owned repository onboarding request."""
        name = _require_source_value(name, "project name")
        if not isinstance(description, str):
            raise MissionError("invalid project description")
        description = _require_source_value(
            description, "project description", optional=True
        )
        if (
            not _PROJECT_REPOSITORY_NAME.fullmatch(name)
            or name.casefold().endswith(".git")
        ):
            raise MissionError("invalid project name")
        if not isinstance(preset, str) or preset not in _PROJECT_ONBOARDING_PRESETS:
            raise MissionError("invalid project preset")
        project_id = name.casefold()
        repository = f"{_PROJECT_ONBOARDING_OWNER}/{name}"
        payload = {
            "description": description,
            "name": name,
            "preset": preset,
        }
        payload_sha256 = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
        owner_scope = _PROJECT_ONBOARDING_OWNER.casefold()
        owner_scope_sha256 = hashlib.sha256(owner_scope.encode("utf-8")).hexdigest()
        identity = hashlib.sha256(
            f"{owner_scope}\0{project_id}".encode("utf-8")
        ).hexdigest()[:32]
        request_id = f"project-onboarding-{identity}"

        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if previous:
                if previous["payload_sha256"] != payload_sha256:
                    raise MissionError("project onboarding idempotency collision")
                return self._project_onboarding_row(previous), False
            raw_catalog = os.environ.get("HERMES_MISSION_PROJECTS", "").strip()
            if raw_catalog:
                projects = registered_intake_projects("workspace")
                if any(
                    project.get("project_id", "").casefold() == project_id
                    or project.get("repository", "").casefold()
                    == repository.casefold()
                    for project in projects
                ):
                    raise MissionError("project is already registered")
            now = _utc_now()
            connection.execute(
                """INSERT INTO project_onboarding_requests(
                       request_id, owner_scope_sha256, project_id, repository,
                       name, description, preset, payload_sha256, checkpoint,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?)""",
                (
                    request_id, owner_scope_sha256, project_id, repository,
                    name, description, preset, payload_sha256, now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        assert row is not None
        return self._project_onboarding_row(row), True

    def project_onboarding(self, request_id: str) -> dict[str, Any]:
        request_id = _require_id(request_id, "project onboarding request_id")
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise MissionError("project onboarding request not found")
        return self._project_onboarding_row(row)

    def pending_project_onboarding(self) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                """SELECT * FROM project_onboarding_requests
                   WHERE checkpoint NOT IN ('ready', 'failed')
                   ORDER BY created_at, request_id LIMIT 1"""
            ).fetchone()
        return self._project_onboarding_row(row) if row else None

    def record_project_onboarding_invocation(
        self, request_id: str, invocation: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Append one systemd InvocationID to a bounded durable chain summary."""
        request_id = _require_id(request_id, "project onboarding request_id")
        if (
            not isinstance(invocation, dict)
            or set(invocation) != {"unit", "invocation_id"}
            or invocation.get("unit") != "hermes-project-onboarding.service"
            or not re.fullmatch(
                r"[0-9a-f]{32}", str(invocation.get("invocation_id") or "")
            )
        ):
            raise MissionError("invalid project onboarding systemd invocation")

        def valid_history(value: Any) -> bool:
            if (
                not isinstance(value, dict)
                or set(value) != {"count", "first", "last", "chain_sha256"}
                or isinstance(value.get("count"), bool)
                or not isinstance(value.get("count"), int)
                or value["count"] < 1
                or not re.fullmatch(
                    r"[0-9a-f]{64}", str(value.get("chain_sha256") or "")
                )
            ):
                return False
            for endpoint in (value.get("first"), value.get("last")):
                if (
                    not isinstance(endpoint, dict)
                    or set(endpoint) != {"unit", "invocation_id"}
                    or endpoint.get("unit") != "hermes-project-onboarding.service"
                    or not re.fullmatch(
                        r"[0-9a-f]{32}", str(endpoint.get("invocation_id") or "")
                    )
                ):
                    return False
            if value["count"] == 1:
                return value["first"] == value["last"] and value[
                    "chain_sha256"
                ] == hashlib.sha256(_json({
                    "invocation_id": value["first"]["invocation_id"],
                    "previous": None,
                    "unit": value["first"]["unit"],
                }).encode("utf-8")).hexdigest()
            return True

        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise MissionError("project onboarding request not found")
            if row["checkpoint"] in {"ready", "failed"}:
                raise MissionError("project onboarding is terminal")
            history = (
                json.loads(row["invocations_json"])
                if row["invocations_json"] is not None
                else None
            )
            if history is not None and not valid_history(history):
                raise MissionError("stored project onboarding invocation history is invalid")
            if history is not None and history["last"] == invocation:
                return self._project_onboarding_row(row), False
            previous = None if history is None else history["chain_sha256"]
            chain = hashlib.sha256(_json({
                "invocation_id": invocation["invocation_id"],
                "previous": previous,
                "unit": invocation["unit"],
            }).encode("utf-8")).hexdigest()
            updated_history = {
                "count": 1 if history is None else history["count"] + 1,
                "first": invocation if history is None else history["first"],
                "last": invocation,
                "chain_sha256": chain,
            }
            updated = connection.execute(
                """UPDATE project_onboarding_requests
                   SET invocations_json = ?, updated_at = ?
                   WHERE request_id = ? AND checkpoint = ?""",
                (_json(updated_history), _utc_now(), request_id, row["checkpoint"]),
            )
            if updated.rowcount != 1:
                raise MissionError("project onboarding checkpoint changed")
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        assert row is not None
        return self._project_onboarding_row(row), True

    def advance_project_onboarding(
        self,
        request_id: str,
        expected_checkpoint: str,
        checkpoint: str,
        *,
        error_code: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Compare-and-swap one onboarding checkpoint, with idempotent replay."""
        request_id = _require_id(request_id, "project onboarding request_id")
        expected_checkpoint = _require_id(
            expected_checkpoint, "project onboarding expected checkpoint"
        )
        checkpoint = _require_id(checkpoint, "project onboarding checkpoint")
        valid = {*_PROJECT_ONBOARDING_CHECKPOINTS, "failed"}
        if expected_checkpoint not in valid or checkpoint not in valid:
            raise MissionError("invalid project onboarding checkpoint")
        if checkpoint == "failed":
            error_code = _require_id(error_code, "project onboarding error_code")
        elif error_code is not None:
            raise MissionError("project onboarding error_code requires failed checkpoint")

        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise MissionError("project onboarding request not found")
            current = str(row["checkpoint"])
            if current == checkpoint:
                if row["error_code"] != error_code:
                    raise MissionError("project onboarding checkpoint collision")
                return self._project_onboarding_row(row), False
            if current != expected_checkpoint:
                raise MissionError("project onboarding checkpoint changed")
            if current in {"ready", "failed"}:
                raise MissionError("project onboarding is terminal")
            if current not in _PROJECT_ONBOARDING_CHECKPOINTS:
                raise MissionError("invalid stored project onboarding checkpoint")
            next_index = _PROJECT_ONBOARDING_CHECKPOINTS.index(current) + 1
            required = (
                _PROJECT_ONBOARDING_CHECKPOINTS[next_index]
                if next_index < len(_PROJECT_ONBOARDING_CHECKPOINTS)
                else None
            )
            if checkpoint != "failed" and checkpoint != required:
                raise MissionError("project onboarding checkpoint is not forward-only")
            updated = connection.execute(
                """UPDATE project_onboarding_requests
                   SET checkpoint = ?, error_code = ?, updated_at = ?
                   WHERE request_id = ? AND checkpoint = ?""",
                (checkpoint, error_code, _utc_now(), request_id, current),
            )
            if updated.rowcount != 1:
                raise MissionError("project onboarding checkpoint changed")
            row = connection.execute(
                "SELECT * FROM project_onboarding_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        assert row is not None
        return self._project_onboarding_row(row), True

    def _prune_terminal(self, connection: sqlite3.Connection, keep: int) -> int:
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        last_row: dict[str, int] = {}
        for row in connection.execute("SELECT rowid, * FROM mission_events ORDER BY rowid"):
            grouped.setdefault(row["mission_id"], []).append(self._row(row))
            last_row[row["mission_id"]] = row["rowid"]
        # ponytail: replaying the bounded single-owner ledger avoids another lifecycle index.
        views = {mission_id: project(events) for mission_id, events in grouped.items()}
        active = {
            mission_id for mission_id, view in views.items()
            if view["status"] in {"active", "waiting_owner"}
        }
        protected = {
            row["mission_id"]
            for row in connection.execute("SELECT mission_id FROM mission_subscriptions")
        }
        for mission_id, view in views.items():
            parent = view.get("parent_mission_id")
            # A terminal repair keeps the Telegram binding until its terminal
            # notification is checkpointed.  Retain the parent needed by the
            # subsequent atomic binding restore throughout that handoff.
            if isinstance(parent, str) and mission_id in protected:
                protected.add(parent)
            if mission_id in active and isinstance(parent, str):
                protected.add(parent)
            if isinstance(parent, str) and parent in active:
                protected.add(mission_id)
        terminal = sorted(
            (
                mission_id for mission_id, view in views.items()
                if view["status"] in {"completed", "failed", "cancelled"}
                and mission_id not in protected
            ),
            key=last_row.__getitem__,
            reverse=True,
        )
        pruned = terminal[keep:]
        for mission_id in pruned:
            connection.execute(
                """INSERT INTO mission_tombstones(mission_id, pruned_at)
                   VALUES (?, ?) ON CONFLICT(mission_id) DO NOTHING""",
                (mission_id, _utc_now()),
            )
            connection.execute(
                """DELETE FROM mission_subscription_history
                   WHERE previous_mission_id = ? OR mission_id = ? OR related_mission_id = ?""",
                (mission_id, mission_id, mission_id),
            )
            connection.execute(
                "DELETE FROM mission_events WHERE mission_id = ?", (mission_id,)
            )
            connection.execute(
                "DELETE FROM mission_intake_selection_receipts WHERE mission_id = ?",
                (mission_id,),
            )
        return len(pruned)

    def prune_terminal(self, keep: int = _MAX_RETAINED_TERMINAL_MISSIONS) -> int:
        """Remove old unbound terminal missions while keeping recent owner history."""
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
            raise MissionError("invalid terminal mission retention")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._prune_terminal(connection, keep)

    def dispatch_candidates(
        self, dispatch_profile: str, limit: int = 1, *, reconcile: bool = False
    ) -> list[dict[str, Any]]:
        dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        limit = max(1, min(int(limit), 100))
        if not reconcile:
            limit = 1
        with self._db() as connection:
            rows = connection.execute(
                """SELECT mission_id, payload_json FROM mission_events
                   WHERE sequence = 1 AND type = 'mission.accepted'
                   ORDER BY rowid"""
            ).fetchall()
        candidates = []
        # ponytail: this full accepted-row scan is enough at single-owner scale;
        # add a durable dispatch index only after measured volume justifies it.
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("dispatch_profile") != dispatch_profile:
                continue
            view = self.projection(row["mission_id"])
            if (
                not reconcile
                and view["status"] in {"active", "waiting_owner"}
                and bool(view["tasks"])
            ):
                return []
            eligible = (
                reconcile
                and view["status"] in {"active", "waiting_owner"}
                and bool(view["tasks"])
            ) or (
                not reconcile
                and view["status"] == "active"
                and view["stage"] == "accepted"
                and not view["tasks"]
            )
            if eligible and len(candidates) < limit:
                candidates.append(view)
                if reconcile and len(candidates) == limit:
                    break
        return candidates

    def latest(self) -> str | None:
        missions = self.list(1)
        return missions[0]["mission_id"] if missions else None

    def _bound_answer_receipt(
        self,
        platform: str,
        chat_id: str,
        thread_id: str,
        source_message_id: str,
    ) -> dict[str, Any] | None:
        """Find a prior answer even after the owner chat moved to a later mission."""
        with self._db() as connection:
            related = {
                row["mission_id"]
                for row in connection.execute(
                    """SELECT mission_id FROM mission_subscriptions
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                    (platform, chat_id, thread_id),
                )
            }
            for row in connection.execute(
                """SELECT previous_mission_id, mission_id, related_mission_id
                   FROM mission_subscription_history
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                (platform, chat_id, thread_id),
            ):
                related.update(value for value in row if value)
            matches = [
                self._row(row)
                for row in connection.execute(
                    """SELECT * FROM mission_events
                       WHERE type = 'mission.answer' ORDER BY rowid DESC"""
                )
                if row["mission_id"] in related
                and json.loads(row["payload_json"]).get("source_message_id")
                == source_message_id
            ]
        if len(matches) > 1:
            raise MissionError("owner turn source identity collision")
        return matches[0] if matches else None

    def _session_missions(self, session_id: str) -> list[str]:
        """Return root and repair missions owned by one Central session."""
        with self._db() as connection:
            accepted = [
                self._row(row)
                for row in connection.execute(
                    """SELECT * FROM mission_events
                       WHERE sequence = 1 AND type = 'mission.accepted'
                       ORDER BY rowid"""
                )
            ]
        related: list[str] = []
        for event in accepted:
            if (
                event["correlation"].get("session_id") == session_id
                or event["payload"].get("parent_mission_id") in related
            ):
                related.append(event["mission_id"])
        return related

    def _session_answer_receipt(
        self, session_id: str, source_message_id: str
    ) -> dict[str, Any] | None:
        """Find a prior Workspace answer after restart or later session turns."""
        related = set(self._session_missions(session_id))
        if not related:
            return None
        with self._db() as connection:
            matches = [
                self._row(row)
                for row in connection.execute(
                    """SELECT * FROM mission_events
                       WHERE type = 'mission.answer' ORDER BY rowid DESC"""
                )
                if row["mission_id"] in related
                and json.loads(row["payload_json"]).get("source_message_id")
                == source_message_id
            ]
        if len(matches) > 1:
            raise MissionError("owner turn source identity collision")
        return matches[0] if matches else None

    def _session_open_question(
        self, session_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        matches = []
        for mission_id in self._session_missions(session_id):
            view = self.projection(mission_id)
            question = view.get("question")
            if view.get("status") == "waiting_owner" and isinstance(question, dict):
                matches.append((mission_id, question))
        if len(matches) > 1:
            raise MissionError("session has multiple open mission questions")
        return matches[0] if matches else None

    @staticmethod
    def _intake_scope(
        platform: str, session_id: str, chat_id: str, thread_id: str
    ) -> str:
        if chat_id:
            return _json({"chat_id": chat_id, "thread_id": thread_id})
        if session_id:
            return _json({"session_id": session_id})
        raise MissionError("mission intake requires a channel identity")

    def _intake_draft(self, platform: str, scope_key: str) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                (platform, scope_key),
            ).fetchone()
        return dict(row) if row else None

    def _intake_selection_receipt(
        self, platform: str, scope_key: str, source_message_id: str
    ) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                """SELECT * FROM mission_intake_selection_receipts
                   WHERE platform = ? AND scope_key = ? AND source_message_id = ?""",
                (platform, scope_key, source_message_id),
            ).fetchone()
        return dict(row) if row else None

    def _intake_cancel_receipt(
        self, platform: str, scope_key: str, source_message_id: str
    ) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                """SELECT * FROM mission_intake_cancel_receipts
                   WHERE platform = ? AND scope_key = ? AND source_message_id = ?""",
                (platform, scope_key, source_message_id),
            ).fetchone()
        return dict(row) if row else None

    def _cancel_intake_draft(
        self,
        *,
        platform: str,
        scope_key: str,
        source_message_id: str,
        text: str,
    ) -> None:
        digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """SELECT * FROM mission_intake_cancel_receipts
                   WHERE platform = ? AND scope_key = ? AND source_message_id = ?""",
                (platform, scope_key, source_message_id),
            ).fetchone()
            if previous:
                if previous["source_text_sha256"] != digest:
                    raise MissionError("owner turn idempotency collision")
                return
            draft = connection.execute(
                "SELECT * FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                (platform, scope_key),
            ).fetchone()
            if (
                not draft
                or draft["mission_id"]
                or draft["selection_message_id"]
            ):
                raise MissionError("выбор проекта уже завершён")
            connection.execute(
                """INSERT INTO mission_intake_cancel_receipts(
                       platform, scope_key, source_message_id,
                       source_text_sha256, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (platform, scope_key, source_message_id, digest, _utc_now()),
            )
            connection.execute(
                "DELETE FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                (platform, scope_key),
            )

    def _save_intake_draft(
        self,
        *,
        platform: str,
        scope_key: str,
        goal: str,
        source_message_id: str,
        session_id: str,
        chat_id: str,
        thread_id: str,
    ) -> None:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                (platform, scope_key),
            ).fetchone()
            if current:
                if (
                    current["goal"] != goal.strip()
                    or current["source_message_id"] != source_message_id
                ):
                    raise MissionProjectRequired(public_intake_projects(platform))
                return
            connection.execute(
                """INSERT INTO mission_intake_drafts(
                       platform, scope_key, goal, source_message_id, session_id,
                       chat_id, thread_id, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    platform, scope_key, goal.strip(), source_message_id, session_id,
                    chat_id, thread_id, _utc_now(),
                ),
            )

    def _resolve_intake_draft(
        self,
        draft: dict[str, Any],
        *,
        platform: str,
        scope_key: str,
        selection: str,
        selection_message_id: str,
    ) -> tuple[dict[str, Any], bool] | None:
        if draft.get("mission_id"):
            if draft.get("selection_message_id") == selection_message_id:
                return self.events(str(draft["mission_id"]))[0], False
            with self._db() as connection:
                connection.execute(
                    "DELETE FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                    (platform, scope_key),
                )
            return None
        normalized = _project_alias(selection)
        projects = registered_intake_projects(platform)
        matches = [item for item in projects if normalized in item["aliases"]]
        if len(matches) != 1:
            raise MissionProjectRequired(public_intake_projects(platform))
        target = matches[0]
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                (platform, scope_key),
            ).fetchone()
            if not current:
                raise MissionError("выбор проекта уже отменён")
            if current["mission_id"]:
                raise MissionError("выбор проекта уже завершён")
            if current["selection_message_id"]:
                if (
                    current["selection_message_id"] != selection_message_id
                    or current["selected_project_id"] != target["project_id"]
                ):
                    raise MissionError("выбор проекта уже выполняется")
            else:
                updated = connection.execute(
                    """UPDATE mission_intake_drafts
                       SET selected_project_id = ?, selection_message_id = ?
                       WHERE platform = ? AND scope_key = ?
                         AND mission_id IS NULL AND selection_message_id IS NULL""",
                    (
                        target["project_id"], selection_message_id,
                        platform, scope_key,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionError("выбор проекта уже изменён")
        accepted, created = self.ingest_owner_goal(
            draft["goal"],
            platform=platform,
            project_id=target["project_id"],
            source_message_id=draft["source_message_id"],
            session_id=draft["session_id"] or None,
            chat_id=draft["chat_id"] or None,
            thread_id=draft["thread_id"] or None,
        )
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            digest = hashlib.sha256(selection.strip().encode("utf-8")).hexdigest()
            previous = connection.execute(
                """SELECT * FROM mission_intake_selection_receipts
                   WHERE platform = ? AND scope_key = ? AND source_message_id = ?""",
                (platform, scope_key, selection_message_id),
            ).fetchone()
            if previous:
                if (
                    previous["source_text_sha256"] != digest
                    or previous["mission_id"] != accepted["mission_id"]
                ):
                    raise MissionError("owner turn idempotency collision")
            else:
                connection.execute(
                    """INSERT INTO mission_intake_selection_receipts(
                           platform, scope_key, source_message_id,
                           source_text_sha256, mission_id, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        platform, scope_key, selection_message_id, digest,
                        accepted["mission_id"], _utc_now(),
                    ),
                )
            updated = connection.execute(
                """UPDATE mission_intake_drafts
                   SET mission_id = ?
                   WHERE platform = ? AND scope_key = ?
                     AND selected_project_id = ? AND selection_message_id = ?
                     AND mission_id IS NULL""",
                (
                    accepted["mission_id"], platform, scope_key,
                    target["project_id"], selection_message_id,
                ),
            )
            if updated.rowcount != 1:
                current = connection.execute(
                    "SELECT mission_id FROM mission_intake_drafts WHERE platform = ? AND scope_key = ?",
                    (platform, scope_key),
                ).fetchone()
                if not current or current["mission_id"] != accepted["mission_id"]:
                    raise MissionError("project selection checkpoint collision")
        return accepted, created

    def ingest_owner_turn(
        self,
        text: str,
        *,
        platform: str,
        source_message_id: str,
        session_id: str | None = None,
        chat_id: str | None = None,
        thread_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Answer the bound question, otherwise accept one new registered goal."""
        if not isinstance(text, str):
            raise MissionError("invalid owner turn")
        if not text.strip() or len(text) > _MAX_OWNER_GOAL_CHARS:
            raise MissionError("invalid owner turn")
        platform = _require_id(platform, "intake platform")
        source_message_id = _require_source_value(
            source_message_id, "source_message_id"
        )
        session_id = _require_source_value(
            session_id, "session_id", optional=True
        )
        chat_id = _require_source_value(chat_id, "chat_id", optional=True)
        thread_id = _require_source_value(
            thread_id, "thread_id", optional=True
        )
        scope_key = self._intake_scope(platform, session_id, chat_id, thread_id)
        selection_receipt = self._intake_selection_receipt(
            platform, scope_key, source_message_id
        )
        if selection_receipt:
            digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            if selection_receipt["source_text_sha256"] != digest:
                raise MissionError("owner turn idempotency collision")
            return self.events(selection_receipt["mission_id"])[0], False
        cancel_receipt = self._intake_cancel_receipt(
            platform, scope_key, source_message_id
        )
        if cancel_receipt:
            digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            if cancel_receipt["source_text_sha256"] != digest:
                raise MissionError("owner turn idempotency collision")
            raise MissionIntakeCancelled()
        if chat_id:
            receipt = self._bound_answer_receipt(
                platform, chat_id, thread_id, source_message_id
            )
            if receipt:
                if (
                    receipt["payload"].get("text") != text.strip()
                    or receipt["payload"].get("source_platform", platform) != platform
                ):
                    raise MissionError("owner turn idempotency collision")
                return receipt, False
            mission_id = self.bound_mission(platform, chat_id, thread_id)
            if mission_id:
                view = self.projection(mission_id)
                question = view.get("question")
                if view.get("status") == "waiting_owner" and isinstance(question, dict):
                    return self.answer(
                        mission_id,
                        question.get("question_id"),
                        text,
                        source_message_id=source_message_id,
                        source_platform=platform,
                    )
        elif session_id:
            receipt = self._session_answer_receipt(session_id, source_message_id)
            if receipt:
                if (
                    receipt["payload"].get("text") != text.strip()
                    or receipt["payload"].get("source_platform", platform) != platform
                ):
                    raise MissionError("owner turn idempotency collision")
                return receipt, False
            open_question = self._session_open_question(session_id)
            if open_question:
                mission_id, question = open_question
                return self.answer(
                    mission_id,
                    question.get("question_id"),
                    text,
                    source_message_id=source_message_id,
                    source_platform=platform,
                )
        # Topic capability dispatch: a server-owned allowlist of exact
        # Telegram (chat_id, thread_id) pairs routes ordinary text to
        # media.image.generate.  Telegram's message_thread_id is unique
        # within a chat, not globally, so both fields are required.
        # Ordered AFTER bound-question answering (a media mission's owner
        # question is still answerable in its topic) and BEFORE project-
        # selection drafts (media intake is projectless, so a configured
        # media topic never creates a draft; an unrelated stale draft in
        # the same scope cannot consume a media-topic message).
        if (
            platform == "telegram"
            and chat_id
            and thread_id
            and (chat_id, thread_id) in media_topic_pairs()
        ):
            if image_edit_requested(text):
                raise MissionError(
                    "subscription image editing is unavailable: the production Codex adapter does not pass source images"
                )
            return self.ingest_media_goal(
                text,
                platform=platform,
                source_message_id=source_message_id,
                session_id=session_id or None,
                chat_id=chat_id or None,
                thread_id=thread_id or None,
            )
        draft = self._intake_draft(platform, scope_key)
        if draft:
            if platform == "telegram" and _project_alias(text) in _INTAKE_CANCEL_ALIASES:
                self._cancel_intake_draft(
                    platform=platform,
                    scope_key=scope_key,
                    source_message_id=source_message_id,
                    text=text,
                )
                raise MissionIntakeCancelled()
            resolved = self._resolve_intake_draft(
                draft,
                platform=platform,
                scope_key=scope_key,
                selection=text,
                selection_message_id=source_message_id,
            )
            if resolved is not None:
                return resolved
        elif platform == "telegram" and _project_alias(text) in _INTAKE_CANCEL_ALIASES:
            raise MissionError("нет ожидающего выбора проекта")
        if image_edit_requested(text):
            raise MissionError(
                "subscription image editing is unavailable: the production Codex adapter does not pass source images"
            )
        media_prompt = image_generation_prompt(text)
        if media_prompt is not None:
            return self.ingest_media_goal(
                media_prompt,
                platform=platform,
                source_message_id=source_message_id,
                session_id=session_id or None,
                chat_id=chat_id or None,
                thread_id=thread_id or None,
            )
        registered_intake_projects(platform)
        try:
            target = registered_intake_target(
                platform, project_id=project_id, goal=text
            )
        except MissionProjectRequired:
            if platform == "telegram":
                self._save_intake_draft(
                    platform=platform,
                    scope_key=scope_key,
                    goal=text,
                    source_message_id=source_message_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    thread_id=thread_id,
                )
            raise
        return self.ingest_owner_goal(
            text,
            platform=platform,
            project_id=target["project_id"],
            source_message_id=source_message_id,
            session_id=session_id,
            chat_id=chat_id or None,
            thread_id=thread_id or None,
        )

    def ingest_media_goal(
        self,
        prompt: str,
        *,
        platform: str,
        source_message_id: str,
        session_id: str | None = None,
        chat_id: str | None = None,
        thread_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Accept one deterministic text-to-image mission without a repo route."""
        prompt = str(prompt or "").strip()
        if not prompt or len(prompt) > 8_192:
            raise MissionError("invalid image prompt")
        platform = _require_id(platform, "intake platform")
        if platform not in {"workspace", "telegram"}:
            raise MissionError("invalid intake platform")
        source_message_id = _require_source_value(source_message_id, "source_message_id")
        session_id = _require_source_value(session_id, "session_id", optional=True)
        chat_id = _require_source_value(chat_id, "chat_id", optional=True)
        thread_id = _require_source_value(thread_id, "thread_id", optional=True)
        if not session_id and not chat_id:
            raise MissionError("mission intake requires a channel identity")
        source_key = _json({
            "platform": platform,
            "session_id": session_id,
            "chat_id": chat_id,
            "thread_id": thread_id,
            "source_message_id": source_message_id,
        })
        digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        mission_id = "mission-intake-" + digest[:32]
        arguments = {
            "mission_id": mission_id,
            "session_id": session_id or None,
            "dispatch_profile": _MEDIA_DISPATCH_PROFILE,
            "capability": _MEDIA_CAPABILITY,
            "input_platform": platform,
            "input_source_key_sha256": digest,
            "input_source_message_sha256": hashlib.sha256(
                source_message_id.encode("utf-8")
            ).hexdigest(),
        }
        try:
            result = self.accept(prompt, **arguments)
        except MissionError as error:
            if str(error) == "mission already accepted":
                result = self.accept(prompt, **arguments)
            elif str(error) == "mission already accepted with different parameters":
                existing = self.events(mission_id)[0]
                if existing["payload"].get("input_source_key_sha256") != digest:
                    raise
                # mission_id is derived from the stable source_key, so the same
                # source message replayed with a different derived prompt (a
                # redelivered voice note whose local STT produced a slightly
                # different transcript) is a replay, not a new goal.  Return the
                # original mission instead of failing closed; a genuine source
                # collision (different input_source_key_sha256) still raises.
                result = existing, False
            else:
                raise
        if chat_id:
            self.bind(mission_id, platform, chat_id, thread_id, reason="owner-intake")
        return result

    def ingest_owner_goal(
        self,
        goal: str,
        *,
        platform: str,
        source_message_id: str,
        session_id: str | None = None,
        chat_id: str | None = None,
        thread_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Accept one ordinary owner turn exactly once on its registered route."""
        if not isinstance(goal, str):
            raise MissionError("invalid mission goal")
        if not isinstance(platform, str):
            raise MissionError("invalid intake platform")
        platform = _require_id(platform, "intake platform")
        target = registered_intake_target(
            platform, project_id=project_id, goal=goal
        )
        source_message_id = _require_source_value(
            source_message_id, "source_message_id"
        )
        session_id = _require_source_value(
            session_id, "session_id", optional=True
        )
        chat_id = _require_source_value(chat_id, "chat_id", optional=True)
        thread_id = _require_source_value(
            thread_id, "thread_id", optional=True
        )
        if not session_id and not chat_id:
            raise MissionError("mission intake requires a channel identity")
        source_key = _json(
            {
                "platform": platform,
                "session_id": session_id,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "source_message_id": source_message_id,
            }
        )
        # ponytail: deterministic acceptance identity is the durable receipt;
        # a second table would duplicate the same uniqueness invariant.
        source_key_sha256 = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        mission_id = "mission-intake-" + source_key_sha256[:32]
        arguments = {
            "mission_id": mission_id,
            "session_id": session_id or None,
            "dispatch_profile": target["dispatch_profile"],
            "delivery_mode": target["delivery_mode"],
            "project_id": target["project_id"],
            "input_platform": platform,
            "input_source_key_sha256": source_key_sha256,
            "input_source_message_sha256": hashlib.sha256(
                source_message_id.encode("utf-8")
            ).hexdigest(),
        }
        try:
            result = self.accept(goal, **arguments)
        except MissionError as error:
            # Two processes can both pass accept()'s optimistic read.  The
            # SQLite writer serializes them; re-read only this exact race so
            # changed goal/profile payloads still fail closed as collisions.
            if str(error) != "mission already accepted":
                raise
            result = self.accept(goal, **arguments)
        if chat_id:
            self.bind(
                result[0]["mission_id"], platform, chat_id, thread_id,
                reason="owner-intake",
            )
        return result

    def accept(
        self,
        goal: str,
        *,
        mission_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        dispatch_profile: str | None = None,
        delivery_mode: str | None = None,
        capability: str | None = None,
        project_id: str | None = None,
        parent_mission_id: str | None = None,
        input_platform: str | None = None,
        input_source_key_sha256: str | None = None,
        input_source_message_sha256: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        goal = str(goal or "").strip()
        if not goal or len(goal) > _MAX_OWNER_GOAL_CHARS:
            raise MissionError("invalid mission goal")
        mission_id = _require_id(mission_id or f"mission-{uuid.uuid4()}", "mission_id")
        if dispatch_profile is not None:
            dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        if project_id is not None:
            project_id = _require_id(project_id, "project_id")
        if delivery_mode is not None and delivery_mode != "none":
            raise MissionError("invalid mission delivery mode")
        if capability is not None and capability != _MEDIA_CAPABILITY:
            raise MissionError("invalid mission capability")
        if parent_mission_id is not None:
            parent_mission_id = _require_id(parent_mission_id, "parent_mission_id")
            if parent_mission_id == mission_id:
                raise MissionError("mission cannot be its own parent")
            self._require_repair_parent(parent_mission_id, mission_id)
        input_fields = (
            input_platform, input_source_key_sha256, input_source_message_sha256,
        )
        if any(value is not None for value in input_fields) and (
            input_platform not in {"workspace", "telegram"}
            or not isinstance(input_source_key_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", input_source_key_sha256)
            or not isinstance(input_source_message_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", input_source_message_sha256)
            or mission_id != f"mission-intake-{input_source_key_sha256[:32]}"
        ):
            raise MissionError("invalid mission input lineage")
        correlation = {
            key: value
            for key, value in (("session_id", session_id), ("run_id", run_id))
            if value
        }
        existing = self.events(mission_id)
        if existing:
            first = existing[0]
            exact_input = all(
                first["payload"].get(name) == value
                for name, value in (
                    ("input_platform", input_platform),
                    ("input_source_key_sha256", input_source_key_sha256),
                    ("input_source_message_sha256", input_source_message_sha256),
                )
            )
            legacy_input = (
                input_source_key_sha256 is not None
                and all(
                    first["payload"].get(name) is None
                    for name in (
                        "input_platform", "input_source_key_sha256",
                        "input_source_message_sha256",
                    )
                )
                and mission_id == f"mission-intake-{input_source_key_sha256[:32]}"
            )
            if (
                first["type"] == "mission.accepted"
                and first["payload"].get("goal") == goal
                and first["payload"].get("dispatch_profile") == dispatch_profile
                and first["payload"].get("delivery_mode") == delivery_mode
                and first["payload"].get("capability") == capability
                and first["payload"].get("project_id") == project_id
                and first["payload"].get("parent_mission_id") == parent_mission_id
                and (exact_input or legacy_input)
            ):
                if (
                    parent_mission_id is not None
                    and self.projection(mission_id).get("status") == "active"
                ):
                    self._inherit_parent_subscriptions(parent_mission_id, mission_id)
                self.prune_terminal()
                return first, False
            raise MissionError("mission already accepted with different parameters")
        payload = {"goal": goal}
        if project_id is not None:
            payload["project_id"] = project_id
        if dispatch_profile is not None:
            payload["dispatch_profile"] = dispatch_profile
        if delivery_mode is not None:
            payload["delivery_mode"] = delivery_mode
        if capability is not None:
            payload["capability"] = capability
        if parent_mission_id is not None:
            payload["parent_mission_id"] = parent_mission_id
        if input_source_key_sha256 is not None:
            payload.update(
                input_platform=input_platform,
                input_source_key_sha256=input_source_key_sha256,
                input_source_message_sha256=input_source_message_sha256,
            )
        accepted = self._append(
            mission_id,
            {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": "mission.accepted",
                "source": "central-hermes",
                "correlation": correlation,
                "payload": payload,
            },
        )
        if parent_mission_id is not None:
            self._inherit_parent_subscriptions(parent_mission_id, mission_id)
        self.prune_terminal()
        return accepted

    def _require_repair_parent(self, parent_mission_id: str, child_mission_id: str) -> None:
        parent = self.projection(parent_mission_id)
        if parent.get("status") != "active" or parent.get("parent_mission_id") is not None:
            raise MissionError("repair parent must be an active root mission")
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (parent_mission_id,),
            ).fetchall()
            if rows:
                if any(row["notification_lease_until"] > now for row in rows):
                    raise MissionError("repair parent notification in progress")
                return
            inherited = connection.execute(
                """SELECT 1 FROM mission_subscription_history AS history
                   JOIN mission_subscriptions AS current
                     ON current.platform = history.platform
                    AND current.chat_id = history.chat_id
                    AND current.thread_id = history.thread_id
                   WHERE history.previous_mission_id = ?
                     AND history.mission_id = ?
                     AND history.reason = 'repair-inherit'
                     AND history.related_mission_id = ?
                     AND current.mission_id = ?
                   LIMIT 1""",
                (
                    parent_mission_id, child_mission_id,
                    child_mission_id, child_mission_id,
                ),
            ).fetchone()
        if not inherited:
            raise MissionError("repair parent has no Telegram subscription")

    @staticmethod
    def _subscription_history(
        connection: sqlite3.Connection,
        row: sqlite3.Row | dict[str, Any],
        previous_mission_id: str,
        mission_id: str,
        reason: str,
        related_mission_id: str,
    ) -> None:
        connection.execute(
            """INSERT INTO mission_subscription_history(
                   platform, chat_id, thread_id, previous_mission_id,
                   mission_id, reason, related_mission_id, occurred_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(
                   platform, chat_id, thread_id, previous_mission_id,
                   mission_id, reason, related_mission_id
               ) DO NOTHING""",
            (
                row["platform"], row["chat_id"], row["thread_id"],
                previous_mission_id, mission_id, reason, related_mission_id,
                _utc_now(),
            ),
        )

    def _inherit_parent_subscriptions(
        self, parent_mission_id: str, child_mission_id: str
    ) -> None:
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (parent_mission_id,),
            ).fetchall()
            if not rows:
                current = connection.execute(
                    """SELECT 1 FROM mission_subscription_history AS history
                       JOIN mission_subscriptions AS subscription
                         ON subscription.platform = history.platform
                        AND subscription.chat_id = history.chat_id
                        AND subscription.thread_id = history.thread_id
                       WHERE history.previous_mission_id = ?
                         AND history.mission_id = ?
                         AND history.reason = 'repair-inherit'
                         AND history.related_mission_id = ?
                         AND subscription.mission_id = ?
                       LIMIT 1""",
                    (
                        parent_mission_id, child_mission_id,
                        child_mission_id, child_mission_id,
                    ),
                ).fetchone()
                if current:
                    return
                raise MissionError("repair parent has no Telegram subscription")
            if any(row["notification_lease_until"] > now for row in rows):
                raise MissionError("repair parent notification in progress")
            for row in rows:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET mission_id = ?, last_notified_sequence = 0,
                           notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ?""",
                    (
                        child_mission_id, row["platform"], row["chat_id"],
                        row["thread_id"], parent_mission_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionError("repair subscription inheritance lost its binding")
                self._subscription_history(
                    connection, row, parent_mission_id, child_mission_id,
                    "repair-inherit", child_mission_id,
                )

    def _restore_parent_subscriptions(
        self, connection: sqlite3.Connection, child_mission_id: str, parent_mission_id: str
    ) -> None:
        rows = connection.execute(
            """SELECT * FROM mission_subscriptions
               WHERE mission_id = ? AND platform = 'telegram'""",
            (child_mission_id,),
        ).fetchall()
        for row in rows:
            updated = connection.execute(
                """UPDATE mission_subscriptions
                   SET mission_id = ?, last_notified_sequence = 0,
                       notification_lease = NULL,
                       notification_lease_sequence = 0,
                       notification_lease_until = 0
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?""",
                (
                    parent_mission_id, row["platform"], row["chat_id"],
                    row["thread_id"], child_mission_id,
                ),
            )
            if updated.rowcount != 1:
                raise MissionError("repair subscription restoration lost its binding")
            self._subscription_history(
                connection, row, child_mission_id, parent_mission_id,
                "repair-restore", child_mission_id,
            )

    def answer(
        self,
        mission_id: str,
        question_id: str,
        text: str,
        *,
        source_message_id: str | None = None,
        source_platform: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Record one idempotent owner answer to the currently open question."""
        question_id = _require_id(question_id, "question_id")
        text = str(text or "").strip()
        if not text or len(text) > _MAX_OWNER_ANSWER_CHARS:
            raise MissionError("owner answer must contain 1..4000 characters")
        if (
            question_id.startswith(_OWNER_GATE_QUESTION_PREFIX)
            and text != _OWNER_GATE_APPROVAL
        ):
            raise MissionError("owner gate answer must be exactly APPROVE")
        fingerprint = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:32]
        payload = {"question_id": question_id, "text": text}
        if source_message_id is not None:
            payload["source_message_id"] = _require_source_value(
                source_message_id, "source_message_id"
            )
        if source_platform is not None:
            if source_message_id is None or source_platform not in {"workspace", "telegram"}:
                raise MissionError("invalid owner answer platform")
            payload["source_platform"] = source_platform
        return self.append_central(
            mission_id,
            {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission_id,
                "type": "mission.answer",
                "source": "central-hermes",
                "correlation": {
                    "producer_event_id": f"central:answer:{fingerprint}"
                },
                "payload": payload,
            },
        )

    def append_central(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        normalized = dict(submission)
        normalized["source"] = "central-hermes"
        normalized = _validate_submission(mission_id, normalized)
        if normalized["type"] == "mission.completed":
            raise MissionError("mission completion requires the automatic delivery contract")
        result = self._append(mission_id, normalized)
        if normalized["type"] in TERMINAL_TYPES:
            self.prune_terminal()
        return result

    def append_producer(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return self._append(mission_id, _producer_submission(mission_id, submission))

    def completion_notification(self, mission_id: str) -> dict[str, Any] | None:
        """Return the committed terminal event while a Telegram cursor is behind."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous:
                raise MissionError("mission not found")
            telegram = connection.execute(
                """SELECT last_notified_sequence FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'""",
                (mission_id,),
            ).fetchall()
        terminal = previous[-1]
        if (
            terminal["type"] not in TERMINAL_TYPES
            or not telegram
            or all(
                row["last_notified_sequence"] >= terminal["sequence"]
                for row in telegram
            )
        ):
            return None
        return terminal

    def pending_terminal_notification(
        self, dispatch_profile: str | None = None
    ) -> dict[str, Any] | None:
        """Return one committed terminal event for the existing profile poll to drain."""
        if dispatch_profile is not None:
            dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        with self._db() as connection:
            terminal_rows = connection.execute(
                """SELECT * FROM mission_events
                   WHERE type IN ('mission.completed', 'mission.failed', 'mission.cancelled')
                   ORDER BY rowid"""
            ).fetchall()
            for row in terminal_rows:
                terminal = self._row(row)
                accepted = connection.execute(
                    """SELECT payload_json FROM mission_events
                       WHERE mission_id = ? AND sequence = 1""",
                    (terminal["mission_id"],),
                ).fetchone()
                if accepted is None:
                    continue
                profile = json.loads(accepted["payload_json"]).get("dispatch_profile")
                if dispatch_profile is not None and profile != dispatch_profile:
                    continue
                if connection.execute(
                    """SELECT 1 FROM mission_subscriptions
                       WHERE mission_id = ? AND platform = 'telegram'
                         AND last_notified_sequence < ? LIMIT 1""",
                    (terminal["mission_id"], terminal["sequence"]),
                ).fetchone():
                    return terminal
        return None

    def complete_if_ready(self, mission_id: str) -> tuple[dict[str, Any], bool] | None:
        """Let Central, never the producer, append the terminal delivery event."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous:
                raise MissionError("mission not found")
            view = project(previous)
            sequence = len(previous) + 1
            rejection = _rejection_terminal(view)
            if completion_ready(view):
                event_type = "mission.completed"
                producer_event_id = "central:auto-complete:v1"
                payload = {"result": _completion_result(view)}
            elif rejection is not None:
                event_type = "mission.failed"
                producer_event_id, payload = rejection
            else:
                return None
            event = _validate_submission(
                mission_id,
                {
                    "schema_version": SCHEMA_VERSION,
                    "mission_id": mission_id,
                    "type": event_type,
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": producer_event_id},
                    "payload": payload,
                },
            )
            event.update(
                sequence=sequence,
                event_id=f"{mission_id}:{sequence}",
                occurred_at=_utc_now(),
            )
            connection.execute(
                """INSERT INTO mission_events
                   (mission_id, sequence, event_id, occurred_at, type, source,
                    correlation_json, payload_json, producer_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission_id,
                    sequence,
                    event["event_id"],
                    event["occurred_at"],
                    event["type"],
                    event["source"],
                    _json(event["correlation"]),
                    _json(event["payload"]),
                    event["correlation"]["producer_event_id"],
                ),
            )
            self._prune_terminal(connection, _MAX_RETAINED_TERMINAL_MISSIONS)
        return event, True

    def _append(self, mission_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        mission_id = _require_id(mission_id, "mission_id")
        event = _validate_submission(mission_id, submission)
        producer_id = event["correlation"].get("producer_event_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if event["type"] == "mission.accepted" and connection.execute(
                "SELECT 1 FROM mission_tombstones WHERE mission_id = ?", (mission_id,)
            ).fetchone():
                raise MissionError("mission id was already retired")
            if producer_id:
                duplicate = connection.execute(
                    "SELECT * FROM mission_events WHERE mission_id = ? AND producer_event_id = ?",
                    (mission_id, producer_id),
                ).fetchone()
                if duplicate:
                    stored = self._row(duplicate)
                    if any(stored[key] != event[key] for key in ("type", "source", "correlation", "payload")):
                        raise MissionError("producer event id collision")
                    return stored, False
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence", (mission_id,)
            ).fetchall()
            previous = [self._row(row) for row in rows]
            if not previous and event["type"] != "mission.accepted":
                raise MissionError("mission must start with mission.accepted")
            if previous and event["type"] == "mission.accepted":
                raise MissionError("mission already accepted")
            if previous:
                current = project(previous)
                if current["status"] in {"completed", "failed", "cancelled"}:
                    raise MissionError("mission is terminal")
                if event["type"] == "mission.stage" and event["payload"]["progress_percent"] < current["progress_percent"]:
                    raise MissionError("mission progress decreased")
                if event["type"] == "mission.answer":
                    question = current.get("question")
                    if (
                        current.get("status") != "waiting_owner"
                        or not isinstance(question, dict)
                        or question.get("question_id") != event["payload"]["question_id"]
                    ):
                        raise MissionError("mission answer does not match the open question")
            sequence = len(previous) + 1
            event.update(
                sequence=sequence,
                event_id=f"{mission_id}:{sequence}",
                occurred_at=_utc_now(),
            )
            connection.execute(
                """INSERT INTO mission_events
                   (mission_id, sequence, event_id, occurred_at, type, source,
                    correlation_json, payload_json, producer_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission_id,
                    sequence,
                    event["event_id"],
                    event["occurred_at"],
                    event["type"],
                    event["source"],
                    _json(event["correlation"]),
                    _json(event["payload"]),
                    producer_id,
                ),
            )
        return event, True

    def bind(
        self,
        mission_id: str,
        platform: str,
        chat_id: str,
        thread_id: str | None = None,
        *,
        reason: str = "manual-bind",
    ) -> None:
        mission_id = _require_id(mission_id, "mission_id")
        platform = _require_id(platform, "platform")
        chat_id = str(chat_id or "").strip()
        thread_id = str(thread_id or "").strip()
        if not chat_id or len(chat_id) > 256 or len(thread_id) > 256:
            raise MissionError("invalid mission subscription")
        reason = _require_id(reason, "binding reason")
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            if not rows:
                raise MissionError("mission not found")
            project([self._row(row) for row in rows])
            current = connection.execute(
                """SELECT mission_id, last_notified_sequence, notification_lease_until
                   FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                (platform, chat_id, thread_id),
            ).fetchone()
            if current and current["mission_id"] == mission_id:
                return
            if current and reason == "owner-intake":
                target_order = connection.execute(
                    "SELECT MIN(rowid) FROM mission_events WHERE mission_id = ?",
                    (mission_id,),
                ).fetchone()[0]
                current_order = connection.execute(
                    "SELECT MIN(rowid) FROM mission_events WHERE mission_id = ?",
                    (current["mission_id"],),
                ).fetchone()[0]
                # A delayed transport replay of an older owner turn must not
                # steal the channel binding from a later accepted mission.
                if target_order < current_order:
                    return
            if current:
                current_events = [
                    self._row(row)
                    for row in connection.execute(
                        """SELECT * FROM mission_events
                           WHERE mission_id = ? ORDER BY sequence""",
                        (current["mission_id"],),
                    ).fetchall()
                ]
                current_view = project(current_events)
                if (
                    isinstance(current_view.get("parent_mission_id"), str)
                    and (
                        current_view["status"] not in {"completed", "failed", "cancelled"}
                        or current["last_notified_sequence"] < current_view["sequence"]
                    )
                ):
                    raise MissionError(
                        "repair mission binding is protected until terminal notification"
                    )
            if current and current["notification_lease_until"] > now:
                raise MissionError("mission subscription notification in progress")
            connection.execute(
                """INSERT INTO mission_subscriptions(
                       platform, chat_id, thread_id, mission_id,
                       last_notified_sequence, notification_lease,
                       notification_lease_sequence, notification_lease_until
                   ) VALUES (?, ?, ?, ?, 0, NULL, 0, 0)
                   ON CONFLICT(platform, chat_id, thread_id) DO UPDATE SET
                       mission_id = excluded.mission_id,
                       last_notified_sequence = 0,
                       notification_lease = NULL,
                       notification_lease_sequence = 0,
                       notification_lease_until = 0""",
                (platform, chat_id, thread_id, mission_id),
            )
            self._subscription_history(
                connection,
                {"platform": platform, "chat_id": chat_id, "thread_id": thread_id},
                current["mission_id"] if current else "",
                mission_id,
                reason,
                mission_id,
            )

    def restore_parent_after_terminal_notification(self, mission_id: str) -> None:
        """Restore a repair binding only after its committed terminal update was delivered."""
        mission_id = _require_id(mission_id, "mission_id")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY sequence",
                (mission_id,),
            ).fetchall()
            if not rows:
                raise MissionError("mission not found")
            view = project([self._row(row) for row in rows])
            if view["status"] not in {"completed", "failed", "cancelled"}:
                raise MissionError("repair mission is not terminal")
            parent_mission_id = view.get("parent_mission_id")
            if not isinstance(parent_mission_id, str):
                return
            if connection.execute(
                """SELECT 1 FROM mission_subscriptions
                   WHERE mission_id = ? AND platform = 'telegram'
                     AND last_notified_sequence < ? LIMIT 1""",
                (mission_id, view["sequence"]),
            ).fetchone():
                raise MissionError("repair terminal notification not checkpointed")
            self._restore_parent_subscriptions(
                connection, mission_id, parent_mission_id
            )
            self._prune_terminal(connection, _MAX_RETAINED_TERMINAL_MISSIONS)

    def binding_history(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM mission_subscription_history ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def bound_mission(self, platform: str, chat_id: str, thread_id: str | None = None) -> str | None:
        with self._db() as connection:
            row = connection.execute(
                """SELECT mission_id FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?""",
                (str(platform), str(chat_id), str(thread_id or "")),
            ).fetchone()
        return row["mission_id"] if row else None

    def pending_subscriptions(self, mission_id: str, sequence: int) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                """SELECT * FROM mission_subscriptions
                   WHERE mission_id = ? AND last_notified_sequence < ?""",
                (mission_id, sequence),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_notification(self, subscription: dict[str, Any], sequence: int) -> str | None:
        token = uuid.uuid4().hex
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            updated = connection.execute(
                """UPDATE mission_subscriptions
                   SET notification_lease = ?, notification_lease_sequence = ?,
                       notification_lease_until = ?
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?
                     AND last_notified_sequence < ?
                     AND notification_lease_until <= ?""",
                (
                    token,
                    sequence,
                    now + _NOTIFICATION_LEASE_SECONDS,
                    subscription["platform"],
                    subscription["chat_id"],
                    subscription["thread_id"],
                    subscription["mission_id"],
                    sequence,
                    now,
                ),
            )
        return token if updated.rowcount == 1 else None

    def finish_notification(
        self,
        subscription: dict[str, Any],
        sequence: int,
        token: str,
        *,
        delivered: bool,
    ) -> bool:
        with self._db() as connection:
            if delivered:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET last_notified_sequence = ?,
                           notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ? AND notification_lease = ?
                         AND notification_lease_sequence = ?""",
                    (
                        sequence,
                        subscription["platform"],
                        subscription["chat_id"],
                        subscription["thread_id"],
                        subscription["mission_id"],
                        token,
                        sequence,
                    ),
                )
            else:
                updated = connection.execute(
                    """UPDATE mission_subscriptions
                       SET notification_lease = NULL,
                           notification_lease_sequence = 0,
                           notification_lease_until = 0
                       WHERE platform = ? AND chat_id = ? AND thread_id = ?
                         AND mission_id = ? AND notification_lease = ?
                         AND notification_lease_sequence = ?""",
                    (
                        subscription["platform"],
                        subscription["chat_id"],
                        subscription["thread_id"],
                        subscription["mission_id"],
                        token,
                        sequence,
                    ),
                )
            if updated.rowcount == 1:
                return True
            current = connection.execute(
                """SELECT last_notified_sequence FROM mission_subscriptions
                   WHERE platform = ? AND chat_id = ? AND thread_id = ?
                     AND mission_id = ?""",
                (
                    subscription["platform"],
                    subscription["chat_id"],
                    subscription["thread_id"],
                    subscription["mission_id"],
                ),
            ).fetchone()
        return bool(delivered and current and current["last_notified_sequence"] >= sequence)


async def notify_subscribers(
    store: MissionStore,
    event: dict[str, Any],
    sender: Callable[[dict[str, Any], str], Awaitable[None]],
) -> int:
    """Deliver owner updates at least once; send-before-cursor crashes may duplicate."""
    if event["type"] not in NOTIFY_TYPES:
        return 0
    history = store.events(event["mission_id"])
    view = (
        project([*history, event])
        if event["type"] in TERMINAL_TYPES and event["sequence"] > len(history)
        else project(history)
    )
    text = telegram_text(view)
    sent = 0
    first_error: Exception | None = None
    for subscription in store.pending_subscriptions(event["mission_id"], event["sequence"]):
        token = store.claim_notification(subscription, event["sequence"])
        if token is None:
            continue
        try:
            await sender(subscription, text)
        except Exception as error:
            store.finish_notification(
                subscription, event["sequence"], token, delivered=False
            )
            first_error = first_error or error
        else:
            if store.finish_notification(
                subscription, event["sequence"], token, delivered=True
            ):
                sent += 1
            else:
                first_error = first_error or RuntimeError(
                    "mission subscription changed during notification"
                )
    if first_error is not None:
        raise first_error
    return sent


def producer_key_valid(provided: str | None) -> bool:
    expected = os.environ.get("HERMES_MISSION_PRODUCER_KEY", "").strip()
    return bool(expected and provided and hmac.compare_digest(expected, provided.strip()))


def owner_key_valid(provided: str | None) -> bool:
    expected = os.environ.get("HERMES_MISSION_OWNER_KEY", "").strip()
    return bool(expected and provided and hmac.compare_digest(expected, provided.strip()))


def terminal_request_allowed(remote: str | None) -> bool:
    """Keep terminal mission authority inside the Central Hermes process boundary."""
    try:
        return ipaddress.ip_address(remote or "").is_loopback
    except ValueError:
        return False
