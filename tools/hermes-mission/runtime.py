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
import urllib.parse
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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
    "deploying",
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
        "goal", "project_id", "project_label", "project_repository",
        "dispatch_profile", "delivery_mode", "parent_mission_id",
        "capability", "execution_class", "expected_changed_files", "owner_gate_flag",
        "input_platform", "input_source_key_sha256", "input_source_message_sha256",
    },
    "mission.notice": {
        "code", "message", "owner_action_required", "next_attempt_at",
        "phase", "cycle", "cycle_limit", "url",
    },
    "mission.answer": {
        "question_id", "text", "source_message_id", "source_platform",
    },
    "task.upsert": {"task_id", "title", "status", "assignee"},
    "worker.upsert": {
        "worker_id", "status", "run_id", "profile", "model", "effort",
        "input_tokens", "cached_input_tokens", "output_tokens",
        "reasoning_output_tokens", "model_requests", "max_request_input_tokens",
        "command_calls", "failed_commands", "web_search_calls",
        "attempts_discarded",
    },
    "terminal.append": {"stream", "text", "offset"},
    "delivery.upsert": {
        "kind", "status", "url", "summary", "environment", "artifact_sha256",
        "deployed_revision",
    },
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
_MAX_DELIVERY_SUMMARY_CHARS = 700
_ID_PAYLOAD_FIELDS = {
    "artifact_id", "assignee", "capability", "code", "delivery_mode", "dispatch_profile", "effort", "execution_class", "gate_id", "input_platform", "kind", "model", "owner_gate_flag", "parent_mission_id", "profile", "project_id", "question_id", "source_platform",
    "environment", "phase", "run_id", "status", "stream", "task_id", "worker_id",
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
    r"\b(?:implement|fix|modify|improve|add|remove|refactor|build|deploy|"
    r"deliver|commit|push|"
    r"create|configure|integrate|rename|update|"
    r"open\s+(?:a\s+)?pr|create\s+(?:a\s+)?pr|"
    r"реализ\w*|исправ\w*|измени\w*|улучш\w*|добав\w*|удали\w*|рефактор\w*|"
    r"созда\w*|настро\w*|интегр\w*|переимен\w*|обнов\w*|"
    r"собер\w*|достав\w*|задепло\w*|закоммит\w*|запуш\w*)\b",
    re.IGNORECASE,
)
_EXECUTION_INTENT = re.compile(
    r"\b(?:implement|fix|modify|improve|add|remove|refactor|build|deploy|"
    r"deliver|commit|push|"
    r"create|configure|integrate|rename|update|test|run|start|execute|"
    r"open\s+(?:a\s+)?pr|create\s+(?:a\s+)?pr|"
    r"сдела\w*|реализ\w*|исправ\w*|измени\w*|улучш\w*|добав\w*|удали\w*|рефактор\w*|"
    r"созда\w*|настро\w*|интегр\w*|переимен\w*|обнов\w*|протест\w*|"
    r"запуст\w*|выполн\w*|почин\w*|собер\w*|достав\w*|внес\w*|"
    r"задепло\w*|закоммит\w*|запуш\w*)\b",
    re.IGNORECASE,
)
_DISCUSSION_INTENT = re.compile(
    r"\b(?:can\s+we|could\s+we|is\s+it\s+possible|what\s+(?:are|is)|"
    r"how\s+(?:should|would|can)|think\s+about|assess|analy[sz]e|review|look\s+at)\b|"
    r"(?:можем\s+ли|можно\s+ли|стоит\s+ли|есть\s+ли|как\s+лучше|какие\s+\w*риски|"
    r"подумай\w*|оцен\w*|проанализ\w*|посмотр\w*|обсуд\w*)",
    re.IGNORECASE,
)
_DISCUSS_THEN_EXECUTE = re.compile(
    r"\b(?:and|then|now|please)\s+(?:implement|fix|modify|improve|add|"
    r"remove|create|configure|integrate|deliver|"
    r"rename|update|build|test|run|execute)\b|(?:\bи\b|\bзатем\b)\s+(?:сдела\w*|"
    r"реализ\w*|исправ\w*|измени\w*|улучш\w*|добав\w*|удали\w*|созда\w*|настро\w*|"
    r"интегр\w*|переимен\w*|обнов\w*|протест\w*|запуст\w*|выполн\w*|"
    r"почин\w*|собер\w*|достав\w*|внес\w*)|"
    r"\b(?:теперь|пожалуйста)\s+(?:сдела\w*|реализ\w*|исправ\w*|измени\w*|"
    r"улучш\w*|добав\w*|удали\w*|созда\w*|настро\w*|обнов\w*|почин\w*)",
    re.IGNORECASE,
)
_STATUS_OR_NARRATIVE_INTENT = re.compile(
    r"^(?:i\s+(?:can\s+)?see|we\s+(?:can\s+)?see|"
    r"я\s+вижу|мы\s+видим)\b|"
    r"^(?:i|we|he|she|they)\s+(?:(?:have|has)\s+)?(?:already\s+)?"
    r"(?:implemented|fixed|modified|added|removed|refactored|built|deployed|"
    r"committed|pushed|created|configured|integrated|renamed|updated|tested|"
    r"ran|started|executed)\b|"
    r"^(?:я|мы|он|она|они)\s+(?:уже\s+)?"
    r"(?:сделал(?:а|и)?|реализовал(?:а|и)?|исправил(?:а|и)?|"
    r"изменил(?:а|и)?|добавил(?:а|и)?|удалил(?:а|и)?|"
    r"обновил(?:а|и)?|настроил(?:а|и)?|запустил(?:а|и)?|"
    r"выполнил(?:а|и)?|починил(?:а|и)?|собрал(?:а|и)?)\b|"
    r"^(?:why|почему|зачем|когда|где)\b",
    re.IGNORECASE,
)
_READ_ONLY_EXECUTION_INTENT = re.compile(
    r"\b(?:read[- ]only|run|test|check|inspect|diagnose|start|execute|status|logs?|"
    r"show\s+(?:the\s+)?status|view\s+(?:the\s+)?logs?)\b|"
    r"(?:запуст\w*|протест\w*|проверь\w*|диагностир\w*|"
    r"тест\w*|статус\w*|диагностик\w*|лог\w*|"
    r"покаж\w*\s+статус|посмотр\w*\s+лог\w*)",
    re.IGNORECASE,
)
_REQUIRED_EXTERNAL_SOURCE = re.compile(
    r"(?:\bread\b|\buse\b|\bfollow\b|\bopen\b|\bbased\s+on\b|\baccording\s+to\b|"
    r"\bhandoff\b|прочит\w*|использ\w*|следу\w*|открой\w*|"
    r"на\s+основе).{0,160}https?://[^\s<>()]+|"
    r"(?:\bimplement\b|\bbuild\b|реализ\w*|сдела\w*)"
    r".{0,160}https?://[^\s<>()]+|"
    r"(?:\bcreate\b|созда\w*).{0,120}"
    r"(?:\bfrom\b|\bper\b|\bиз\b|\bпо\b).{0,80}https?://[^\s<>()]+|"
    r"https?://[^\s<>()]+.{0,160}(?:\bas\s+(?:the\s+)?source\b|"
    r"\bhandoff\b|как\s+источник\w*)",
    re.IGNORECASE,
)
_TASK_RISK_PATTERNS = (
    (
        "architecture_change",
        re.compile(
            r"(?:\b(?:implement|fix|modify|improve|add|remove|refactor|build|"
            r"deploy|create|configure|integrate|rename|update|enable|change|"
            r"replace|redesign|supersede|rework|move|transfer)\b|"
            r"(?:реализ|исправ|измен|улучш|добав|удал|рефактор|созда|настро|"
            r"интегр|переимен|обнов|разверн|замен|перепроект|перестро|отмен|"
            r"перенес|переда)\w*)"
            r".{0,100}(?:\b(?:accepted\s+)?architecture\b|"
            r"\b(?:architectural|security|authority)\s+boundary\b|"
            r"\bauthoritative\s+\w*\s*state\b|\bsource\s+of\s+truth\b|"
            r"\btopology\b|\bADR-\d+\b|архитектур\w*|источник\w*\s+истин\w*|"
            r"авторитетн\w+\s+состояни\w*|"
            r"границ\w+\s+(?:безопасност|полномоч)\w*|тополог\w*)",
            re.IGNORECASE,
        ),
    ),
    (
        "destructive",
        re.compile(
            r"(?:\b(?:drop|wipe|destroy|erase|purge|reset|delete|remove)\b|"
            r"(?:удал|уничтож|сотр|сброс|очист)\w*)"
            r".{0,60}(?:\b(?:production|prod|database|db|user\s+data|"
            r"persistent\s+data|volume|disk|cluster(?!-admin)|repository|repo|vm)\b|"
            r"прод\w*|баз\w+\s+данн\w*|данн\w+\s+пользовател\w*|"
            r"том\w*|диск\w*|кластер\w*|репозитор\w*|виртуальн\w+\s+машин\w*)",
            re.IGNORECASE,
        ),
    ),
    (
        "credentials_or_external_authority",
        re.compile(
            r"(?:\b(?:add|implement|build|enable|create|issue|rotate|replace|"
            r"grant|provision|configure)\b|"
            r"(?:добав|реализ|собер|включ|созда|выпуст|ротир|замен|выда|"
            r"предостав|настро)\w*)"
            r".{0,60}(?:\b(?:credential|secret|token|api\s+key|ssh\s+key|"
            r"write\s+access|admin\s+access|cluster-admin|rbac|external\s+account|permission)\w*\b|"
            r"уч[её]тн\w+\s+данн\w*|секрет\w*|токен\w*|ключ\w+\s+api|"
            r"ключ\w+\s+ssh|прав\w*.{0,20}(?:запис\w*|cluster-admin|admin|rbac)|"
            r"доступ\w*|полномоч\w*)",
            re.IGNORECASE,
        ),
    ),
    (
        "new_provider",
        re.compile(
            r"\b(?:claude|anthropic|openrouter|gemini|qwen)\b.{0,50}"
            r"\b(?:become|replace)\b.{0,30}\b(?:the\s+)?(?:new\s+)?(?:model\s+)?provider\b|"
            r"\b(?:add|configure|build|implement|create)\b.{0,60}"
            r"\b(?:claude|anthropic|openrouter|gemini|qwen)\b"
            r".{0,30}\b(?:as\s+)?(?:the\s+)?(?:new\s+)?(?:model\s+)?provider\b|"
            r"\badd\s+(?:support\s+for\s+)?(?:claude|anthropic|openrouter|"
            r"gemini|qwen)\b.{0,30}\b(?:model\s+)?provider\b|"
            r"(?:добав\w+).{0,30}(?:claude|anthropic|openrouter|gemini|qwen)"
            r".{0,30}(?:model\s+provider|модел\w+\s+провайдер\w*|провайдер\w*)|"
            r"(?:\b(?:add\s+support\s+for|integrate|enable|"
            r"switch.{0,40}\bto|migrate\s+to|route\s+to|use)\b|"
            r"(?:добав\w+\s+поддержк\w+|интегр|включ|переключ|мигрир|"
            r"маршрутизир|использ)\w*)"
            r".{0,60}(?:\b(?:new\s+(?:model\s+)?provider|claude|anthropic|"
            r"openrouter|gemini|qwen|non-openai\s+provider)\b|"
            r"нов\w+\s+(?:модел\w+\s+)?провайдер\w*)",
            re.IGNORECASE,
        ),
    ),
    (
        "local_or_gpu",
        re.compile(
            r"(?:\b(?:add|integrate|implement|build|create|enable|run|use|"
            r"deploy|configure|start)\b|"
            r"(?:добав|интегр|реализ|собер|созда|включ|запуст|запуска|"
            r"использ|разверн|задепло|настро)\w*)"
            r".{0,60}(?:\b(?:local\s+(?:inference|model)|ollama|lm\s+studio|"
            r"gpu|cuda|rocm|rtx)\b|локальн\w+\s+(?:инференс|модел)\w*|"
            r"видеокарт\w*)",
            re.IGNORECASE,
        ),
    ),
)
_TASK_RISK_EXCLUSIONS = {
    "architecture_change": re.compile(
        r"\b(?:add|update)\s+(?:a\s+)?(?:link|reference)\s+to\s+ADR-\d+\b|"
        r"(?:добав|обнов)\w*\s+ссылк\w+\s+на\s+ADR-\d+\b|"
        r"\b(?:fix|update)\s+(?:(?:a|the)\s+)?"
        r"(?:typo\s+in\s+)?docs?/architecture\.md\b|"
        r"(?:исправ|обнов)\w*\s+(?:опечатк\w+\s+в\s+)?"
        r"docs?/architecture\.md\b",
        re.IGNORECASE,
    ),
    "destructive": re.compile(
        r"\b(?:delete|remove)\s+(?:the\s+)?(?:production|prod)\s+"
        r"(?:database|db)\s+(?:instructions?|documentation)\b"
        r"\s+(?:from|in)\s+(?:the\s+)?(?:readme|docs?)\b|"
        r"(?:удал|убер)\w*\s+(?:инструкц\w*|документац\w*)"
        r"(?:\s+по)?\s+(?:production\s+(?:database|db)|"
        r"prod\s+(?:database|db)|баз\w+\s+данн\w*)"
        r"\s+(?:из|в)\s+(?:readme|docs?|документ\w*)|"
        r"(?:удал|убер)\w*\s+(?:production\s+(?:database|db)|"
        r"prod\s+(?:database|db)|баз\w+\s+данн\w*)"
        r"\s+(?:инструкц\w*|документац\w*)"
        r"\s+(?:из|в)\s+(?:readme|docs?|документ\w*)",
        re.IGNORECASE,
    ),
    "credentials_or_external_authority": re.compile(
        r"\b(?:fake|mock)\s+(?:secret|token|credential)\s+"
        r"(?:fixture|mock|test)\b|"
        r"(?:fake|mock|фиктивн\w*)\s+"
        r"(?:секрет\w*|токен\w*|credential)\s+"
        r"(?:fixture|mock|test|тест\w*)|"
        r"\b(?:credential|secret|token)\s+(?:redaction|parser|validator)\b|"
        r"\brbac\s+(?:validator|test|mock)\b",
        re.IGNORECASE,
    ),
    "new_provider": re.compile(
        r"\b(?:claude|anthropic|openrouter|gemini|qwen)\s+"
        r"(?:provider\s+)?(?:mock|fixture|test)\b",
        re.IGNORECASE,
    ),
    "local_or_gpu": re.compile(
        r"\b(?:mocked?|fake)\s+(?:gpu|cuda|rocm|rtx)\s+"
        r"(?:path|test|fixture|mock)\b",
        re.IGNORECASE,
    ),
}
_ROUTINE_DOCS_ONLY = re.compile(
    r"\b(?:only\s+(?:the\s+)?(?:readme(?:\.md)?|docs?|documentation)|"
    r"(?:readme(?:\.md)?|docs?|documentation)\s+only)\b|"
    r"\bтолько\s+(?:файл\s+)?(?:readme(?:\.md)?|docs|документац\w*|документ\w*)\b",
    re.IGNORECASE,
)
_ROUTINE_NON_DOCS_SCOPE = re.compile(
    r"\b(?:code|source|implementation|config(?:uration)?|ya?ml|json|toml|"
    r"workflow|manifest|tests?|код\w*|исходн\w*|реализац\w*|конфиг\w*|"
    r"настройк\w*|манифест\w*|тест\w*)\b",
    re.IGNORECASE,
)
_ROUTINE_PLAN_ONLY = re.compile(
    r"\b(?:create|write|add)\s+(?:an?\s+)?(?:implementation\s+)?plan\b|"
    r"\b(?:созда\w*|напиш\w*|добав\w*)\s+(?:себе\s+)?"
    r"(?:plan|план\w*)(?:\s+(?:implementation|реализац\w*))?\b",
    re.IGNORECASE,
)
_PLAN_AND_IMPLEMENT = re.compile(
    r"(?:plan|план\w*).{0,80}\b(?:and|then|и|затем)\s+"
    r"(?:implement|modify|change|code|реализ\w*|измен\w*|добав\w*)\b",
    re.IGNORECASE,
)
_COMPLETION_GATES = {"tests", "review", "ci", "post-verify", "cleanup"}
_COMPLETION_DELIVERIES = {
    "pull_request": "merged",
    "default_branch": "verified",
}
_GATE_LABELS = {
    "tests": "тесты",
    "review": "независимое ревью",
    "ci": "CI",
    "post-verify": "проверка после слияния",
    "deployment": "деплой",
    "cleanup": "очистка",
    "execution": "выполнение",
}
_ALLOWED_WORKER_MODELS = {"gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"}
_ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_ROLE_LABELS = {"author": "Автор", "reviewer": "Ревьюер"}
_API_PRICE_DATE = "22.07.2026"
_API_PRICES = {
    # input, cached input, cache write, output; USD per million tokens
    "gpt-5.6-sol": tuple(map(Decimal, ("5", "0.5", "6.25", "30"))),
    "gpt-5.6-terra": tuple(map(Decimal, ("2.5", "0.25", "3.125", "15"))),
    "gpt-5.6-luna": tuple(map(Decimal, ("1", "0.1", "1.25", "6"))),
}
_WEB_SEARCH_USD = Decimal("0.01")
_LONG_CONTEXT_TOKENS = 272_000
_STAGE_LABELS = {
    "accepted": "Цель принята",
    "planning": "Планирование",
    "implementing": "Внесение изменений",
    "testing": "Автоматические проверки",
    "reviewing": "Независимая проверка",
    "delivering": "PR, CI и слияние",
    "verifying": "Проверка после слияния",
    "deploying": "Развёртывание",
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
    normalized = " ".join(text.split())
    return (
        bool(_RESEARCH_INTENT.search(normalized))
        and not _MUTATION_INTENT.search(normalized)
        and not task_owner_gate_flags(normalized)
    )


def is_read_only_execution_goal(text: object) -> bool:
    """Keep non-mutating operational work out of the code-delivery state machine."""
    if not isinstance(text, str):
        return False
    normalized = " ".join(text.split())
    payload = re.sub(r"^/(?:run|mission)\b\s*", "", normalized, flags=re.IGNORECASE)
    return (
        bool(_READ_ONLY_EXECUTION_INTENT.search(payload))
        and not _MUTATION_INTENT.search(payload)
        and not task_owner_gate_flags(payload)
    )


def requires_external_source(text: object) -> bool:
    """Fail closed until external source material has an immutable transport."""
    if not isinstance(text, str):
        return False
    return bool(_REQUIRED_EXTERNAL_SOURCE.search(" ".join(text.split())))


def is_execution_goal(text: object) -> bool:
    """Conservatively distinguish an explicit action from discussion."""
    if not isinstance(text, str):
        return False
    normalized = " ".join(text.split())
    if not normalized:
        return False
    lowered = normalized.casefold()
    task_flags = task_owner_gate_flags(normalized)
    if lowered.startswith(("/discuss", "обсудим:", "давай обсудим")):
        return False
    if is_read_only_execution_goal(normalized):
        return False
    if lowered.startswith(("/run", "/mission")):
        return True
    if (
        _STATUS_OR_NARRATIVE_INTENT.search(normalized)
        and not _DISCUSS_THEN_EXECUTE.search(normalized)
        and not task_flags
    ):
        return False
    discussed_then_execute = _DISCUSS_THEN_EXECUTE.search(normalized)
    if normalized.endswith("?") and not discussed_then_execute:
        return False
    if (
        (_RESEARCH_INTENT.search(normalized) or _DISCUSSION_INTENT.search(normalized))
        and not discussed_then_execute
        and not task_flags
    ):
        return False
    return bool(
        _EXECUTION_INTENT.search(normalized)
        or task_flags
    )


def routine_docs_file_limit(text: object) -> int | None:
    """Return the closed small-change cap only for an explicit docs-only goal."""
    if not isinstance(text, str):
        return None
    normalized = " ".join(text.split())
    if not is_execution_goal(normalized):
        return None
    if (
        _ROUTINE_DOCS_ONLY.search(normalized)
        and not _ROUTINE_NON_DOCS_SCOPE.search(normalized)
    ):
        return 2
    if _ROUTINE_PLAN_ONLY.search(normalized) and not _PLAN_AND_IMPLEMENT.search(normalized):
        return 1
    return None


def task_owner_gate_flags(text: object) -> tuple[str, ...]:
    """Return only explicit protected actions; plain mentions remain ordinary work."""
    if not isinstance(text, str):
        return ()
    normalized = " ".join(text.split())
    if not normalized:
        return ()
    flags = []
    for flag, pattern in _TASK_RISK_PATTERNS:
        candidate = normalized
        if exclusion := _TASK_RISK_EXCLUSIONS.get(flag):
            if flag in {"architecture_change", "destructive"}:
                candidate = exclusion.sub(
                    lambda match: match.group(0).split(maxsplit=1)[0],
                    candidate,
                )
            else:
                candidate = exclusion.sub("", candidate)
        if pattern.search(candidate):
            flags.append(flag)
    return tuple(sorted(flags))


def task_owner_gate_flag(text: object) -> str | None:
    """Allow the existing architecture gate; other capabilities need separate setup."""
    flags = task_owner_gate_flags(text)
    unsupported = tuple(flag for flag in flags if flag != "architecture_change")
    if unsupported:
        raise MissionError(
            "task requires separate capability setup: " + ", ".join(unsupported)
        )
    return "architecture_change" if flags else None


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
            delivery_mode = item.get("delivery_mode")
            if delivery_mode not in {"none", "deploy"}:
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
                    "delivery_mode": delivery_mode,
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
        if mode not in {"none", "deploy"}:
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


def project_setup_target(platform: str, project_id: object) -> dict[str, Any]:
    """Resolve one catalog-owned project that is eligible for setup discussion."""
    project_id = _require_id(project_id, "setup_project_id")
    matches = [
        project
        for project in registered_intake_projects(platform)
        if project["project_id"] == project_id
    ]
    if len(matches) != 1:
        raise MissionError("project is not registered")
    target = matches[0]
    if target["status"] != "setup_required":
        raise MissionError("project does not require setup")
    return target


_SETUP_PROJECT_MARKER = "UAP_SETUP_PROJECT_ID: "


def project_setup_system_prompt(target: dict[str, Any]) -> str:
    """Build server-owned read-only context for an existing-project setup chat."""
    tests = ", ".join(target.get("test_targets", [])) or "не определены"
    return (
        "SERVER-OWNED PROJECT SETUP CONTEXT\n"
        f"{_SETUP_PROJECT_MARKER}{target['project_id']}\n"
        f"Проект: {target['label']}\n"
        f"Репозиторий: {target['repository']}\n"
        f"Описание: {target['summary']}\n"
        f"Предварительные площадки проверок: {tests}\n"
        "Статус: setup_required. Это этап обсуждения: изучай репозиторий только "
        "на чтение, объясняй архитектуру, проверки, риски и предлагаемый профиль. "
        "Не утверждай, что проект настроен, и не меняй его статус. Явная команда "
        "владельца на настройку перехватывается сервером и создаёт отдельную "
        "проверяемую UAP mission."
    )


def project_setup_target_from_system_prompt(
    platform: str, system_prompt: object
) -> dict[str, Any] | None:
    """Recover a server-owned setup binding persisted with the session."""
    if not isinstance(system_prompt, str):
        return None
    for line in system_prompt.splitlines():
        if line.startswith(_SETUP_PROJECT_MARKER):
            return project_setup_target(
                platform, line.removeprefix(_SETUP_PROJECT_MARKER).strip()
            )
    return None


def project_setup_execution_goal(target: dict[str, Any], owner_text: str) -> str:
    """Turn explicit setup approval into a reviewable UAP configuration mission."""
    owner_text = " ".join(str(owner_text).split())
    return (
        f"Настрой существующий проект {target['label']} "
        f"({target['repository']}, project_id={target['project_id']}) для автономной "
        "работы через Central Hermes. Сначала выполни read-only аудит репозитория и "
        "его CI. Затем добавь минимальный server-owned schema-v4 delivery profile, "
        "точные проверки и необходимые catalog/runtime изменения через обычный UAP "
        "PR, независимое review и CI. Сохраняй status=setup_required, пока профиль, "
        "runner/timer и реальный canary не проверены; только после этого переведи "
        "проект в ready. Не создавай новые credentials и не расширяй execution "
        f"boundary без отдельного согласия владельца. Команда владельца: {owner_text}"
    )[:_MAX_OWNER_GOAL_CHARS]


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
        if name == "expected_changed_files":
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= 2
            ):
                raise MissionError("invalid payload.expected_changed_files")
            continue
        if name in {
            "input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_output_tokens", "model_requests", "max_request_input_tokens",
            "command_calls", "failed_commands", "web_search_calls",
            "attempts_discarded", "cycle", "cycle_limit",
        }:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MissionError(f"invalid payload.{name}")
            continue
        if not isinstance(value, str) or not value.strip():
            raise MissionError(f"invalid payload.{name}")
        if name in _ID_PAYLOAD_FIELDS:
            _require_id(value, f"payload.{name}")
    if event_type == "worker.upsert" and "model" in payload:
        if payload["model"] not in _ALLOWED_WORKER_MODELS:
            raise MissionError("worker model is not in the closed delivery set")
    if event_type == "worker.upsert" and "effort" in payload:
        if payload["effort"] not in _ALLOWED_EFFORTS:
            raise MissionError("worker effort is not in the closed Codex effort enum")
    if event_type == "worker.upsert":
        if payload.get("cached_input_tokens", 0) > payload.get("input_tokens", 0):
            raise MissionError("worker cached input exceeds total input")
        if payload.get("reasoning_output_tokens", 0) > payload.get("output_tokens", 0):
            raise MissionError("worker reasoning output exceeds total output")
        if payload.get("failed_commands", 0) > payload.get("command_calls", 0):
            raise MissionError("worker failed commands exceed command calls")
    if event_type == "mission.stage":
        if payload.get("stage") not in STAGES:
            raise MissionError("invalid mission stage")
        progress = payload.get("progress_percent")
        if not isinstance(progress, int) or isinstance(progress, bool) or not 0 <= progress <= 100:
            raise MissionError("invalid mission progress")
    if event_type == "mission.notice":
        if payload.get("code") not in {
            "capacity_wait", "capacity_recovered", "execution_reconciling",
            "disk_space_wait", "disk_space_recovered", "progress_detail",
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
        url = payload.get("url")
        if url is not None:
            parsed_url = urllib.parse.urlsplit(url)
            if (
                len(url) > 2_048
                or parsed_url.scheme not in {"http", "https"}
                or not parsed_url.netloc
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise MissionError("invalid mission notice URL")
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
        if payload.get("delivery_mode") not in {"none", "deploy"}:
            raise MissionError("invalid mission delivery mode")
    if event_type == "mission.accepted" and "owner_gate_flag" in payload:
        if payload.get("owner_gate_flag") != "architecture_change":
            raise MissionError("invalid mission owner gate flag")
    if event_type == "mission.accepted":
        execution_class = payload.get("execution_class")
        expected_changed_files = payload.get("expected_changed_files")
        if (execution_class, expected_changed_files) != (None, None) and (
            execution_class != "routine_docs"
            or not isinstance(expected_changed_files, int)
            or isinstance(expected_changed_files, bool)
            or not 1 <= expected_changed_files <= 2
        ):
            raise MissionError("invalid mission execution class")
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
    if event_type == "mission.accepted" and "project_repository" in payload:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", payload.get("project_repository", "")):
            raise MissionError("invalid project repository")
    if event_type == "mission.accepted" and "project_label" in payload:
        _require_source_value(payload.get("project_label"), "project_label")
    if event_type == "delivery.upsert":
        not_applicable = (
            payload.get("kind") == "delivery"
            and payload.get("status") == "not_applicable"
        )
        summary = payload.get("summary")
        if not_applicable:
            if "url" in payload:
                raise MissionError("not-applicable delivery must not have a URL")
        elif "url" not in payload:
            raise MissionError("delivery URL is required")
        if summary is not None and (
            payload.get("kind") != "pull_request"
            or not isinstance(summary, str)
            or summary != " ".join(summary.split())
            or not summary
            or len(summary) > _MAX_DELIVERY_SUMMARY_CHARS
        ):
            raise MissionError("invalid delivery summary")
        deployment_fields = {"environment", "artifact_sha256", "deployed_revision"}
        if payload.get("kind") == "deployment":
            if (
                payload.get("status") not in {"verified", "failed"}
                or not isinstance(payload.get("environment"), str)
                or not _ID.fullmatch(payload["environment"])
                or not isinstance(payload.get("deployed_revision"), str)
                or not re.fullmatch(r"[0-9a-f]{40,64}", payload["deployed_revision"])
                or (
                    payload.get("status") == "verified"
                    and not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("artifact_sha256") or ""))
                )
                or (
                    payload.get("status") == "failed"
                    and "artifact_sha256" in payload
                )
            ):
                raise MissionError("invalid deployment delivery")
        elif deployment_fields & payload.keys():
            raise MissionError("deployment identity belongs only to deployment delivery")
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
        "project_label": None,
        "project_repository": None,
        "dispatch_profile": None,
        "capability": None,
        "delivery_mode": None,
        "execution_class": None,
        "expected_changed_files": None,
        "owner_gate_flag": None,
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
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
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
        if event.get("occurred_at"):
            if view["started_at"] is None:
                view["started_at"] = event["occurred_at"]
            view["updated_at"] = event["occurred_at"]
        kind, payload = event["type"], event["payload"]
        if kind == "mission.accepted":
            projected_owner_gate_flag = payload.get("owner_gate_flag")
            if projected_owner_gate_flag is None:
                legacy_flags = task_owner_gate_flags(payload["goal"])
                unsupported = tuple(
                    flag
                    for flag in legacy_flags
                    if flag != "architecture_change"
                )
                if unsupported:
                    raise MissionError(
                        "legacy mission requires separate capability setup: "
                        + ", ".join(unsupported)
                    )
                if legacy_flags:
                    projected_owner_gate_flag = "architecture_change"
            view.update(
                status="active",
                stage="accepted",
                goal=payload["goal"],
                project_id=payload.get("project_id"),
                project_label=payload.get("project_label"),
                project_repository=payload.get("project_repository"),
                dispatch_profile=payload.get("dispatch_profile"),
                capability=payload.get("capability"),
                delivery_mode=payload.get("delivery_mode"),
                execution_class=payload.get("execution_class"),
                expected_changed_files=payload.get("expected_changed_files"),
                owner_gate_flag=projected_owner_gate_flag,
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
            legacy_answer_flags = task_owner_gate_flags(payload["text"])
            if legacy_answer_flags:
                raise MissionError(
                    "legacy owner answer adds task capabilities: "
                    + ", ".join(legacy_answer_flags)
                )
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
                finished_at=event.get("occurred_at"),
            )
        elif kind == "mission.failed":
            view.update(status="failed", error=payload["error"], notice=None,
                        finished_at=event.get("occurred_at"))
        elif kind == "mission.cancelled":
            view.update(status="cancelled", error=payload["reason"], notice=None,
                        finished_at=event.get("occurred_at"))

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


def _short_mission_id(mission_id: str | None) -> str:
    """Return a short technical identifier for support references."""
    text = str(mission_id or "")
    if not text:
        return "неизвестен"
    return text[-8:] if len(text) > 12 else text


def _headline(view: dict[str, Any]) -> str:
    """Build the owner-readable headline from server-owned project metadata."""
    label = view.get("project_label")
    repository = view.get("project_repository")
    if label and repository:
        return f"{label} ({repository})"
    if label:
        return str(label)
    if repository:
        return str(repository)
    goal = view.get("goal")
    if isinstance(goal, str) and goal.strip():
        text = " ".join(goal.split())
        return text[:80] + ("…" if len(text) > 80 else "")
    return f"Задача {_short_mission_id(view.get('mission_id'))}"


def _project_tag(view: dict[str, Any]) -> str | None:
    """Return a searchable Telegram hashtag from trusted catalog identity."""
    project_id = view.get("project_id")
    if not isinstance(project_id, str):
        return None
    tag = re.sub(r"[^A-Za-z0-9_]", "_", project_id).strip("_")
    return f"#{tag}" if tag else None


def _workspace_mission_url(view: dict[str, Any]) -> str | None:
    """Build one optional owner-facing deep link without trusting mission text."""
    base = os.environ.get("HERMES_MISSION_WORKSPACE_URL", "").strip().rstrip("/")
    mission_id = view.get("mission_id")
    if not base or not isinstance(mission_id, str) or not mission_id:
        return None
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{base}/dashboard?mission={urllib.parse.quote(mission_id, safe='')}"


def telegram_text(view: dict[str, Any]) -> str:
    """Render the compact Telegram view from the exact Workspace projection."""
    status = view.get("status") or "unknown"
    stage = view.get("stage") or "unknown"
    headline = _headline(view)
    project_tag = _project_tag(view)
    lines = [
        f"{project_tag} · {headline}" if project_tag else headline,
        f"ID: {_short_mission_id(view.get('mission_id'))}",
        f"Этап: {_STAGE_LABELS.get(stage, stage)} · {view.get('progress_percent', 0)}%",
        f"Статус: {_STATUS_LABELS.get(status, status)}",
    ]
    workspace_url = _workspace_mission_url(view)
    if workspace_url:
        lines.append(f"Подробнее: {workspace_url}")
    goal = view.get("goal")
    if isinstance(goal, str) and goal.strip():
        short_goal = " ".join(goal.split())
        if len(short_goal) > 120:
            short_goal = short_goal[:119].rstrip() + "…"
        lines.append(f"Цель: {short_goal}")
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
        cycle = notice.get("cycle")
        cycle_limit = notice.get("cycle_limit")
        if (
            isinstance(cycle, int) and not isinstance(cycle, bool)
            and isinstance(cycle_limit, int) and not isinstance(cycle_limit, bool)
        ):
            lines.append(f"Цикл: {cycle} из {cycle_limit}")
        notice_url = notice.get("url")
        if isinstance(notice_url, str) and notice_url != workspace_url:
            lines.append(f"Текущий результат: {notice_url}")
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
    if status in ("active", "waiting_owner", "failed", "cancelled"):
        workers = view.get("workers", [])
        final = status in ("failed", "cancelled")
        lines.extend(_role_telemetry_lines(workers, final=final))
        lines.extend(_usage_statistics_lines(workers, final=final))
    lines.append(
        "Задачи {tasks} · Исполнители {workers} · Проверки {gates} · Результаты {deliveries}".format(
            tasks=len(view.get("tasks", [])),
            workers=sum(1 for w in view.get("workers", []) if isinstance(w, dict) and not _is_telemetry_worker(w)),
            gates=len(view.get("gates", [])),
            deliveries=len(view.get("deliveries", [])),
        )
    )
    return "\n".join(lines)


def _is_telemetry_worker(worker: dict[str, Any]) -> bool:
    """True for informational author/reviewer telemetry records."""
    return isinstance(worker.get("profile"), str) and worker["profile"] in _ROLE_LABELS


def _one_terminal_worker(
    workers: Any, terminal_statuses: set[str]
) -> bool:
    if (
        not isinstance(workers, list)
        or not workers
        or not all(isinstance(worker, dict) for worker in workers)
    ):
        return False
    canonical = [w for w in workers if not _is_telemetry_worker(w)]
    if not canonical:
        return False
    statuses = [worker.get("status") for worker in canonical]
    return (
        statuses[-1] in terminal_statuses
        and all(status == "scheduled" for status in statuses[:-1])
    )


def _format_elapsed(started_at: str | None, finished_at: str | None) -> str | None:
    """Compute human-readable elapsed time from authoritative event timestamps."""
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    delta = end - start
    if delta.total_seconds() < 0:
        return None
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м"
    if minutes > 0:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"


def _role_telemetry_lines(
    workers: list[dict[str, Any]], *, final: bool = True
) -> list[str]:
    """Render role-bound telemetry from final accepted author/reviewer runs."""
    lines: list[str] = []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        profile = worker.get("profile")
        if not isinstance(profile, str) or profile not in _ROLE_LABELS:
            continue
        model = worker.get("model")
        if not isinstance(model, str) or not model.strip():
            continue
        role = _ROLE_LABELS[profile]
        run_label = "финальный прогон" if final else "последний завершённый прогон"
        parts = [f"{role} ({run_label}): {model.strip()}"]
        effort = worker.get("effort")
        if isinstance(effort, str) and effort.strip():
            parts.append(f"effort {effort.strip()}")
        in_tok = worker.get("input_tokens")
        out_tok = worker.get("output_tokens")
        if (
            isinstance(in_tok, int) and not isinstance(in_tok, bool) and in_tok >= 0
            and isinstance(out_tok, int) and not isinstance(out_tok, bool) and out_tok >= 0
        ):
            parts.append(f"{in_tok} in / {out_tok} out")
        lines.append(" · ".join(parts))
    return lines


def _metric(worker: dict[str, Any], name: str) -> int | None:
    value = worker.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _format_token_count(value: int) -> str:
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{text.replace('.', ',')} млн"
    if value >= 1_000:
        text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{text.replace('.', ',')} тыс."
    return str(value)


def _api_cost_range(workers: list[dict[str, Any]]) -> tuple[Decimal, Decimal] | None:
    low = Decimal(0)
    high = Decimal(0)
    million = Decimal(1_000_000)
    for worker in workers:
        prices = _API_PRICES.get(worker.get("model"))
        input_tokens = _metric(worker, "input_tokens")
        cached_tokens = _metric(worker, "cached_input_tokens")
        output_tokens = _metric(worker, "output_tokens")
        max_input = _metric(worker, "max_request_input_tokens")
        if (
            prices is None or input_tokens is None or cached_tokens is None
            or output_tokens is None or max_input is None or max_input <= 0
            or max_input > _LONG_CONTEXT_TOKENS or cached_tokens > input_tokens
        ):
            return None
        input_price, cached_price, cache_write_price, output_price = prices
        fresh_tokens = Decimal(input_tokens - cached_tokens)
        cached_tokens_decimal = Decimal(cached_tokens)
        output_tokens_decimal = Decimal(output_tokens)
        searches = Decimal(_metric(worker, "web_search_calls") or 0)
        fixed = (
            cached_tokens_decimal * cached_price
            + output_tokens_decimal * output_price
        ) / million + searches * _WEB_SEARCH_USD
        low += fixed + fresh_tokens * input_price / million
        high += fixed + fresh_tokens * cache_write_price / million
    return low, high


def _usage_statistics_lines(
    workers: list[dict[str, Any]], *, final: bool = True
) -> list[str]:
    cumulative = [
        worker for worker in workers
        if isinstance(worker, dict) and worker.get("profile") == "usage"
    ]
    role_telemetry = [
        worker for worker in workers
        if isinstance(worker, dict) and worker.get("profile") in _ROLE_LABELS
    ]
    telemetry = cumulative or role_telemetry
    measured = [
        worker for worker in telemetry
        if _metric(worker, "input_tokens") is not None
        and _metric(worker, "output_tokens") is not None
    ]
    if not measured or len(measured) != len(telemetry):
        return []

    total_input = sum(_metric(worker, "input_tokens") or 0 for worker in measured)
    total_output = sum(_metric(worker, "output_tokens") or 0 for worker in measured)
    parts = [f"вход {_format_token_count(total_input)}"]
    if all(_metric(worker, "cached_input_tokens") is not None for worker in measured):
        cached = sum(_metric(worker, "cached_input_tokens") or 0 for worker in measured)
        if cached <= total_input:
            percent = (
                Decimal(cached) * 100 / Decimal(total_input)
                if total_input
                else Decimal(0)
            ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            parts.extend((
                f"runtime-кэш {_format_token_count(cached)} ({str(percent).replace('.', ',')}%)",
                f"новый вход {_format_token_count(total_input - cached)}",
            ))
    parts.append(f"выход {_format_token_count(total_output)}")
    requests = [_metric(worker, "model_requests") for worker in measured]
    if all(value is not None for value in requests):
        parts.append(f"запросы к моделям {sum(value or 0 for value in requests)}")
    if cumulative:
        label = "Накопительный подтверждённый расход"
    else:
        label = (
            "Статистика финальных прогонов"
            if final
            else "Последние подтверждённые прогоны"
        )
    lines = [f"{label}: " + " · ".join(parts)]
    discarded = sum(
        _metric(worker, "attempts_discarded") or 0 for worker in measured
    )
    if discarded:
        lines.append(
            f"Важно: как минимум {discarded} предыдущих или отброшенных "
            "прогонов не входят в эту сумму."
        )

    command_calls = sum(_metric(worker, "command_calls") or 0 for worker in measured)
    failed_commands = sum(_metric(worker, "failed_commands") or 0 for worker in measured)
    searches = sum(_metric(worker, "web_search_calls") or 0 for worker in measured)
    if command_calls or failed_commands or searches:
        lines.append(
            f"Инструменты: shell {command_calls} · ненулевой код {failed_commands} · web search {searches}"
        )

    estimate = _api_cost_range(measured)
    if estimate is not None:
        low, high = (
            value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for value in estimate
        )
        low_text = str(low).replace(".", ",")
        high_text = str(high).replace(".", ",")
        amount = f"${low_text}" if low == high else f"${low_text}–${high_text}"
        lines.append(f"API-эквивалент: {amount} · прайс OpenAI {_API_PRICE_DATE}")
    return lines


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
    owner_result = deliveries.get("pull_request", {}).get("summary")
    lines = [
        compact(owner_result, _MAX_DELIVERY_SUMMARY_CHARS)
        if isinstance(owner_result, str) and owner_result.strip()
        else "Изменения внесены, проверены и слиты; подробное описание результата недоступно."
    ]
    for label, kind in (("PR", "pull_request"), ("Merge-коммит", "default_branch")):
        url = deliveries.get(kind, {}).get("url")
        if isinstance(url, str) and url.strip():
            lines.append(f"{label}: {compact(url, 512)}")
    gates = view.get("gates", [])
    if gates and all(isinstance(g, dict) for g in gates):
        passed = []
        failed = []
        for gate in gates:
            label = _GATE_LABELS.get(gate.get("gate_id", ""), gate.get("gate_id", "?"))
            if gate.get("status") == "passed":
                passed.append(label)
            else:
                failed.append(label)
        if failed:
            parts = []
            if passed:
                parts.append(", ".join(passed) + " — пройдены")
            parts.append(", ".join(failed) + " — не пройдены")
            lines.append(f"Проверки: {'; '.join(parts)}")
        elif passed:
            lines.append(f"Проверки: {', '.join(passed)} — пройдены")
        else:
            lines.append("Проверки: нет данных о проверках")
    else:
        lines.append("Проверки: нет данных о проверках")
    if view.get("delivery_mode") == "none":
        lines.append("Деплой: не настроен для этого проекта")
    elif view.get("delivery_mode") == "deploy":
        deployment = deliveries.get("deployment", {})
        environment = deployment.get("environment")
        revision = deployment.get("deployed_revision")
        if deployment.get("status") == "verified" and environment and revision:
            lines.append(
                f"Деплой: {compact(environment, 128)} · ревизия {compact(revision, 12)} · проверен"
            )
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
    elapsed = _format_elapsed(view.get("started_at"), view.get("updated_at"))
    if elapsed:
        lines.append(f"Время: {elapsed}")
    workers = view.get("workers", [])
    telemetry_lines = _role_telemetry_lines(workers) + _usage_statistics_lines(workers)
    body = "\n".join(lines)
    suffix = "\n".join(telemetry_lines)
    result = body + ("\n" + suffix if suffix else "")
    if len(result) <= _MAX_COMPLETION_RESULT_CHARS:
        return result
    if suffix and len(suffix) + 2 < _MAX_COMPLETION_RESULT_CHARS:
        available = _MAX_COMPLETION_RESULT_CHARS - len(suffix) - 1
        body = body[:available - 1].rstrip() + "…"
        return body + "\n" + suffix
    return result[:_MAX_COMPLETION_RESULT_CHARS - 1].rstrip() + "…"


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
    if mode == "none":
        return deliveries.get("delivery") == "not_applicable"
    return (
        mode == "deploy"
        and gates.get("deployment") == "passed"
        and deliveries.get("deployment") == "verified"
    )


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
    if gates == {
        "tests": "passed", "review": "passed", "ci": "passed",
        "post-verify": "failed", "cleanup": "passed",
    }:
        return deliveries == {"pull_request": "merged"}
    return gates == {
        "tests": "passed", "review": "passed", "ci": "passed",
        "post-verify": "passed", "deployment": "failed", "cleanup": "passed",
    } and deliveries == {
        "pull_request": "merged", "default_branch": "verified", "deployment": "failed",
    }


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
    if gates.get("deployment") == "failed":
        return "central:auto-deployment-failed:v1", {
            "error": "Деплой точной слитой ревизии не прошёл после автоматических повторов",
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
        self._preflight_task_risk_history()

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
                CREATE TABLE IF NOT EXISTS mission_notification_targets (
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    last_notified_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease TEXT,
                    notification_lease_sequence INTEGER NOT NULL DEFAULT 0,
                    notification_lease_until REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (platform, chat_id, thread_id, mission_id)
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
            # Existing channel bindings remain the current mission for ordinary
            # answers. Notification cursors become many-to-many so concurrent
            # project missions cannot displace one another's updates.
            connection.execute(
                """INSERT OR IGNORE INTO mission_notification_targets(
                       platform, chat_id, thread_id, mission_id,
                       last_notified_sequence, notification_lease,
                       notification_lease_sequence, notification_lease_until
                   )
                   SELECT platform, chat_id, thread_id, mission_id,
                          last_notified_sequence, notification_lease,
                          notification_lease_sequence, notification_lease_until
                   FROM mission_subscriptions"""
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

    def _preflight_task_risk_history(self) -> None:
        """Reject pre-gate durable events before any legacy task can resume."""
        with self._db() as connection:
            rows = connection.execute(
                """SELECT mission_id, type, payload_json
                   FROM mission_events
                   WHERE type IN ('mission.accepted', 'mission.answer')
                   ORDER BY rowid"""
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            if row["type"] == "mission.answer":
                flags = task_owner_gate_flags(payload.get("text"))
                if flags:
                    raise MissionError(
                        "stored owner answer adds task capabilities: "
                        + ", ".join(flags)
                    )
                continue
            flags = task_owner_gate_flags(payload.get("goal"))
            unsupported = tuple(
                flag for flag in flags if flag != "architecture_change"
            )
            if unsupported:
                raise MissionError(
                    "stored mission requires separate capability setup: "
                    + ", ".join(unsupported)
                )
            expected = "architecture_change" if flags else None
            if payload.get("owner_gate_flag") not in {None, expected}:
                raise MissionError("stored mission owner gate flag is invalid")

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

    @staticmethod
    def _watch_target(
        connection: sqlite3.Connection,
        mission_id: str,
        platform: str,
        chat_id: str,
        thread_id: str,
    ) -> None:
        connection.execute(
            """INSERT INTO mission_notification_targets(
                   platform, chat_id, thread_id, mission_id
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(platform, chat_id, thread_id, mission_id) DO NOTHING""",
            (platform, chat_id, thread_id, mission_id),
        )

    @staticmethod
    def _default_workspace_telegram_target() -> tuple[str, str] | None:
        chat_id = os.environ.get("HERMES_MISSION_TELEGRAM_CHAT_ID", "").strip()
        thread_id = os.environ.get("HERMES_MISSION_TELEGRAM_THREAD_ID", "").strip()
        if not chat_id:
            return None
        if len(chat_id) > 256 or len(thread_id) > 256:
            raise MissionError("invalid default Telegram notification target")
        return chat_id, thread_id

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
                """SELECT last_notified_sequence FROM mission_notification_targets
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
        protected.update(
            row["mission_id"]
            for row in connection.execute(
                "SELECT mission_id, last_notified_sequence FROM mission_notification_targets"
            )
            if row["mission_id"] in views
            and row["last_notified_sequence"] < views[row["mission_id"]]["sequence"]
        )
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
                "DELETE FROM mission_notification_targets WHERE mission_id = ?",
                (mission_id,),
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

    def owner_turn_continues_mission(
        self,
        *,
        platform: str,
        source_message_id: str,
        session_id: str | None = None,
        chat_id: str | None = None,
        thread_id: str | None = None,
    ) -> bool:
        """Return whether a non-imperative turn belongs to existing mission intake."""
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
        if (
            self._intake_selection_receipt(platform, scope_key, source_message_id)
            or self._intake_cancel_receipt(platform, scope_key, source_message_id)
            or self._intake_draft(platform, scope_key)
        ):
            return True
        if chat_id:
            if self._bound_answer_receipt(
                platform, chat_id, thread_id, source_message_id
            ):
                return True
            mission_id = self.bound_mission(platform, chat_id, thread_id)
            if mission_id:
                view = self.projection(mission_id)
                return view.get("status") == "waiting_owner"
            return False
        return bool(
            self._session_answer_receipt(session_id, source_message_id)
            or self._session_open_question(session_id)
        )

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
        if requires_external_source(text):
            raise MissionError(
                "external source is not available through an immutable intake capability"
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
        if not is_execution_goal(text):
            raise MissionError("owner turn is not an execution goal")
        task_owner_gate_flag(text)
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
        owner_gate_flag = task_owner_gate_flag(goal)
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
            "project_label": target.get("label"),
            "project_repository": target.get("repository"),
            "input_platform": platform,
            "input_source_key_sha256": source_key_sha256,
            "input_source_message_sha256": hashlib.sha256(
                source_message_id.encode("utf-8")
            ).hexdigest(),
        }
        routine_limit = routine_docs_file_limit(goal)
        if routine_limit is not None:
            arguments.update(
                execution_class="routine_docs",
                expected_changed_files=routine_limit,
            )
        if owner_gate_flag is not None:
            arguments["owner_gate_flag"] = owner_gate_flag
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
        execution_class: str | None = None,
        expected_changed_files: int | None = None,
        owner_gate_flag: str | None = None,
        project_id: str | None = None,
        project_label: str | None = None,
        project_repository: str | None = None,
        parent_mission_id: str | None = None,
        input_platform: str | None = None,
        input_source_key_sha256: str | None = None,
        input_source_message_sha256: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        goal = str(goal or "").strip()
        if not goal or len(goal) > _MAX_OWNER_GOAL_CHARS:
            raise MissionError("invalid mission goal")
        derived_owner_gate_flag = task_owner_gate_flag(goal)
        if owner_gate_flag is None:
            owner_gate_flag = derived_owner_gate_flag
        elif owner_gate_flag != derived_owner_gate_flag:
            raise MissionError("invalid mission owner gate flag")
        mission_id = _require_id(mission_id or f"mission-{uuid.uuid4()}", "mission_id")
        if dispatch_profile is not None:
            dispatch_profile = _require_id(dispatch_profile, "dispatch_profile")
        if project_id is not None:
            project_id = _require_id(project_id, "project_id")
        if project_label is not None:
            project_label = _require_source_value(project_label, "project_label")
        if project_repository is not None:
            project_repository = _require_source_value(project_repository, "project_repository")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project_repository):
                raise MissionError("invalid project repository")
        if delivery_mode is not None and delivery_mode not in {"none", "deploy"}:
            raise MissionError("invalid mission delivery mode")
        if capability is not None and capability != _MEDIA_CAPABILITY:
            raise MissionError("invalid mission capability")
        if owner_gate_flag is not None and owner_gate_flag != "architecture_change":
            raise MissionError("invalid mission owner gate flag")
        if (execution_class, expected_changed_files) != (None, None) and (
            execution_class != "routine_docs"
            or not isinstance(expected_changed_files, int)
            or isinstance(expected_changed_files, bool)
            or not 1 <= expected_changed_files <= 2
        ):
            raise MissionError("invalid mission execution class")
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
                and first["payload"].get("owner_gate_flag") == owner_gate_flag
                and (
                    first["payload"].get("execution_class") == execution_class
                    or (
                        first["payload"].get("execution_class") is None
                        and execution_class == "routine_docs"
                    )
                )
                and (
                    first["payload"].get("expected_changed_files")
                    == expected_changed_files
                    or (
                        first["payload"].get("expected_changed_files") is None
                        and expected_changed_files is not None
                    )
                )
                and first["payload"].get("project_id") == project_id
                and (
                    first["payload"].get("project_label") == project_label
                    or (project_label is not None and first["payload"].get("project_label") is None)
                )
                and (
                    first["payload"].get("project_repository") == project_repository
                    or (project_repository is not None and first["payload"].get("project_repository") is None)
                )
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
        if project_label is not None:
            payload["project_label"] = project_label
        if project_repository is not None:
            payload["project_repository"] = project_repository
        if dispatch_profile is not None:
            payload["dispatch_profile"] = dispatch_profile
        if delivery_mode is not None:
            payload["delivery_mode"] = delivery_mode
        if capability is not None:
            payload["capability"] = capability
        if owner_gate_flag is not None:
            payload["owner_gate_flag"] = owner_gate_flag
        if execution_class is not None:
            payload.update(
                execution_class=execution_class,
                expected_changed_files=expected_changed_files,
            )
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
                """SELECT subscriptions.*,
                          COALESCE(targets.notification_lease_until, 0)
                              AS target_notification_lease_until
                   FROM mission_subscriptions AS subscriptions
                   LEFT JOIN mission_notification_targets AS targets
                     ON targets.platform = subscriptions.platform
                    AND targets.chat_id = subscriptions.chat_id
                    AND targets.thread_id = subscriptions.thread_id
                    AND targets.mission_id = subscriptions.mission_id
                   WHERE subscriptions.mission_id = ?
                     AND subscriptions.platform = 'telegram'""",
                (parent_mission_id,),
            ).fetchall()
            if rows:
                if any(row["target_notification_lease_until"] > now for row in rows):
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
                """SELECT subscriptions.*,
                          COALESCE(targets.notification_lease_until, 0)
                              AS target_notification_lease_until
                   FROM mission_subscriptions AS subscriptions
                   LEFT JOIN mission_notification_targets AS targets
                     ON targets.platform = subscriptions.platform
                    AND targets.chat_id = subscriptions.chat_id
                    AND targets.thread_id = subscriptions.thread_id
                    AND targets.mission_id = subscriptions.mission_id
                   WHERE subscriptions.mission_id = ?
                     AND subscriptions.platform = 'telegram'""",
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
                    for row in connection.execute(
                        """SELECT platform, chat_id, thread_id
                           FROM mission_subscriptions
                           WHERE mission_id = ? AND platform = 'telegram'""",
                        (child_mission_id,),
                    ).fetchall():
                        self._watch_target(
                            connection, child_mission_id,
                            row["platform"], row["chat_id"], row["thread_id"],
                        )
                    return
                raise MissionError("repair parent has no Telegram subscription")
            if any(row["target_notification_lease_until"] > now for row in rows):
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
                self._watch_target(
                    connection, child_mission_id,
                    row["platform"], row["chat_id"], row["thread_id"],
                )
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
            self._watch_target(
                connection, parent_mission_id,
                row["platform"], row["chat_id"], row["thread_id"],
            )
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
        task_flags = task_owner_gate_flags(text)
        if task_flags:
            raise MissionError(
                "owner answer cannot add task capabilities: "
                + ", ".join(task_flags)
            )
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
                """SELECT last_notified_sequence FROM mission_notification_targets
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
                    """SELECT 1 FROM mission_notification_targets
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
            if (
                event["type"] == "mission.accepted"
                and event["payload"].get("input_platform") == "workspace"
            ):
                target = self._default_workspace_telegram_target()
                if target is not None:
                    self._watch_target(
                        connection, mission_id, "telegram", target[0], target[1]
                    )
        return event, True

    def watch(
        self,
        mission_id: str,
        platform: str,
        chat_id: str,
        thread_id: str | None = None,
    ) -> None:
        """Idempotently add a notification recipient without changing answer routing."""
        mission_id = _require_id(mission_id, "mission_id")
        platform = _require_id(platform, "platform")
        chat_id = str(chat_id or "").strip()
        thread_id = str(thread_id or "").strip()
        if not chat_id or len(chat_id) > 256 or len(thread_id) > 256:
            raise MissionError("invalid mission notification target")
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM mission_events WHERE mission_id = ? LIMIT 1",
                (mission_id,),
            ).fetchone():
                raise MissionError("mission not found")
            self._watch_target(connection, mission_id, platform, chat_id, thread_id)

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
                """SELECT subscriptions.mission_id,
                          COALESCE(targets.last_notified_sequence, 0)
                              AS last_notified_sequence,
                          COALESCE(targets.notification_lease_until, 0)
                              AS notification_lease_until
                   FROM mission_subscriptions AS subscriptions
                   LEFT JOIN mission_notification_targets AS targets
                     ON targets.platform = subscriptions.platform
                    AND targets.chat_id = subscriptions.chat_id
                    AND targets.thread_id = subscriptions.thread_id
                    AND targets.mission_id = subscriptions.mission_id
                   WHERE subscriptions.platform = ?
                     AND subscriptions.chat_id = ?
                     AND subscriptions.thread_id = ?""",
                (platform, chat_id, thread_id),
            ).fetchone()
            if current and current["mission_id"] == mission_id:
                self._watch_target(
                    connection, mission_id, platform, chat_id, thread_id
                )
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
            self._watch_target(connection, mission_id, platform, chat_id, thread_id)
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
                """SELECT 1 FROM mission_notification_targets
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
                """SELECT * FROM mission_notification_targets
                   WHERE mission_id = ? AND last_notified_sequence < ?""",
                (mission_id, sequence),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_notification(self, subscription: dict[str, Any], sequence: int) -> str | None:
        token = uuid.uuid4().hex
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as connection:
            updated = connection.execute(
                """UPDATE mission_notification_targets
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
                    """UPDATE mission_notification_targets
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
                    """UPDATE mission_notification_targets
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
                """SELECT last_notified_sequence FROM mission_notification_targets
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
