#!/usr/bin/env python3
"""Hermes Flow v2 contract: routing, quota state, repo guards and review gates."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
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


def validate_review(
    summary: dict[str, Any],
    verification: dict[str, Any],
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


def summarize_codex_events(
    path: str | pathlib.Path, *, component: str, model: str
) -> dict[str, Any]:
    _exact_model({"model": model}, "telemetry")
    session_id = None
    usage = None
    tool_calls: dict[str, int] = {}
    failed_commands = 0
    timeouts = 0
    non_json_lines = 0
    completed = False
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
            elif event_type == "turn.completed":
                usage = event.get("usage")
                completed = True
    if not isinstance(session_id, str) or not session_id:
        raise ContractError("telemetry: thread.started event missing")
    if not completed:
        raise ContractError("telemetry: turn.completed event missing")
    return {
        "schema_version": 1,
        "component": component,
        "engine": "codex",
        "engine_family": "openai",
        "model": model,
        "session_id": session_id,
        "status": "completed",
        "tool_calls": tool_calls,
        "failed_commands": failed_commands,
        "timeouts": timeouts,
        "retries": None,
        "non_json_lines": non_json_lines,
        "usage": usage,
    }


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

    quota = sub.add_parser("quota-set")
    quota.add_argument("--file", required=True)
    quota.add_argument("--engine", required=True)
    quota.add_argument("--state", required=True)
    quota.add_argument("--blocked-until")
    quota.add_argument("--reason")

    review = sub.add_parser("validate-review")
    review.add_argument("--summary", required=True)
    review.add_argument("--verification", required=True)
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

    telemetry = sub.add_parser("summarize-codex")
    telemetry.add_argument("--events", required=True)
    telemetry.add_argument("--component", required=True)
    telemetry.add_argument("--model", required=True)
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
        if args.command == "quota-set":
            path = pathlib.Path(args.file)
            state = load_json(path) if path.exists() else {"schema_version": 1, "engines": {}}
            write_json(path, set_quota(state, args.engine, args.state, args.blocked_until, args.reason))
            return 0
        if args.command == "validate-review":
            validate_review(
                load_json(args.summary), load_json(args.verification), expected_repo=args.repo,
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
        if args.command == "summarize-codex":
            result = summarize_codex_events(
                args.events, component=args.component, model=args.model
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
