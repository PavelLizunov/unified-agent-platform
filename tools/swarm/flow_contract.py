#!/usr/bin/env python3
"""Hermes Flow v2 contract: OpenAI routing, repo guards and review gates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import uuid
from typing import Any
from urllib.parse import urlsplit


class ContractError(ValueError):
    pass


def _safe_error(value: object) -> str:
    text = str(value).replace("\x00", "?")
    text = re.sub(r"(?i)://[^/\s@]+@", "://[REDACTED]@", text)
    text = re.sub(
        r"(?i)\b(?:authorization|proxy-authorization)\s*:\s*[^\r\n]+",
        "[REDACTED]",
        text,
    )
    text = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{40,}|"
        r"gh[pousr]_[A-Za-z0-9]{36}|tskey-(?:auth|client|api)-[A-Za-z0-9_-]+)\b",
        "[REDACTED]",
        text,
    )
    return text[-4000:] or "contract failed"


def load_json(path: str | pathlib.Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ContractError(f"{path}: expected a JSON object")
    return value


def write_json(path: str | pathlib.Path, value: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _required_text(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{where}.{key}: non-empty string required")
    return value.strip()


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


_DELIVERY_POLICY_FIELDS = {
    "policy_id", "complex_changed_files_at", "complex_prior_quality_failures_at",
    "escalated_prior_quality_failures_at", "complex_flags", "owner_gate_flags", "routes",
}
_DELIVERY_SIGNAL_FIELDS = {"schema_version", "changed_files", "prior_quality_failures", "flags"}
_DELIVERY_POLICY_FIELDS_V1 = {
    "policy_id", "complex_changed_files_at", "complex_prior_review_rejections_at",
    "escalated_prior_review_rejections_at", "complex_flags", "owner_gate_flags", "routes",
}
_DELIVERY_SIGNAL_FIELDS_V1 = {
    "schema_version", "changed_files", "prior_review_rejections", "flags",
}
_DELIVERY_ROUTE_FIELDS = {"task_class", "risk", "standing_approved", "author", "reviewer"}
_DELIVERY_ACTOR_FIELDS = {"engine", "model", "reasoning_effort"}
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_OPENAI_PROVIDER = "openai"
_OPENAI_AUTONOMY_ROUTES = {
    "standard": {
        "task_class": "standard_code", "risk": "medium",
        "author": {"engine": "codex", "model": "gpt-5.6-luna", "reasoning_effort": "medium"},
        "reviewer": {"engine": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "low"},
    },
    "complex": {
        "task_class": "complex_code", "risk": "high",
        "author": {"engine": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
        "reviewer": {"engine": "codex", "model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
    },
    "escalated": {
        "task_class": "escalated_code", "risk": "critical",
        "author": {"engine": "codex", "model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
        "reviewer": {"engine": "codex", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
    },
}
_CAPACITY_POLICY_ID = "openai-autonomy-capacity-v1"
_CAPACITY_ROUTE_ORDER = ("standard", "complex", "escalated")
_CAPACITY_MESSAGE = "Selected model is at capacity. Please try a different model."
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _closed_fields(value: Any, allowed: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{where}: expected an object")
    if unknown := set(value) - allowed:
        raise ContractError(f"{where}: unknown fields: {', '.join(sorted(unknown))}")
    if missing := allowed - value.keys():
        raise ContractError(f"{where}: missing fields: {', '.join(sorted(missing))}")
    return value


def _nonnegative_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{where}: non-negative integer required")
    return value


def _delivery_actor(value: Any, where: str) -> dict[str, str]:
    actor = _closed_fields(value, _DELIVERY_ACTOR_FIELDS, where)
    result = {
        field: _required_text(actor, field, where)
        for field in ("engine", "model", "reasoning_effort")
    }
    result["model"] = _exact_model(actor, where)
    if result["reasoning_effort"] not in _REASONING_EFFORTS:
        raise ContractError(f"{where}.reasoning_effort: invalid value")
    return result


def _choose_delivery_route(
    policy: dict[str, Any],
    signals: dict[str, Any],
    *,
    policy_id: str,
) -> dict[str, Any]:
    """Choose a deterministic repo-contract route without invoking a model."""
    if (
        not isinstance(policy, dict)
        or isinstance(policy.get("schema_version"), bool)
        or policy.get("schema_version") != 1
        or not isinstance(policy.get("engines"), dict)
    ):
        raise ContractError("policy: schema_version 1 plus an engines object required")
    codex = policy["engines"].get("codex")
    if (
        not isinstance(codex, dict)
        or codex.get("family") != "openai"
        or codex.get("requires_local_permission") is True
    ):
        raise ContractError("policy.engines.codex: unexpected delivery-route boundary")
    legacy = policy_id == "openai-autonomy-v1"
    if policy_id not in {"openai-autonomy-v1", "openai-autonomy-v2"}:
        raise ContractError("delivery_model_policy.policy_id: unsupported policy")
    config = _closed_fields(
        policy.get("delivery_model_policy"),
        _DELIVERY_POLICY_FIELDS_V1 if legacy else _DELIVERY_POLICY_FIELDS,
        "delivery_model_policy",
    )
    if config.get("policy_id") != policy_id:
        raise ContractError(f"delivery_model_policy.policy_id: expected {policy_id}")
    inputs = _closed_fields(
        signals, _DELIVERY_SIGNAL_FIELDS_V1 if legacy else _DELIVERY_SIGNAL_FIELDS, "signals"
    )
    if (
        isinstance(inputs["schema_version"], bool)
        or not isinstance(inputs["schema_version"], int)
        or inputs["schema_version"] != 1
    ):
        raise ContractError("signals.schema_version: expected 1")
    changed_files = _nonnegative_int(inputs["changed_files"], "signals.changed_files")
    failure_field = "prior_review_rejections" if legacy else "prior_quality_failures"
    prior_failures = _nonnegative_int(inputs[failure_field], f"signals.{failure_field}")
    if (
        not isinstance(inputs["flags"], list)
        or not all(isinstance(flag, str) and flag for flag in inputs["flags"])
        or len(inputs["flags"]) != len(set(inputs["flags"]))
    ):
        raise ContractError("signals.flags: unique non-empty strings required")

    def configured_flags(name: str) -> set[str]:
        values = config[name]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(flag, str) and flag for flag in values)
            or len(values) != len(set(values))
        ):
            raise ContractError(f"delivery_model_policy.{name}: unique non-empty strings required")
        return set(values)

    complex_flags = configured_flags("complex_flags")
    owner_flags = configured_flags("owner_gate_flags")
    if overlap := complex_flags & owner_flags:
        raise ContractError(
            "delivery_model_policy: flags cannot belong to both levels: "
            + ", ".join(sorted(overlap))
        )
    flags = set(inputs["flags"])
    if unknown := flags - complex_flags - owner_flags:
        raise ContractError(f"signals.flags: unknown flags: {', '.join(sorted(unknown))}")

    complex_files_at = _nonnegative_int(
        config["complex_changed_files_at"],
        "delivery_model_policy.complex_changed_files_at",
    )
    complex_failure_field = (
        "complex_prior_review_rejections_at" if legacy else "complex_prior_quality_failures_at"
    )
    escalated_failure_field = (
        "escalated_prior_review_rejections_at"
        if legacy else "escalated_prior_quality_failures_at"
    )
    complex_failures_at = _nonnegative_int(
        config[complex_failure_field], f"delivery_model_policy.{complex_failure_field}"
    )
    escalated_failures_at = _nonnegative_int(
        config[escalated_failure_field], f"delivery_model_policy.{escalated_failure_field}"
    )
    if not 0 < complex_failures_at < escalated_failures_at:
        raise ContractError("delivery_model_policy: quality-failure thresholds must increase")
    if complex_files_at < 1:
        raise ContractError("delivery_model_policy.complex_changed_files_at: expected 1 or more")

    owner_matches = sorted(flags & owner_flags)
    reasons: list[str]
    if prior_failures >= escalated_failures_at:
        reasons = [f"{failure_field}>={escalated_failures_at}"]
        route_name = "escalated"
    else:
        reasons = []
        complex_matches = sorted(flags & complex_flags)
        reasons.extend(f"flag:{flag}" for flag in complex_matches)
        if changed_files >= complex_files_at:
            reasons.append(f"changed_files>={complex_files_at}")
        if prior_failures >= complex_failures_at:
            reasons.append(f"{failure_field}>={complex_failures_at}")
        route_name = "complex" if reasons else "standard"
        if not reasons:
            reasons.append("default:standard")

    routes = config["routes"]
    if not isinstance(routes, dict) or set(routes) != {"standard", "complex", "escalated"}:
        raise ContractError("delivery_model_policy.routes: exact standard/complex/escalated routes required")
    resolved_routes: dict[str, dict[str, Any]] = {}
    for name in ("standard", "complex", "escalated"):
        candidate = _closed_fields(routes[name], _DELIVERY_ROUTE_FIELDS, f"route.{name}")
        if not isinstance(candidate["standing_approved"], bool):
            raise ContractError(f"route.{name}.standing_approved: boolean required")
        if not candidate["standing_approved"]:
            raise ContractError("all OpenAI delivery routes must be standing-approved")
        resolved_candidate = {
            "task_class": _required_text(candidate, "task_class", f"route.{name}"),
            "risk": _required_text(candidate, "risk", f"route.{name}"),
            "author": _delivery_actor(candidate["author"], f"route.{name}.author"),
            "reviewer": _delivery_actor(candidate["reviewer"], f"route.{name}.reviewer"),
        }
        if resolved_candidate != _OPENAI_AUTONOMY_ROUTES[name]:
            raise ContractError(f"route.{name}: exact ADR-031 actor tuple required")
        for component in ("author", "reviewer"):
            engine = resolved_candidate[component]["engine"]
            engine_policy = policy.get("engines", {}).get(engine)
            if (
                engine != "codex"
                or not isinstance(engine_policy, dict)
                or engine_policy.get("family") != "openai"
                or engine_policy.get("requires_local_permission") is True
            ):
                raise ContractError(f"route.{name}.{component}: OpenAI Codex engine required")
        if resolved_candidate["author"]["model"] == resolved_candidate["reviewer"]["model"]:
            raise ContractError(f"route.{name}: author and reviewer exact models must differ")
        resolved_routes[name] = {"standing_approved": True, **resolved_candidate}
    canonical_signals = {
        "schema_version": 1,
        "changed_files": changed_files,
        failure_field: prior_failures,
        "flags": sorted(flags),
    }
    policy_sha256 = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    resolved = None if owner_matches else resolved_routes[route_name]
    decision: dict[str, Any] = {
        "policy_id": _required_text(config, "policy_id", "delivery_model_policy"),
        "policy_sha256": policy_sha256,
        "route": None if owner_matches else route_name,
        "task_class": None if owner_matches else resolved["task_class"],
        "risk": None if owner_matches else resolved["risk"],
        "reasons": [*(f"flag:{flag}" for flag in owner_matches)] if owner_matches else reasons,
        "signals": canonical_signals,
    }
    decision["decision_id"] = hashlib.sha256(
        json.dumps(
            {**decision, "resolved_route": resolved},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if owner_matches:
        return {
            "status": "owner_approval_required", **decision,
            "author": None, "reviewer": None, "review_mode": None,
        }
    return {
        "status": "ready", **decision, "author": resolved["author"],
        "reviewer": resolved["reviewer"], "review_mode": "same_provider_independent",
    }


def choose_delivery_route(
    policy: dict[str, Any], signals: dict[str, Any]
) -> dict[str, Any]:
    """Choose the current deterministic repo-contract route."""
    return _choose_delivery_route(policy, signals, policy_id="openai-autonomy-v2")


def resolve_capacity_route(
    policy: dict[str, Any], base_decision: dict[str, Any], fallback_index: int
) -> dict[str, Any]:
    """Resolve a higher, complete ADR-approved route for an operational capacity failure."""
    if (
        not isinstance(fallback_index, int)
        or isinstance(fallback_index, bool)
        or fallback_index < 1
    ):
        raise ContractError("capacity fallback index must be a positive integer")
    if not isinstance(base_decision, dict) or base_decision.get("policy_id") not in {
        "openai-autonomy-v1", "openai-autonomy-v2",
    }:
        raise ContractError("capacity fallback requires a base quality route")
    base = validate_stored_delivery_route(policy, base_decision)
    if base.get("status") != "ready" or base.get("route") not in _CAPACITY_ROUTE_ORDER:
        raise ContractError("capacity fallback requires a ready base route")
    target_position = _CAPACITY_ROUTE_ORDER.index(base["route"]) + fallback_index
    if target_position >= len(_CAPACITY_ROUTE_ORDER):
        raise ContractError("capacity fallback exhausted the approved route chain")
    target_name = _CAPACITY_ROUTE_ORDER[target_position]
    config = policy.get("delivery_model_policy", {})
    target_signals = {
        "schema_version": 1,
        "changed_files": 0,
        "prior_quality_failures": (
            config.get("escalated_prior_quality_failures_at", 0)
            if target_name == "escalated"
            else config.get("complex_prior_quality_failures_at", 0)
        ),
        "flags": [],
    }
    target = choose_delivery_route(policy, target_signals)
    if target.get("route") != target_name or target.get("status") != "ready":
        raise ContractError("capacity fallback did not resolve an approved complete route")
    decision = {
        "status": "ready",
        "policy_id": _CAPACITY_POLICY_ID,
        "policy_sha256": target["policy_sha256"],
        "route": target["route"],
        "task_class": target["task_class"],
        "risk": target["risk"],
        "reasons": [f"capacity_fallback:{base['route']}->{target['route']}"],
        "signals": base["signals"],
        "base_decision": base_decision,
        "capacity_fallback_index": fallback_index,
        "author": target["author"],
        "reviewer": target["reviewer"],
        "review_mode": target["review_mode"],
    }
    decision["decision_id"] = hashlib.sha256(
        json.dumps(decision, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return decision


def parse_codex_failure(
    path: str | pathlib.Path, stderr: str | None = None
) -> dict[str, Any]:
    """Classify only trusted terminal Codex failure locations; never inspect tool/model output."""
    thread_started = False
    turn_started = False
    item_seen = False
    permanent_signal = False
    terminal_messages: list[tuple[str, str]] = []
    stderr_messages: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "thread.started":
                thread_started = True
            elif event_type == "turn.started":
                turn_started = True
            elif isinstance(event_type, str) and event_type.startswith("item."):
                item_seen = True
            if event_type in {"error", "turn.failed"}:
                message = event.get("message")
                detail = event.get("error") if isinstance(event.get("error"), dict) else event
                if not isinstance(message, str):
                    message = detail.get("message")
                if isinstance(message, str):
                    terminal_messages.append((str(event_type), message))
                info = detail.get("codexErrorInfo", event.get("codexErrorInfo"))
                info_object = info if isinstance(info, dict) else {}
                if isinstance(info, dict):
                    info = info.get("type")
                normalized_info = info.casefold() if isinstance(info, str) else None
                status = detail.get("httpStatusCode")
                if status is None:
                    status = event.get("httpStatusCode")
                if status is None:
                    status = info_object.get("httpStatusCode")
                if normalized_info in {
                    "badrequest", "unauthorized", "sandboxerror", "usagelimitexceeded",
                    "contextwindowexceeded",
                } or status in {400, 401, 403, 404}:
                    permanent_signal = True
    for raw_line in (stderr or "").splitlines():
        line = _ANSI_ESCAPE.sub("", raw_line).strip()
        if line.lower().startswith("error:"):
            line = line.split(":", 1)[1].strip()
        if line:
            stderr_messages.append(line)
    capacity_source = None
    if terminal_messages and all(
        message.strip() == _CAPACITY_MESSAGE for _source, message in terminal_messages
    ):
        capacity_source = terminal_messages[0][0]
    elif not terminal_messages and any(
        message.strip() == _CAPACITY_MESSAGE for message in stderr_messages
    ):
        capacity_source = "stderr"
    if permanent_signal:
        capacity_source = None
    diagnostic = next(
        (message for _source, message in terminal_messages if message.strip()),
        next((message for message in stderr_messages if message.strip()), ""),
    )
    return {
        "schema_version": 1,
        "error_class": "transient_capacity" if capacity_source else "unknown",
        "terminal_source": capacity_source,
        "thread_started": thread_started,
        "turn_started": turn_started,
        "item_seen": item_seen,
        "permanent_signal": permanent_signal,
        "safe_before_side_effects": not (thread_started or turn_started or item_seen),
        "message_sha256": hashlib.sha256(diagnostic.encode("utf-8")).hexdigest(),
    }


def _legacy_delivery_policy(policy: dict[str, Any]) -> dict[str, Any]:
    legacy = json.loads(json.dumps(policy))
    config = _closed_fields(
        legacy.get("delivery_model_policy"), _DELIVERY_POLICY_FIELDS, "delivery_model_policy"
    )
    if config.get("policy_id") != "openai-autonomy-v2":
        raise ContractError("legacy route recovery requires the current v2 policy")
    config["policy_id"] = "openai-autonomy-v1"
    config["complex_prior_review_rejections_at"] = config.pop(
        "complex_prior_quality_failures_at"
    )
    config["escalated_prior_review_rejections_at"] = config.pop(
        "escalated_prior_quality_failures_at"
    )
    return legacy


def validate_stored_delivery_route(
    policy: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any]:
    """Validate a durable current or exact compatible v1 route; return its v2 equivalent."""
    if not isinstance(decision, dict) or not isinstance(decision.get("signals"), dict):
        raise ContractError("route decision with canonical signals required")
    if decision.get("policy_id") == _CAPACITY_POLICY_ID:
        expected = resolve_capacity_route(
            policy,
            decision.get("base_decision"),
            decision.get("capacity_fallback_index"),
        )
        if decision != expected:
            raise ContractError("capacity route decision does not match the fail-closed policy")
        return expected
    if decision.get("policy_id") == "openai-autonomy-v2":
        current = choose_delivery_route(policy, decision["signals"])
        if decision != current:
            raise ContractError("route decision does not match the current fail-closed policy")
        return current
    if decision.get("policy_id") != "openai-autonomy-v1":
        raise ContractError("durable route decision uses an unsupported policy")
    legacy = _choose_delivery_route(
        _legacy_delivery_policy(policy),
        decision["signals"],
        policy_id="openai-autonomy-v1",
    )
    if decision != legacy:
        raise ContractError("legacy route decision does not match the exact v1 policy")
    signals = decision["signals"]
    current = choose_delivery_route(policy, {
        "schema_version": signals["schema_version"],
        "changed_files": signals["changed_files"],
        "prior_quality_failures": signals["prior_review_rejections"],
        "flags": signals["flags"],
    })
    compatible = ("status", "route", "task_class", "risk", "author", "reviewer", "review_mode")
    if any(decision.get(field) != current.get(field) for field in compatible):
        raise ContractError("legacy route is not execution-compatible with the current policy")
    return current


def _validate_checks(value: Any, where: str) -> None:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{where}: at least one check required")
    for index, check in enumerate(value):
        if not isinstance(check, dict) or not isinstance(check.get("command"), str):
            raise ContractError(f"{where}[{index}]: command required")
        if check.get("exit_code") != 0:
            raise ContractError(f"{where}[{index}]: non-green exit_code")


def _exact_model(obj: dict[str, Any], where: str) -> str:
    model = _required_text(obj, "model", where)
    aliases = {"default", "unknown", "runtime-required", "opus", "sonnet", "haiku", "fable"}
    if model.lower() in aliases or model.startswith("$") or not any(char.isdigit() for char in model):
        raise ContractError(f"{where}.model: exact model ID required, got {model!r}")
    return model


def _validate_runtime_attestation(
    artifact: dict[str, Any], telemetry: dict[str, Any], *, component: str, sandbox: str
) -> None:
    where = f"{component}_telemetry"
    if telemetry.get("schema_version") != 1 or telemetry.get("status") != "completed":
        raise ContractError(f"{where}: completed schema_version 1 telemetry required")
    if telemetry.get("model_provider") != _OPENAI_PROVIDER:
        raise ContractError(f"{where}.model_provider: approved OpenAI provider required")
    artifact_effort = _required_text(artifact, "reasoning_effort", component)
    telemetry_effort = _required_text(telemetry, "reasoning_effort", where)
    allowed_efforts = {"low", "medium", "high", "xhigh", "max"}
    if artifact_effort not in allowed_efforts or telemetry_effort not in allowed_efforts:
        raise ContractError(f"{where}.reasoning_effort: valid exact effort required")
    for key in ("engine_family", "model", "reasoning_effort", "session_id"):
        if telemetry.get(key) != artifact.get(key):
            raise ContractError(f"{where}.{key}: runtime attestation mismatch")
    if telemetry.get("component") != component:
        raise ContractError(f"{where}.component: expected {component!r}")
    if telemetry.get("sandbox") != sandbox:
        raise ContractError(f"{where}.sandbox: expected {sandbox!r}")
    sha_key = "head_sha" if component == "author" else "reviewed_sha"
    if telemetry.get("head_sha") != artifact.get(sha_key) or telemetry.get("worktree_clean") is not True:
        raise ContractError(f"{where}: clean exact-SHA worktree attestation required")
    expected_repo_attestation = (
        "post_turn_clean_head" if component == "author" else "codex_rollout_prompt_sha256"
    )
    if telemetry.get("repo_attestation") != expected_repo_attestation:
        raise ContractError(f"{where}: source-bound exact-SHA attestation required")
    _required_text(telemetry, "tree_sha", where)
    if component == "reviewer":
        _required_text(telemetry, "source_attestation_sha256", where)
    if (
        telemetry.get("model_attestation") != "codex_rollout_turn_context"
        or telemetry.get("reasoning_effort_attestation") != "codex_rollout_turn_context"
        or telemetry.get("sandbox_attestation") != "codex_rollout_turn_context"
    ):
        raise ContractError(f"{where}: Codex rollout attestation required")


def validate_review(
    summary: dict[str, Any],
    verification: dict[str, Any],
    author_telemetry: dict[str, Any],
    reviewer_telemetry: dict[str, Any],
    route_decision: dict[str, Any],
    policy: dict[str, Any],
    *,
    expected_repo: str,
    current_head: str,
    ci_green: bool,
) -> None:
    current_decision = validate_stored_delivery_route(policy, route_decision)
    if current_decision.get("status") != "ready":
        raise ContractError("route decision is not ready")
    expected_decision = route_decision
    if summary.get("schema_version") != 1 or verification.get("schema_version") != 1:
        raise ContractError("summary and verification schema_version must be 1")
    if _required_text(summary, "repo", "summary") != expected_repo:
        raise ContractError("summary.repo does not match mission allowlist")
    author_head = _required_text(summary, "head_sha", "summary")
    reviewed_head = _required_text(verification, "reviewed_sha", "verification")
    if author_head != current_head or reviewed_head != current_head:
        raise ContractError("stale review: author, reviewer and current HEAD must match")
    if verification.get("verdict") != "accept":
        raise ContractError("review verdict is not accept")
    _required_text(summary, "branch", "summary")
    author_model = _exact_model(summary, "summary")
    reviewer_model = _exact_model(verification, "verification")
    author_session = _required_text(summary, "session_id", "summary")
    reviewer_session = _required_text(verification, "session_id", "verification")
    decision_id = _required_text(expected_decision, "decision_id", "route_decision")
    if (
        summary.get("route_decision_id") != decision_id
        or verification.get("route_decision_id") != decision_id
    ):
        raise ContractError("author and reviewer must bind the exact route decision")
    if summary.get("task_class") != expected_decision["task_class"]:
        raise ContractError("summary.task_class does not match the route decision")
    for artifact, actor, where in (
        (summary, expected_decision["author"], "summary"),
        (verification, expected_decision["reviewer"], "verification"),
    ):
        if (
            artifact.get("engine_family") != "openai"
            or artifact.get("model") != actor["model"]
            or artifact.get("reasoning_effort") != actor["reasoning_effort"]
        ):
            raise ContractError(f"{where} does not match the exact OpenAI route actor")
    _validate_runtime_attestation(
        summary, author_telemetry, component="author", sandbox="workspace-write"
    )
    _validate_runtime_attestation(
        verification, reviewer_telemetry, component="reviewer", sandbox="read-only"
    )
    review_mode = _required_text(verification, "review_mode", "verification")
    if review_mode != expected_decision["review_mode"]:
        raise ContractError("review mode does not match the route decision")
    if author_model == reviewer_model:
        raise ContractError("same-provider author and reviewer must use different exact models")
    if author_session == reviewer_session:
        raise ContractError("same-provider author and reviewer must use different sessions")
    changed_files = summary.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files or not all(
        isinstance(item, str) and item for item in changed_files
    ):
        raise ContractError("summary.changed_files: non-empty string list required")
    findings = verification.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, str) for item in findings):
        raise ContractError("verification.findings: string list required")
    if findings:
        raise ContractError("accepted review has actionable findings")
    _validate_checks(summary.get("checks"), "summary.checks")
    _validate_checks(verification.get("checks"), "verification.checks")
    cycles = verification.get("review_cycle")
    if not isinstance(cycles, int) or not 1 <= cycles <= 8:
        raise ContractError("verification.review_cycle must be between 1 and 8")
    if not ci_green:
        raise ContractError("required CI is not green")


def terminal_complete(
    *, merged: bool, main_contains_head: bool, branch_deleted: bool, worktree_removed: bool
) -> bool:
    return all((merged, main_contains_head, branch_deleted, worktree_removed))


def _codex_rollout_context(
    path: str | pathlib.Path,
    *,
    session_id: str,
    expected_model: str,
    expected_reasoning_effort: str | None,
    expected_sandbox: str,
    expected_worktree: str | pathlib.Path,
    source_attestation: dict[str, Any] | None,
) -> dict[str, str]:
    session_meta: list[dict[str, Any]] = []
    turn_context: list[dict[str, Any]] = []
    user_texts: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ContractError(f"rollout line {line_number}: invalid JSON") from error
            if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
                continue
            if event.get("type") == "session_meta":
                session_meta.append(event["payload"])
            elif event.get("type") == "turn_context":
                turn_context.append(event["payload"])
            elif event.get("type") == "response_item":
                payload = event["payload"]
                if payload.get("type") == "message" and payload.get("role") == "user":
                    for item in payload.get("content", []):
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            user_texts.append(item["text"])
    if len(session_meta) != 1 or not turn_context:
        raise ContractError("rollout must contain exactly one session_meta and one turn_context")
    if any(context != turn_context[0] for context in turn_context[1:]):
        raise ContractError("rollout turn_context entries conflict")
    meta, context = session_meta[0], turn_context[0]
    if _required_text(meta, "id", "rollout.session_meta") != session_id:
        raise ContractError("rollout session does not match telemetry thread")
    persisted_session = meta.get("session_id")
    if persisted_session is not None and persisted_session != session_id:
        raise ContractError("rollout persisted session does not match telemetry thread")
    worktree = pathlib.Path(expected_worktree).resolve()
    if pathlib.Path(_required_text(meta, "cwd", "rollout.session_meta")).resolve() != worktree:
        raise ContractError("rollout cwd does not match attested worktree")
    actual_model = _exact_model(context, "rollout.turn_context")
    if actual_model != expected_model:
        raise ContractError(
            f"runtime model mismatch: expected {expected_model!r}, observed {actual_model!r}"
        )
    actual_reasoning_effort = context.get("effort")
    if expected_reasoning_effort is not None:
        actual_reasoning_effort = _required_text(context, "effort", "rollout.turn_context")
        if actual_reasoning_effort != expected_reasoning_effort:
            raise ContractError(
                "runtime reasoning effort mismatch: "
                f"expected {expected_reasoning_effort!r}, observed {actual_reasoning_effort!r}"
            )
    sandbox_policy = context.get("sandbox_policy")
    if not isinstance(sandbox_policy, dict):
        raise ContractError("rollout.turn_context.sandbox_policy: object required")
    actual_sandbox = _required_text(sandbox_policy, "type", "rollout.turn_context.sandbox_policy")
    if actual_sandbox != expected_sandbox:
        raise ContractError(
            f"runtime sandbox mismatch: expected {expected_sandbox!r}, observed {actual_sandbox!r}"
        )
    model_provider = _required_text(meta, "model_provider", "rollout.session_meta")
    if model_provider != _OPENAI_PROVIDER:
        raise ContractError("rollout.session_meta.model_provider: approved OpenAI provider required")
    result = {
        "model": actual_model,
        "model_provider": model_provider,
        "sandbox": actual_sandbox,
        "codex_cli_version": _required_text(meta, "cli_version", "rollout.session_meta"),
    }
    if expected_reasoning_effort is not None:
        result["reasoning_effort"] = actual_reasoning_effort
    if source_attestation is not None:
        digest = _required_text(source_attestation, "sha256", "source_attestation")
        marker = f"UAP_SOURCE_ATTESTATION_SHA256={digest}"
        if sum(text.count(marker) for text in user_texts) != 1:
            raise ContractError("source attestation marker must appear exactly once in rollout user input")
        created = _parse_time(_required_text(source_attestation, "created_at", "source_attestation"))
        started = _parse_time(_required_text(meta, "timestamp", "rollout.session_meta"))
        if created is None or started is None or not dt.timedelta(0) <= started - created <= dt.timedelta(minutes=5):
            raise ContractError("source attestation must immediately precede the Codex session")
        result["source_attestation_sha256"] = digest
    return result


def _repo_attestation(path: str | pathlib.Path, expected_head: str) -> dict[str, Any]:
    requested = pathlib.Path(path).resolve()
    root = pathlib.Path(_git(requested, "rev-parse", "--show-toplevel")).resolve()
    if root != requested:
        raise ContractError(f"worktree root mismatch: requested {requested}, actual {root}")
    actual_head = _git(root, "rev-parse", "HEAD")
    if actual_head != expected_head:
        raise ContractError(
            f"worktree HEAD mismatch: expected {expected_head!r}, observed {actual_head!r}"
        )
    if _git(root, "status", "--porcelain=v1"):
        raise ContractError("worktree must be clean for runtime attestation")
    return {
        "worktree": str(root),
        "head_sha": actual_head,
        "tree_sha": _git(root, "rev-parse", "HEAD^{tree}"),
        "worktree_clean": True,
    }


def source_attestation(path: str | pathlib.Path, expected_head: str) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        **_repo_attestation(path, expected_head),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "nonce": str(uuid.uuid4()),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value["sha256"] = hashlib.sha256(encoded).hexdigest()
    return value


def _validate_source_attestation(
    value: dict[str, Any], *, worktree: str | pathlib.Path, head: str
) -> dict[str, Any]:
    digest = _required_text(value, "sha256", "source_attestation")
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != digest:
        raise ContractError("source attestation digest mismatch")
    current = _repo_attestation(worktree, head)
    for key in ("worktree", "head_sha", "tree_sha", "worktree_clean"):
        if value.get(key) != current[key]:
            raise ContractError(f"source attestation {key} no longer matches worktree")
    return value


def summarize_codex_events(
    path: str | pathlib.Path,
    *,
    component: str,
    model: str,
    reasoning_effort: str,
    rollout: str | pathlib.Path,
    sandbox: str,
    worktree: str | pathlib.Path,
    head: str,
    source_attestation_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    _exact_model({"model": model}, "telemetry")
    session_id = None
    usage = None
    tool_calls: dict[str, int] = {}
    failed_commands = 0
    timeouts = 0
    non_json_lines = 0
    completed = False
    rerouted = False
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                non_json_lines += 1
                continue
            event_type = event.get("type")
            if event_type == "thread.started":
                session_id = event.get("thread_id")
            elif event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "unknown")
                tool_calls[item_type] = tool_calls.get(item_type, 0) + 1
                if item_type == "command_execution" and item.get("status") == "failed":
                    failed_commands += 1
                if "timed out" in str(item.get("aggregated_output", "")).lower():
                    timeouts += 1
                if item_type == "error" and "model rerouted:" in str(item.get("message", "")).lower():
                    rerouted = True
            elif event_type == "turn.completed":
                usage = event.get("usage")
                completed = True
    if not isinstance(session_id, str) or not session_id:
        raise ContractError("telemetry: thread.started event missing")
    if not completed:
        raise ContractError("telemetry: turn.completed event missing")
    if rerouted:
        raise ContractError("telemetry: model reroute is not an exact-model run")
    repo = _repo_attestation(worktree, head)
    source = None
    if component == "reviewer":
        if source_attestation_path is None:
            raise ContractError("reviewer telemetry requires a source attestation")
        source = _validate_source_attestation(
            load_json(source_attestation_path), worktree=worktree, head=head
        )
    runtime = _codex_rollout_context(
        rollout,
        session_id=session_id,
        expected_model=model,
        expected_reasoning_effort=reasoning_effort,
        expected_sandbox=sandbox,
        expected_worktree=worktree,
        source_attestation=source,
    )
    result = {
        "schema_version": 1,
        "component": component,
        "engine": "codex",
        "engine_family": "openai",
        "model": runtime["model"],
        "model_provider": runtime["model_provider"],
        "model_attestation": "codex_rollout_turn_context",
        "sandbox": runtime["sandbox"],
        "sandbox_attestation": "codex_rollout_turn_context",
        "codex_cli_version": runtime["codex_cli_version"],
        "repo_attestation": (
            "codex_rollout_prompt_sha256" if source is not None else "post_turn_clean_head"
        ),
        "source_attestation_sha256": runtime.get("source_attestation_sha256"),
        **repo,
        "session_id": session_id,
        "status": "completed",
        "tool_calls": tool_calls,
        "failed_commands": failed_commands,
        "timeouts": timeouts,
        "retries": None,
        "non_json_lines": non_json_lines,
        "usage": usage,
    }
    if reasoning_effort is not None:
        result.update(
            reasoning_effort=runtime["reasoning_effort"],
            reasoning_effort_attestation="codex_rollout_turn_context",
        )
    return result


def canonical_remote(value: str) -> str:
    value = value.strip().removesuffix(".git").removesuffix("/")
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {"http", "https"} and parsed.username is not None:
        raise ContractError("remote URL userinfo is forbidden")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    return value.lower()


def _git(path: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ContractError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def guard_repo(path: str | pathlib.Path, expected_remote: str, expected_branch: str) -> dict[str, str]:
    requested = pathlib.Path(path).resolve()
    root = pathlib.Path(_git(requested, "rev-parse", "--show-toplevel")).resolve()
    if root != requested:
        raise ContractError(f"repo root mismatch: requested {requested}, actual {root}")
    remote = _git(root, "remote", "get-url", "origin")
    branch = _git(root, "branch", "--show-current")
    if canonical_remote(remote) != canonical_remote(expected_remote):
        raise ContractError("remote mismatch")
    if branch != expected_branch or branch in {"main", "master"}:
        raise ContractError(f"branch mismatch or protected default branch: {branch!r}")
    worktrees = [
        pathlib.Path(line[9:]).resolve()
        for line in _git(root, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    ]
    if root not in worktrees:
        raise ContractError(f"{root} is not a registered git worktree")
    if worktrees and root == worktrees[0]:
        raise ContractError(f"{root} is the primary checkout; a disposable worktree is required")
    return {"root": str(root), "remote": remote, "branch": branch}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    delivery_route = sub.add_parser("delivery-route")
    delivery_route.add_argument("--policy", required=True)
    delivery_route.add_argument("--signals", required=True)

    review = sub.add_parser("validate-review")
    review.add_argument("--summary", required=True)
    review.add_argument("--verification", required=True)
    review.add_argument("--author-telemetry", required=True)
    review.add_argument("--reviewer-telemetry", required=True)
    review.add_argument("--route-decision", required=True)
    review.add_argument("--policy", required=True)
    review.add_argument("--repo", required=True)
    review.add_argument("--head", required=True)
    review.add_argument("--ci-green", action="store_true")

    guard = sub.add_parser("guard-repo")
    guard.add_argument("--path", required=True)
    guard.add_argument("--remote", required=True)
    guard.add_argument("--branch", required=True)

    terminal = sub.add_parser("terminal-check")
    terminal.add_argument("--merged", action="store_true")
    terminal.add_argument("--main-contains-head", action="store_true")
    terminal.add_argument("--branch-deleted", action="store_true")
    terminal.add_argument("--worktree-removed", action="store_true")

    attest = sub.add_parser("attest-source")
    attest.add_argument("--worktree", required=True)
    attest.add_argument("--head", required=True)
    attest.add_argument("--output", required=True)

    telemetry = sub.add_parser("summarize-codex")
    telemetry.add_argument("--events", required=True)
    telemetry.add_argument("--component", required=True)
    telemetry.add_argument("--model", required=True)
    telemetry.add_argument(
        "--reasoning-effort", required=True,
        choices=("low", "medium", "high", "xhigh", "max"),
    )
    telemetry.add_argument("--rollout", required=True)
    telemetry.add_argument("--worktree", required=True)
    telemetry.add_argument("--head", required=True)
    telemetry.add_argument("--source-attestation")
    telemetry.add_argument(
        "--sandbox", required=True,
        choices=("read-only", "workspace-write", "danger-full-access"),
    )
    telemetry.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "delivery-route":
            result = choose_delivery_route(
                load_json(args.policy), load_json(args.signals),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ready" else 3
        if args.command == "validate-review":
            validate_review(
                load_json(args.summary), load_json(args.verification),
                load_json(args.author_telemetry), load_json(args.reviewer_telemetry),
                load_json(args.route_decision), load_json(args.policy),
                expected_repo=args.repo,
                current_head=args.head, ci_green=args.ci_green,
            )
            print("hermes-flow-review-ok")
            return 0
        if args.command == "guard-repo":
            print(json.dumps(guard_repo(args.path, args.remote, args.branch), indent=2))
            return 0
        if args.command == "terminal-check":
            if not terminal_complete(
                merged=args.merged, main_contains_head=args.main_contains_head,
                branch_deleted=args.branch_deleted, worktree_removed=args.worktree_removed,
            ):
                raise ContractError("terminal state requires merge, default-branch proof and cleanup")
            print("hermes-flow-terminal-ok")
            return 0
        if args.command == "attest-source":
            value = source_attestation(args.worktree, args.head)
            write_json(args.output, value)
            print(f"UAP_SOURCE_ATTESTATION_SHA256={value['sha256']}")
            return 0
        if args.command == "summarize-codex":
            result = summarize_codex_events(
                args.events, component=args.component, model=args.model,
                reasoning_effort=args.reasoning_effort,
                rollout=args.rollout, sandbox=args.sandbox,
                worktree=args.worktree, head=args.head,
                source_attestation_path=args.source_attestation,
            )
            write_json(args.output, result)
            print("hermes-flow-telemetry-ok")
            return 0
    except (ContractError, OSError, json.JSONDecodeError) as error:
        print(f"hermes-flow-error: {_safe_error(error)}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
