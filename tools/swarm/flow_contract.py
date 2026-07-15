#!/usr/bin/env python3
"""Hermes Flow v2 contract: routing, quota state, repo guards and review gates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import uuid
from typing import Any


class ContractError(ValueError):
    pass


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


def quota_state(quota: dict[str, Any], engine: str, now: dt.datetime | None = None) -> str:
    entry = quota.get("engines", {}).get(engine, {"state": "unknown"})
    state = entry.get("state", "unknown")
    if state not in {"available", "quota_blocked", "unknown"}:
        raise ContractError(f"quota.engines.{engine}.state: invalid state {state!r}")
    until = _parse_time(entry.get("blocked_until"))
    now = now or dt.datetime.now(dt.timezone.utc)
    if state == "quota_blocked" and until and now >= until:
        return "unknown"
    return state


def set_quota(
    quota: dict[str, Any], engine: str, state: str, blocked_until: str | None, reason: str | None
) -> dict[str, Any]:
    if state not in {"available", "quota_blocked", "unknown"}:
        raise ContractError(f"invalid quota state {state!r}")
    if blocked_until:
        _parse_time(blocked_until)
    quota.setdefault("schema_version", 1)
    quota.setdefault("engines", {})[engine] = {
        "state": state,
        "blocked_until": blocked_until,
        "reason": reason,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return quota


def _resolve_candidate(
    candidate: dict[str, Any], policy: dict[str, Any], model_overrides: dict[str, str]
) -> dict[str, str] | None:
    engine = _required_text(candidate, "engine", "candidate")
    engine_policy = policy.get("engines", {}).get(engine)
    if not isinstance(engine_policy, dict):
        raise ContractError(f"candidate engine {engine!r} is absent from policy.engines")
    model = candidate.get("model")
    if not model and candidate.get("model_env"):
        model = model_overrides.get(engine) or os.environ.get(candidate["model_env"])
    if not isinstance(model, str) or not model.strip():
        return None
    return {"engine": engine, "family": _required_text(engine_policy, "family", engine), "model": model}


def choose_route(
    policy: dict[str, Any],
    quota: dict[str, Any],
    task_class: str,
    *,
    allow_local: bool = False,
    allow_unknown: bool = False,
    model_overrides: dict[str, str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    route = policy.get("routes", {}).get(task_class)
    if not isinstance(route, dict):
        raise ContractError(f"unknown task class {task_class!r}")
    model_overrides = model_overrides or {}

    def eligible(
        items: list[dict[str, Any]], forbidden_family: str | None = None,
        allow_same_family: bool = False,
    ) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
        skipped: list[dict[str, str]] = []
        for item in items:
            engine = _required_text(item, "engine", "candidate")
            engine_policy = policy.get("engines", {}).get(engine)
            if not isinstance(engine_policy, dict):
                raise ContractError(f"candidate engine {engine!r} is absent from policy.engines")
            family = _required_text(engine_policy, "family", engine)
            if family == forbidden_family and not (
                allow_same_family and item.get("same_provider_fallback") is True
            ):
                skipped.append({"engine": engine, "reason": "same_family"})
                continue
            if engine_policy.get("requires_local_permission") and not allow_local:
                skipped.append({"engine": engine, "reason": "local_permission_required"})
                continue
            state = quota_state(quota, engine, now)
            if state != "available" and not (state == "unknown" and allow_unknown):
                skipped.append({"engine": engine, "reason": state})
                continue
            resolved = _resolve_candidate(item, policy, model_overrides)
            if not resolved:
                skipped.append({"engine": engine, "reason": "exact_model_unresolved"})
                continue
            resolved["quota_state"] = state
            return resolved, skipped
        return None, skipped

    author, author_skipped = eligible(route.get("authors", []))
    if not author:
        return {
            "status": "author_blocked",
            "task_class": task_class,
            "author": None,
            "reviewer": None,
            "skipped": {"authors": author_skipped},
        }
    reviewer, reviewer_skipped = eligible(
        route.get("reviewers", []),
        author["family"],
        allow_same_family=route.get("same_provider_fallback") is True,
    )
    review_mode = None
    if reviewer:
        review_mode = (
            "same_provider_degraded"
            if reviewer["family"] == author["family"]
            else "cross_family"
        )
    return {
        "status": "ready" if reviewer else "review_blocked",
        "task_class": task_class,
        "risk": route.get("risk"),
        "author": author,
        "reviewer": reviewer,
        "review_mode": review_mode,
        "skipped": {"authors": author_skipped, "reviewers": reviewer_skipped},
    }


_DELIVERY_POLICY_FIELDS = {
    "policy_id", "complex_changed_files_at", "complex_prior_review_rejections_at",
    "owner_gate_prior_review_rejections_at", "complex_flags", "owner_gate_flags", "routes",
}
_DELIVERY_SIGNAL_FIELDS = {"schema_version", "changed_files", "prior_review_rejections", "flags"}
_DELIVERY_ROUTE_BASE_FIELDS = {"task_class", "risk", "standing_approved"}
_DELIVERY_STANDARD_ROUTE_FIELDS = {
    *_DELIVERY_ROUTE_BASE_FIELDS, "author_reasoning_effort", "reviewer_reasoning_effort",
}
_DELIVERY_STRONG_ROUTE_FIELDS = {
    *_DELIVERY_ROUTE_BASE_FIELDS, "author", "reviewer",
}
_DELIVERY_ACTOR_FIELDS = {"engine", "model", "reasoning_effort"}
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


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


def choose_delivery_route(
    policy: dict[str, Any],
    signals: dict[str, Any],
    quota: dict[str, Any] | None = None,
    *,
    model_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Choose a deterministic repo-contract route without invoking a model."""
    if (
        not isinstance(policy, dict)
        or isinstance(policy.get("schema_version"), bool)
        or policy.get("schema_version") != 1
        or not isinstance(policy.get("engines"), dict)
        or not isinstance(policy.get("routes"), dict)
    ):
        raise ContractError("policy: schema_version 1 plus engines/routes objects required")
    if model_overrides is not None and not isinstance(model_overrides, dict):
        raise ContractError("model_overrides: expected an object")
    for engine, family in (("codex", "openai"), ("claude", "anthropic")):
        entry = policy["engines"].get(engine)
        if (
            not isinstance(entry, dict)
            or entry.get("family") != family
            or entry.get("requires_local_permission") is True
        ):
            raise ContractError(f"policy.engines.{engine}: unexpected standard-route boundary")
    config = _closed_fields(
        policy.get("delivery_model_policy"), _DELIVERY_POLICY_FIELDS, "delivery_model_policy"
    )
    inputs = _closed_fields(signals, _DELIVERY_SIGNAL_FIELDS, "signals")
    if (
        isinstance(inputs["schema_version"], bool)
        or not isinstance(inputs["schema_version"], int)
        or inputs["schema_version"] != 1
    ):
        raise ContractError("signals.schema_version: expected 1")
    changed_files = _nonnegative_int(inputs["changed_files"], "signals.changed_files")
    prior_rejections = _nonnegative_int(
        inputs["prior_review_rejections"], "signals.prior_review_rejections"
    )
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
    complex_rejections_at = _nonnegative_int(
        config["complex_prior_review_rejections_at"],
        "delivery_model_policy.complex_prior_review_rejections_at",
    )
    owner_rejections_at = _nonnegative_int(
        config["owner_gate_prior_review_rejections_at"],
        "delivery_model_policy.owner_gate_prior_review_rejections_at",
    )
    if not 0 < complex_rejections_at < owner_rejections_at:
        raise ContractError("delivery_model_policy: rejection thresholds must increase from 1 or more")
    if complex_files_at < 1:
        raise ContractError("delivery_model_policy.complex_changed_files_at: expected 1 or more")

    reasons: list[str] = []
    owner_matches = sorted(flags & owner_flags)
    if owner_matches:
        reasons.extend(f"flag:{flag}" for flag in owner_matches)
    if prior_rejections >= owner_rejections_at:
        reasons.append(f"prior_review_rejections>={owner_rejections_at}")
    if reasons:
        route_name = "escalated"
    else:
        complex_matches = sorted(flags & complex_flags)
        reasons.extend(f"flag:{flag}" for flag in complex_matches)
        if changed_files >= complex_files_at:
            reasons.append(f"changed_files>={complex_files_at}")
        if prior_rejections >= complex_rejections_at:
            reasons.append(f"prior_review_rejections>={complex_rejections_at}")
        route_name = "complex" if reasons else "standard"
        if not reasons:
            reasons.append("default:standard")

    routes = config["routes"]
    if not isinstance(routes, dict) or set(routes) != {"standard", "complex", "escalated"}:
        raise ContractError("delivery_model_policy.routes: exact standard/complex/escalated routes required")
    standard = _closed_fields(
        routes["standard"], _DELIVERY_STANDARD_ROUTE_FIELDS, "route.standard"
    )
    if not isinstance(standard["standing_approved"], bool):
        raise ContractError("route.standard.standing_approved: boolean required")
    if not standard["standing_approved"]:
        raise ContractError("delivery model policy v1 requires its standard route to be standing-approved")
    if _required_text(standard, "task_class", "route.standard") != "standard_code":
        raise ContractError("route.standard.task_class: expected ADR-028 standard_code")
    if _required_text(standard, "risk", "route.standard") != "medium":
        raise ContractError("route.standard.risk: expected medium")
    for field in ("author_reasoning_effort", "reviewer_reasoning_effort"):
        if _required_text(standard, field, "route.standard") not in _REASONING_EFFORTS:
            raise ContractError(f"route.standard.{field}: invalid value")

    resolved_routes: dict[str, dict[str, Any]] = {}
    for name in ("complex", "escalated"):
        candidate = _closed_fields(routes[name], _DELIVERY_STRONG_ROUTE_FIELDS, f"route.{name}")
        if not isinstance(candidate["standing_approved"], bool):
            raise ContractError(f"route.{name}.standing_approved: boolean required")
        if name != "standard" and candidate["standing_approved"]:
            raise ContractError("delivery model policy v1 never standing-approves stronger routes")
        resolved_candidate = {
            "task_class": _required_text(candidate, "task_class", f"route.{name}"),
            "risk": _required_text(candidate, "risk", f"route.{name}"),
            "author": _delivery_actor(candidate["author"], f"route.{name}.author"),
            "reviewer": _delivery_actor(candidate["reviewer"], f"route.{name}.reviewer"),
        }
        for component in ("author", "reviewer"):
            engine = resolved_candidate[component]["engine"]
            engine_policy = policy.get("engines", {}).get(engine)
            if not isinstance(engine_policy, dict):
                raise ContractError(f"route.{name}.{component}: unknown engine {engine!r}")
            if engine_policy.get("requires_local_permission"):
                raise ContractError(
                    f"route.{name}.{component}: local engines require a separate owner gate"
                )
        if resolved_candidate["author"]["model"] == resolved_candidate["reviewer"]["model"]:
            raise ContractError(f"route.{name}: author and reviewer exact models must differ")
        resolved_routes[name] = {"standing_approved": candidate["standing_approved"], **resolved_candidate}
    quota_sha256 = None
    if route_name == "standard":
        legacy_standard = policy["routes"].get("standard_code")
        if (
            not isinstance(legacy_standard, dict)
            or legacy_standard.get("risk") != "medium"
            or legacy_standard.get("same_provider_fallback") is not True
            or not isinstance(legacy_standard.get("authors"), list)
            or not all(isinstance(item, dict) for item in legacy_standard["authors"])
            or not isinstance(legacy_standard.get("reviewers"), list)
            or not all(isinstance(item, dict) for item in legacy_standard["reviewers"])
        ):
            raise ContractError("policy.routes.standard_code: invalid ADR-028 route")
        if quota is None:
            routed = {
                "status": "review_blocked", "task_class": standard["task_class"],
                "risk": standard["risk"], "author": None, "reviewer": None,
                "review_mode": None, "skipped": {"reviewers": [{"reason": "quota_required"}]},
            }
        else:
            if (
                not isinstance(quota, dict)
                or isinstance(quota.get("schema_version"), bool)
                or quota.get("schema_version") != 1
                or not isinstance(quota.get("engines"), dict)
            ):
                raise ContractError("quota: schema_version 1 and an engines object required")
            for engine in ("codex", "claude"):
                entry = quota["engines"].get(engine)
                if entry is not None and not isinstance(entry, dict):
                    raise ContractError(f"quota.engines.{engine}: expected an object")
                if entry is None:
                    continue
                allowed = {"state", "blocked_until", "reason", "updated_at"}
                if unknown := set(entry) - allowed:
                    raise ContractError(
                        f"quota.engines.{engine}: unknown fields: {', '.join(sorted(unknown))}"
                    )
                state = entry.get("state", "unknown")
                if not isinstance(state, str) or state not in {"available", "quota_blocked", "unknown"}:
                    raise ContractError(f"quota.engines.{engine}.state: invalid state")
                for field in ("reason", "updated_at"):
                    if entry.get(field) is not None and not isinstance(entry[field], str):
                        raise ContractError(f"quota.engines.{engine}.{field}: string or null required")
                blocked_until = entry.get("blocked_until")
                if blocked_until is not None:
                    if not isinstance(blocked_until, str) or not blocked_until:
                        raise ContractError(
                            f"quota.engines.{engine}.blocked_until: timestamp or null required"
                        )
                    try:
                        _parse_time(blocked_until)
                    except ValueError as error:
                        raise ContractError(
                            f"quota.engines.{engine}.blocked_until: invalid timestamp"
                        ) from error
            routed = choose_route(
                policy, quota, standard["task_class"], model_overrides=model_overrides
            )
            quota_sha256 = hashlib.sha256(
                json.dumps(quota, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        if routed["status"] == "ready":
            _exact_model(routed["author"], "route.standard.author")
            _exact_model(routed["reviewer"], "route.standard.reviewer")
            if routed["author"].get("engine") != "codex" or routed["author"].get("model") != "gpt-5.6-luna":
                raise ContractError("route.standard.author: expected Codex Luna")
            expected_reviewer = (
                ("claude", None) if routed["review_mode"] == "cross_family"
                else ("codex", "gpt-5.6-sol")
            )
            if (
                routed["reviewer"].get("engine") != expected_reviewer[0]
                or (
                    expected_reviewer[1] is not None
                    and routed["reviewer"].get("model") != expected_reviewer[1]
                )
            ):
                raise ContractError("route.standard.reviewer: unexpected ADR-028 reviewer")
        if routed["status"] == "ready" and routed["review_mode"] == "same_provider_degraded":
            claude_blocked = any(
                skipped.get("engine") == "claude" and skipped.get("reason") == "quota_blocked"
                for skipped in routed["skipped"].get("reviewers", [])
            )
            if not claude_blocked:
                routed = {
                    **routed, "status": "review_blocked", "author": None, "reviewer": None,
                    "review_mode": None,
                }
        resolved = {
            "standing_approved": standard["standing_approved"],
            "task_class": standard["task_class"],
            "risk": standard["risk"],
            "author": (
                {**routed["author"], "reasoning_effort": standard["author_reasoning_effort"]}
                if routed.get("author") else None
            ),
            "reviewer": (
                {**routed["reviewer"], "reasoning_effort": standard["reviewer_reasoning_effort"]}
                if routed.get("reviewer") else None
            ),
            "review_mode": routed.get("review_mode"),
        }
    else:
        routed = None
        resolved = resolved_routes[route_name]
    canonical_signals = {
        "schema_version": 1,
        "changed_files": changed_files,
        "prior_review_rejections": prior_rejections,
        "flags": sorted(flags),
    }
    policy_sha256 = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    decision = {
        "policy_id": _required_text(config, "policy_id", "delivery_model_policy"),
        "policy_sha256": policy_sha256,
        "route": route_name,
        "task_class": resolved["task_class"],
        "risk": resolved["risk"],
        "reasons": reasons,
        "signals": canonical_signals,
    }
    if quota_sha256 is not None:
        decision["quota_sha256"] = quota_sha256
    decision["decision_id"] = hashlib.sha256(
        json.dumps(
            {**decision, "resolved_route": resolved},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if route_name == "standard":
        if resolved["standing_approved"] and routed and routed["status"] == "ready":
            return {
                "status": "ready", **decision, "author": resolved["author"],
                "reviewer": resolved["reviewer"], "review_mode": resolved["review_mode"],
            }
        return {
            "status": routed["status"] if routed else "review_blocked", **decision,
            "author": None, "reviewer": None, "review_mode": None,
        }
    return {
        "status": "owner_approval_required",
        **decision,
        "author": None,
        "reviewer": None,
        "proposed_route": {"author": resolved["author"], "reviewer": resolved["reviewer"]},
    }


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
    *,
    expected_repo: str,
    current_head: str,
    ci_green: bool,
    allow_same_provider_review: bool = False,
) -> None:
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
    _validate_runtime_attestation(
        summary, author_telemetry, component="author", sandbox="workspace-write"
    )
    _validate_runtime_attestation(
        verification, reviewer_telemetry, component="reviewer", sandbox="read-only"
    )
    same_family = summary.get("engine_family") == verification.get("engine_family")
    review_mode = _required_text(verification, "review_mode", "verification")
    if same_family:
        if not allow_same_provider_review:
            raise ContractError("author and reviewer must use different engine families")
        if summary.get("task_class") != "standard_code":
            raise ContractError("same-provider review is allowed only for standard_code")
        if review_mode != "same_provider_degraded":
            raise ContractError("same-provider review must declare same_provider_degraded")
        if author_model == reviewer_model:
            raise ContractError("same-provider author and reviewer must use different exact models")
        if author_session == reviewer_session:
            raise ContractError("same-provider author and reviewer must use different sessions")
    elif review_mode != "cross_family":
        raise ContractError("cross-family review must declare cross_family")
    changed_files = summary.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files or not all(
        isinstance(item, str) and item for item in changed_files
    ):
        raise ContractError("summary.changed_files: non-empty string list required")
    if not isinstance(verification.get("findings"), list):
        raise ContractError("verification.findings: list required")
    _validate_checks(summary.get("checks"), "summary.checks")
    _validate_checks(verification.get("checks"), "verification.checks")
    cycles = verification.get("review_cycle")
    if not isinstance(cycles, int) or not 1 <= cycles <= 2:
        raise ContractError("verification.review_cycle must be 1 or 2")
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
    if len(session_meta) != 1 or len(turn_context) != 1:
        raise ContractError("rollout must contain exactly one session_meta and one turn_context")
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
    result = {
        "model": actual_model,
        "model_provider": _required_text(meta, "model_provider", "rollout.session_meta"),
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
        raise ContractError(f"remote mismatch: expected {expected_remote}, actual {remote}")
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


def _model_overrides(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        engine, separator, model = value.partition("=")
        if not separator or not engine or not model:
            raise ContractError("--model must be ENGINE=MODEL")
        result[engine] = model
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route")
    route.add_argument("--policy", required=True)
    route.add_argument("--quota", required=True)
    route.add_argument("--task-class", required=True)
    route.add_argument("--allow-local", action="store_true")
    route.add_argument("--allow-unknown", action="store_true")
    route.add_argument("--model", action="append", default=[])

    delivery_route = sub.add_parser("delivery-route")
    delivery_route.add_argument("--policy", required=True)
    delivery_route.add_argument("--signals", required=True)
    delivery_route.add_argument("--quota", required=True)
    delivery_route.add_argument("--model", action="append", default=[])

    quota = sub.add_parser("quota-set")
    quota.add_argument("--file", required=True)
    quota.add_argument("--engine", required=True)
    quota.add_argument("--state", required=True)
    quota.add_argument("--blocked-until")
    quota.add_argument("--reason")

    review = sub.add_parser("validate-review")
    review.add_argument("--summary", required=True)
    review.add_argument("--verification", required=True)
    review.add_argument("--author-telemetry", required=True)
    review.add_argument("--reviewer-telemetry", required=True)
    review.add_argument("--repo", required=True)
    review.add_argument("--head", required=True)
    review.add_argument("--ci-green", action="store_true")
    review.add_argument("--allow-same-provider-review", action="store_true")

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
        if args.command == "route":
            result = choose_route(
                load_json(args.policy), load_json(args.quota), args.task_class,
                allow_local=args.allow_local, allow_unknown=args.allow_unknown,
                model_overrides=_model_overrides(args.model),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ready" else 3
        if args.command == "delivery-route":
            result = choose_delivery_route(
                load_json(args.policy), load_json(args.signals), load_json(args.quota),
                model_overrides=_model_overrides(args.model),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ready" else 3
        if args.command == "quota-set":
            path = pathlib.Path(args.file)
            state = load_json(path) if path.exists() else {"schema_version": 1, "engines": {}}
            write_json(path, set_quota(state, args.engine, args.state, args.blocked_until, args.reason))
            return 0
        if args.command == "validate-review":
            validate_review(
                load_json(args.summary), load_json(args.verification),
                load_json(args.author_telemetry), load_json(args.reviewer_telemetry),
                expected_repo=args.repo,
                current_head=args.head, ci_green=args.ci_green,
                allow_same_provider_review=args.allow_same_provider_review,
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
        print(f"hermes-flow-error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
