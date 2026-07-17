#!/usr/bin/env python3
"""One-shot, crash-recoverable delivery coordinator for one configured mission profile."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

import flow_contract
import mission_adapter


class DeliveryError(ValueError):
    pass


class InjectedCrash(RuntimeError):
    pass


class CIFailed(DeliveryError):
    def __init__(self, message: str, checks: Any):
        super().__init__(message)
        self.checks = checks


class PostVerifyFailed(DeliveryError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]
_PROFILE_FIELDS = {
    "schema_version", "dispatch_profile", "goal", "repo", "remote",
    "source_checkout", "default_branch", "worktree_root", "branch_prefix",
    "assignee", "route_flags", "required_files",
    "author_checks", "review_checks", "post_verify_checks", "required_ci_checks", "commit_message",
    "pull_request_title", "pull_request_body", "max_review_cycles",
    "claim_ttl_seconds", "command_timeout_seconds", "ci_timeout_seconds",
    "crash_after_author_commit_once", "codex_bin", "gh_bin", "codex_home",
    "post_verify_repair",
}
_REQUIRED_PROFILE_FIELDS = _PROFILE_FIELDS - {
    "route_flags", "codex_bin", "gh_bin", "codex_home", "post_verify_repair",
}
_REJECTION_RESULT = "review_rejected"
_REJECTION_SUMMARY = "Independent review rejected the candidate"
_AUTHOR_CHECKS_RESULT = "author_checks_failed"
_AUTHOR_CHECKS_SUMMARY = "Author checks failed after the approved cycle limit"
_CI_RESULT = "ci_failed"
_CI_SUMMARY = "Required CI failed after the approved cycle limit"
_POST_VERIFY_RESULT = "post_verify_failed"
_POST_VERIFY_SUMMARY = "Post-verify failed after the approved repair mission"
_MAX_CHECK_FAILURE_CHARS = 4000
_COMPLETED_STATE_RETENTION_SECONDS = 30 * 24 * 60 * 60
_DIAGNOSTIC_REDACTIONS = (
    re.compile(r"(?i)\b(?:authorization|proxy-authorization)\s*:\s*[^\r\n]+"),
    re.compile(
        r"(?i)\b[A-Z0-9_.-]*(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|credential)"
        r"[A-Z0-9_.-]*\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    ),
    re.compile(r"(?i)://[^/\s@]+@"),
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{40,}|"
        r"gh[pousr]_[A-Za-z0-9]{36}|tskey-(?:auth|client|api)-[A-Za-z0-9_-]+|"
        r"AGE-" r"SECRET-" r"KEY-[A-Z0-9-]+|[0-9]{8,10}:[A-Za-z0-9_-]{35})\b"
    ),
    re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])"),
)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeliveryError(f"profile.{name}: non-empty string required")
    return value.strip()


def _pr_head_oid(info: dict[str, Any]) -> str | None:
    direct = info.get("headRefOid")
    if isinstance(direct, str) and direct:
        return direct
    commits = info.get("commits")
    if not isinstance(commits, list) or not commits or not isinstance(commits[-1], dict):
        return None
    oid = commits[-1].get("oid")
    return oid if isinstance(oid, str) and oid else None


def load_profile(path: str | pathlib.Path) -> dict[str, Any]:
    profile = mission_adapter._read_json(path)
    if not isinstance(profile, dict) or profile.get("schema_version") != 3:
        raise DeliveryError("profile schema_version must be 3; migrate before activation")
    if unknown := set(profile) - _PROFILE_FIELDS:
        raise DeliveryError(f"unknown profile fields: {', '.join(sorted(unknown))}")
    if missing := _REQUIRED_PROFILE_FIELDS - profile.keys():
        raise DeliveryError(f"missing profile fields: {', '.join(sorted(missing))}")
    for name in (
        "dispatch_profile", "goal", "repo", "remote", "source_checkout",
        "default_branch", "worktree_root", "branch_prefix", "assignee", "commit_message",
        "pull_request_title", "pull_request_body",
    ):
        profile[name] = _required_text(profile.get(name), name)
    route_flags = profile.get("route_flags", [])
    if (
        not isinstance(route_flags, list)
        or not all(isinstance(flag, str) and flag for flag in route_flags)
        or len(route_flags) != len(set(route_flags))
    ):
        raise DeliveryError("profile.route_flags: unique non-empty strings required")
    profile["route_flags"] = sorted(route_flags)
    if not re.fullmatch(r"coordinator-[A-Za-z0-9._-]{1,80}", profile["assignee"]):
        raise DeliveryError("profile.assignee must be a reserved non-routable coordinator identity")
    for name in ("required_files",):
        values = profile.get(name)
        if (
            not isinstance(values, list)
            or not values
            or not all(
                isinstance(item, str)
                and item
                and not pathlib.PurePath(item).is_absolute()
                and ".." not in pathlib.PurePath(item).parts
                for item in values
            )
            or len(values) != len(set(values))
        ):
            raise DeliveryError(f"profile.{name}: unique relative paths required")
    for name in ("author_checks", "review_checks", "post_verify_checks"):
        commands = profile.get(name)
        if (
            not isinstance(commands, list)
            or not commands
            or not all(
                isinstance(command, list)
                and command
                and all(isinstance(argument, str) and argument for argument in command)
                for command in commands
            )
        ):
            raise DeliveryError(f"profile.{name}: non-empty argv arrays required")
    required_ci = profile.get("required_ci_checks")
    if (
        not isinstance(required_ci, list)
        or not required_ci
        or not all(isinstance(name, str) and name.strip() for name in required_ci)
    ):
        raise DeliveryError("profile.required_ci_checks: unique check names required")
    profile["required_ci_checks"] = [name.strip() for name in required_ci]
    if len(profile["required_ci_checks"]) != len(set(profile["required_ci_checks"])):
        raise DeliveryError("profile.required_ci_checks: unique check names required")
    for name in (
        "max_review_cycles", "claim_ttl_seconds", "command_timeout_seconds", "ci_timeout_seconds"
    ):
        value = profile.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise DeliveryError(f"profile.{name}: positive integer required")
    if not 3 <= profile["max_review_cycles"] <= 7:
        raise DeliveryError(
            "profile.max_review_cycles must be between 3 and 7 bounded correction retries"
        )
    if profile["claim_ttl_seconds"] < (
        profile["command_timeout_seconds"] + profile["ci_timeout_seconds"] + 600
    ):
        raise DeliveryError("profile claim TTL has no recovery margin")
    if profile.get("crash_after_author_commit_once") is not True:
        raise DeliveryError("A7.3 profile must enable the approved one-time crash")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}", profile["branch_prefix"])
        or ".." in profile["branch_prefix"]
        or profile["branch_prefix"].endswith("/")
    ):
        raise DeliveryError("profile.branch_prefix is invalid")
    for name in ("source_checkout", "worktree_root"):
        if not pathlib.Path(profile[name]).is_absolute():
            raise DeliveryError(f"profile.{name}: absolute path required")
    profile.setdefault("codex_bin", "/home/uap/.local/bin/codex")
    profile.setdefault("gh_bin", "gh")
    profile.setdefault("codex_home", str(pathlib.Path.home() / ".codex"))
    repair = profile.get("post_verify_repair")
    if repair is not None:
        if not isinstance(repair, dict) or set(repair) != {"dispatch_profile", "goal"}:
            raise DeliveryError(
                "profile.post_verify_repair must contain only dispatch_profile and goal"
            )
        repair = {
            name: _required_text(repair.get(name), f"post_verify_repair.{name}")
            for name in ("dispatch_profile", "goal")
        }
        if repair["dispatch_profile"] == profile["dispatch_profile"]:
            raise DeliveryError("post-verify repair must use a distinct dispatch profile")
        profile["post_verify_repair"] = repair
    return profile


def _private_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = pathlib.Path(handle.name)
    if os.name == "posix":
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    if os.name == "posix":
        os.chmod(path, 0o600)


@contextlib.contextmanager
def _temporary_private_output():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        path = pathlib.Path(handle.name)
    if os.name == "posix":
        os.chmod(path, 0o600)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _private_codex_events(path: pathlib.Path, text: str) -> None:
    lines: list[str] = []
    for raw_line in text.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            lines.append("[REDACTED non-json Codex event]")
            continue
        if not isinstance(event, dict):
            lines.append("[REDACTED invalid Codex event]")
            continue
        containers = [event]
        if isinstance(event.get("item"), dict):
            containers.append(event["item"])
        for container in containers:
            for field in ("aggregated_output", "command", "message", "output", "text"):
                if isinstance(container.get(field), str):
                    container[field] = _bounded_diagnostic(container[field])
        lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    _private_text(path, "\n".join(lines) + ("\n" if lines else ""))


def _redact_diagnostic(value: str) -> str:
    value = value.replace("\x00", "?")
    for pattern in _DIAGNOSTIC_REDACTIONS:
        value = pattern.sub("[REDACTED]", value)
    return value


def _bounded_diagnostic(value: str, default: str = "") -> str:
    value = _redact_diagnostic(value).strip()
    return value[-_MAX_CHECK_FAILURE_CHARS:] if value else default


def _sanitize_findings(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DeliveryError("delivery diagnostics must be a string array")
    return [_bounded_diagnostic(item) for item in value[:16] if item.strip()]


def _command_failure(result: subprocess.CompletedProcess[str], command: list[str]) -> str:
    streams = [
        f"{name}:\n{_redact_diagnostic(text).strip()}"
        for name, text in (("stderr", result.stderr), ("stdout", result.stdout))
        if text and text.strip()
    ]
    if not streams:
        return "command failed without diagnostic output"
    separators = len(streams) - 1
    budget = (_MAX_CHECK_FAILURE_CHARS - separators) // len(streams)
    marker = "\n...[truncated]...\n"
    bounded = []
    for item in streams:
        if len(item) > budget:
            head = (budget - len(marker)) // 2
            item = item[:head] + marker + item[-(budget - len(marker) - head):]
        bounded.append(item)
    return "\n".join(bounded)


def _ci_decision(checks: Any, required: list[str]) -> str:
    """Return pending/passed/failed for one exact PR check rollup."""
    if not isinstance(checks, list) or not checks:
        return "pending"
    pending = {
        None, "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "REQUESTED", "WAITING",
    }
    passing = {"SUCCESS", "NEUTRAL", "SKIPPED"}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in checks:
        if not isinstance(item, dict):
            return "failed"
        name = item.get("name") or item.get("context")
        if isinstance(name, str):
            by_name.setdefault(name, []).append(item)
        outcome = item.get("conclusion") or item.get("state") or item.get("status")
        if outcome not in pending | passing:
            return "failed"
    for name in required:
        matches = by_name.get(name, [])
        if not matches:
            return "pending"
        if len(matches) != 1:
            return "failed"
        outcome = (
            matches[0].get("conclusion")
            or matches[0].get("state")
            or matches[0].get("status")
        )
        if outcome in pending:
            return "pending"
        if outcome != "SUCCESS":
            return "failed"
    if any(
        (item.get("conclusion") or item.get("state") or item.get("status")) in pending
        for item in checks
    ):
        return "pending"
    return "passed"


def _ci_summaries(checks: Any) -> list[dict[str, str]]:
    summaries = []
    for item in checks[:50] if isinstance(checks, list) else []:
        if not isinstance(item, dict):
            continue
        summaries.append({
            "name": str(item.get("name") or item.get("context") or "unknown")[:200],
            "outcome": str(
                item.get("conclusion") or item.get("state") or item.get("status") or "unknown"
            )[:100],
        })
    return summaries


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(path, "a+b")
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt

            handle.seek(0)
            if handle.tell() == handle.seek(0, os.SEEK_END):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except (BlockingIOError, OSError) as error:
        handle.close()
        raise DeliveryError("delivery coordinator is already running") from error
    try:
        yield
    finally:
        handle.close()


class DeliveryCoordinator:
    def __init__(
        self,
        profile: dict[str, Any],
        client: Any,
        backend: Any,
        state_root: pathlib.Path,
        *,
        runner: Runner = subprocess.run,
        policy: dict[str, Any] | None = None,
    ):
        self.profile = {**profile, "route_flags": sorted(profile.get("route_flags", []))}
        self.client = client
        self.backend = backend
        self.state_root = state_root
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.state_root, 0o700)
        self.runner = runner
        self.policy = policy or flow_contract.load_json(
            pathlib.Path(__file__).with_name("flow-policy.json")
        )

    def _safe_env(self) -> dict[str, str]:
        allowed = {
            "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TERM", "TMPDIR",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
        }
        environment = {name: value for name, value in os.environ.items() if name in allowed}
        environment["CODEX_HOME"] = self.profile["codex_home"]
        return environment

    def _run(
        self,
        command: list[str],
        *,
        cwd: pathlib.Path | None = None,
        input_text: str | None = None,
        timeout: int | None = None,
        check: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = self.runner(
            command,
            cwd=None if cwd is None else str(cwd),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout or self.profile["command_timeout_seconds"],
            env=environment or self._safe_env(),
        )
        if check and result.returncode:
            raise DeliveryError(_command_failure(result, command))
        return result

    def _model_env(self, paths: dict[str, pathlib.Path]) -> dict[str, str]:
        home = paths["directory"] / "model-home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(home, 0o700)
        environment = self._safe_env()
        environment.update(
            HOME=str(home),
            XDG_CONFIG_HOME=str(home / ".config"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
        )
        return environment

    def _route_signals(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "changed_files": len(self.profile["required_files"]),
            "prior_quality_failures": self._quality_failures(state),
            "flags": self.profile["route_flags"],
        }

    @staticmethod
    def _quality_failures(state: dict[str, Any]) -> int:
        values = [
            state.get("prior_author_failures", 0),
            state.get("prior_review_rejections", 0),
            state.get("prior_ci_failures", 0),
        ]
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise DeliveryError("durable quality-failure counters are invalid")
        return sum(values)

    def _ensure_route(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> dict[str, Any]:
        decision = flow_contract.choose_delivery_route(
            self.policy, self._route_signals(state)
        )
        if decision.get("status") != "ready":
            raise DeliveryError("mission requires a capability outside the configured OpenAI policy")
        key = str(self._quality_failures(state))
        decisions = state.setdefault("route_decisions", {})
        if key in decisions:
            recovered = flow_contract.validate_stored_delivery_route(
                self.policy, decisions[key]
            )
            if recovered != decision:
                raise DeliveryError("routing policy changed during a durable mission cycle")
            return decisions[key]
        decisions[key] = decision
        self._save(paths, state)
        return decision

    def _current_route(self, state: dict[str, Any]) -> dict[str, Any]:
        key = str(self._quality_failures(state))
        decision = state.get("route_decisions", {}).get(key)
        if not isinstance(decision, dict) or decision.get("status") != "ready":
            raise DeliveryError("durable OpenAI route decision is missing")
        return decision

    def _actor(self, state: dict[str, Any], component: str) -> dict[str, str]:
        actor = self._current_route(state).get(component)
        if not isinstance(actor, dict):
            raise DeliveryError(f"route has no {component} actor")
        return actor

    def _reasoning_args(self, state: dict[str, Any], component: str) -> list[str]:
        effort = self._actor(state, component)["reasoning_effort"]
        return ["--strict-config", "-c", f'model_reasoning_effort="{effort}"']

    def _git(self, checkout: pathlib.Path, *arguments: str, check: bool = True) -> str:
        return self._run(["git", "-C", str(checkout), *arguments], check=check).stdout.strip()

    def _mission(self) -> dict[str, Any] | None:
        queued = self.client.list_missions(self.profile["dispatch_profile"])
        active = self.client.list_missions(self.profile["dispatch_profile"], reconcile=True)
        missions = {item.get("mission_id"): item for item in [*queued, *active]}
        missions.pop(None, None)
        if len(missions) > 1:
            raise DeliveryError("profile matched more than one active mission")
        mission = next(iter(missions.values()), None)
        if mission is None:
            recoverable = []
            for path in self.state_root.glob("mission-*/delivery-state.json"):
                state = mission_adapter._read_json(path)
                if (
                    isinstance(state, dict)
                    and state.get("dispatch_profile") == self.profile["dispatch_profile"]
                    and state.get("phase") != "complete"
                ):
                    recoverable.append(state)
            if len(recoverable) > 1:
                raise DeliveryError("profile has more than one recoverable delivery state")
            if recoverable:
                mission = self.client.get_mission(recoverable[0]["mission_id"])
        if mission is not None and mission.get("goal") != self.profile["goal"]:
            raise DeliveryError("mission goal does not match the owner-approved profile")
        if (
            mission is not None
            and mission.get("parent_mission_id") is not None
            and self.profile.get("post_verify_repair") is not None
        ):
            raise DeliveryError("repair missions cannot recursively dispatch another repair")
        return mission

    def _paths(self, mission_id: str) -> dict[str, pathlib.Path]:
        directory = mission_adapter._mission_dir(self.state_root, mission_id)
        digest = hashlib.sha256(mission_id.encode()).hexdigest()[:12]
        root = pathlib.Path(self.profile["worktree_root"])
        return {
            "directory": directory,
            "state": directory / "delivery-state.json",
            "lock": directory / "delivery.lock",
            "author": root / f"author-{digest}",
            "review": root / f"review-{digest}",
            "verify": root / f"verify-{digest}",
            "repair_context": directory / "post-verify-repair.json",
        }

    @staticmethod
    def _owner_answers(state: dict[str, Any]) -> list[dict[str, str]]:
        answers = state.get("owner_answers", [])
        if not isinstance(answers, list) or len(answers) > 8:
            raise DeliveryError("durable owner-answer history is invalid")
        validated = []
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) != {
                "question_id", "text", "sha256"
            }:
                raise DeliveryError("durable owner-answer checkpoint is invalid")
            question_id, text, digest = (
                answer.get("question_id"), answer.get("text"), answer.get("sha256")
            )
            if (
                not isinstance(question_id, str)
                or not question_id
                or len(question_id) > 128
                or not isinstance(text, str)
                or not text
                or len(text) > 4096
                or not isinstance(digest, str)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest
            ):
                raise DeliveryError("durable owner-answer checkpoint is invalid")
            validated.append(dict(answer))
        return validated

    def _load_state(self, mission_id: str, paths: dict[str, pathlib.Path]) -> dict[str, Any]:
        if paths["state"].is_file():
            state = mission_adapter._read_json(paths["state"])
            if (
                not isinstance(state, dict)
                or state.get("mission_id") != mission_id
                or state.get("dispatch_profile") != self.profile["dispatch_profile"]
            ):
                raise DeliveryError("delivery state identity mismatch")
            state.setdefault("prior_review_rejections", 0)
            state.setdefault("prior_ci_failures", 0)
            state.setdefault("prior_author_failures", 0)
            state.setdefault("route_decisions", {})
            state.setdefault("owner_answers", [])
            self._owner_answers(state)
            migrated = False
            if "review_findings" in state:
                findings = _sanitize_findings(state["review_findings"])
                if findings != state["review_findings"]:
                    state["review_findings"] = findings
                    migrated = True
            if isinstance(state.get("failure_error"), str):
                failure = _bounded_diagnostic(state["failure_error"])
                if failure != state["failure_error"]:
                    state["failure_error"] = failure
                    migrated = True
            if state.get("pr_number") is not None and "pr_base_branch" not in state:
                state["pr_base_branch"] = self.profile["default_branch"]
                migrated = True
            if (
                state.get("pr_number") is not None
                and state.get("phase") in {"pr_open", "ci_green"}
                and "pr_head_sha" not in state
            ):
                candidate = state.get("candidate_sha")
                if not isinstance(candidate, str) or not candidate:
                    raise DeliveryError("legacy PR state has no candidate identity")
                state["pr_head_sha"] = candidate
                migrated = True
            if migrated:
                self._save(paths, state)
            return state
        digest = hashlib.sha256(mission_id.encode()).hexdigest()[:12]
        state = {
            "schema_version": 1,
            "mission_id": mission_id,
            "dispatch_profile": self.profile["dispatch_profile"],
            "phase": "new",
            "branch": f"{self.profile['branch_prefix']}-{digest}",
            "review_cycle": 1,
            "prior_review_rejections": 0,
            "prior_ci_failures": 0,
            "prior_author_failures": 0,
            "route_decisions": {},
            "owner_answers": [],
            "crash_injected": False,
        }
        if paths["repair_context"].is_file():
            context = mission_adapter._read_json(paths["repair_context"])
            expected = {
                "schema_version", "mission_id", "parent_mission_id",
                "dispatch_profile", "diagnostic", "failed_default_sha",
            }
            if (
                not isinstance(context, dict)
                or set(context) != expected
                or context.get("schema_version") != 1
                or context.get("mission_id") != mission_id
                or context.get("dispatch_profile") != self.profile["dispatch_profile"]
                or not isinstance(context.get("parent_mission_id"), str)
                or not isinstance(context.get("failed_default_sha"), str)
            ):
                raise DeliveryError("post-verify repair context is invalid")
            diagnostic = _bounded_diagnostic(
                str(context.get("diagnostic") or ""), "post-verify failed"
            )
            state.update(
                parent_mission_id=context["parent_mission_id"],
                repair_failed_default_sha=context["failed_default_sha"],
                review_findings=[diagnostic],
            )
        return state

    def _save(self, paths: dict[str, pathlib.Path], state: dict[str, Any]) -> None:
        mission_adapter._write_json(paths["state"], state, private_parent=True)

    def _wait_for_owner(
        self,
        state: dict[str, Any],
        mission: dict[str, Any],
        paths: dict[str, pathlib.Path],
    ) -> dict[str, Any]:
        question = mission.get("question")
        if (
            state.get("phase") not in {"new", "waiting_owner"}
            or not isinstance(question, dict)
            or set(question) != {"question_id", "text"}
            or not isinstance(question.get("question_id"), str)
            or not question["question_id"]
            or not isinstance(question.get("text"), str)
            or not question["text"]
        ):
            raise DeliveryError("owner question is outside the pre-execution checkpoint")
        tasks = mission.get("tasks")
        if not isinstance(tasks, list):
            raise DeliveryError("owner question has an invalid task projection")
        if not tasks:
            raise DeliveryError("owner question requires the inert pre-execution Kanban root")
        adapter_state = mission_adapter.recover_mission_state(
            mission["mission_id"], self.state_root, self.backend
        )
        projected = {
            task.get("task_id") for task in tasks if isinstance(task, dict)
        }
        if adapter_state["root_task_id"] not in projected:
            raise DeliveryError("owner question does not reference the exact Kanban root")
        snapshot = self.backend.show(adapter_state["root_task_id"])
        task = snapshot.get("task")
        sticky = mission_adapter._latest_sticky_event(snapshot.get("events"))
        if (
            not isinstance(task, dict)
            or task.get("status") != "blocked"
            or task.get("assignee") is not None
            or snapshot.get("runs") != []
            or sticky is None
            or sticky.get("kind") != "blocked"
        ):
            raise DeliveryError("owner question root is not inert and sticky-blocked")
        state.update(
            phase="waiting_owner",
            root_task_id=adapter_state["root_task_id"],
            owner_question={
                "question_id": question["question_id"],
                "text": _bounded_diagnostic(question["text"]),
            },
        )
        self._save(paths, state)
        return {
            "action": "waiting_owner",
            "mission_id": mission["mission_id"],
            "state": state,
        }

    def _resume_owner_answer(
        self,
        state: dict[str, Any],
        mission: dict[str, Any],
        paths: dict[str, pathlib.Path],
    ) -> None:
        if state.get("phase") not in {"new", "waiting_owner", "owner_answer_pending"}:
            raise DeliveryError("owner answer arrived after execution started")
        answer = mission.get("answer")
        if (
            not isinstance(answer, dict)
            or set(answer) != {"question_id", "text"}
            or not isinstance(answer.get("question_id"), str)
            or not answer["question_id"]
            or not isinstance(answer.get("text"), str)
            or not answer["text"]
        ):
            raise DeliveryError("owner answer projection is invalid")
        previous = state.get("owner_question")
        if isinstance(previous, dict) and previous.get("question_id") != answer["question_id"]:
            raise DeliveryError("owner answer does not match the durable question")
        text = _bounded_diagnostic(answer["text"])
        entry = {
            "question_id": answer["question_id"],
            "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        answers = self._owner_answers(state)
        matches = [item for item in answers if item["question_id"] == entry["question_id"]]
        if matches and matches != [entry]:
            raise DeliveryError("owner answer changed after its durable checkpoint")
        if not matches:
            if len(answers) == 8:
                raise DeliveryError("owner-answer history limit reached")
            answers.append(entry)
        adapter_state = mission_adapter.recover_mission_state(
            mission["mission_id"], self.state_root, self.backend
        )
        tasks = mission.get("tasks")
        if (
            not isinstance(tasks, list)
            or adapter_state["root_task_id"] not in {
                task.get("task_id") for task in tasks if isinstance(task, dict)
            }
        ):
            raise DeliveryError("owner answer does not reference the exact Kanban root")
        state.update(
            phase="owner_answer_pending",
            root_task_id=adapter_state["root_task_id"],
            owner_answers=answers,
        )
        self._save(paths, state)
        self._assert_nonroutable_assignee()
        self.backend.resume_root_from_answer(
            state["root_task_id"],
            assignee=self.profile["assignee"],
            workspace=f"worktree:{paths['author']}",
            question_id=entry["question_id"],
            answer_digest=entry["sha256"],
        )
        state["phase"] = "new"
        state.pop("owner_question", None)
        self._save(paths, state)

    def _ensure_worktree(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> None:
        source = pathlib.Path(self.profile["source_checkout"])
        author = paths["author"]
        self._git(source, "fetch", "--prune", "origin", self.profile["default_branch"])
        if not author.is_dir():
            author.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                source,
                "worktree", "add", "-b", state["branch"], str(author),
                f"origin/{self.profile['default_branch']}",
            )
        flow_contract.guard_repo(author, self.profile["remote"], state["branch"])
        if "base_sha" not in state:
            state["base_sha"] = self._git(author, "rev-parse", "HEAD")
        elif self._run(
            ["git", "-C", str(author), "merge-base", "--is-ancestor", state["base_sha"], "HEAD"],
            check=False,
        ).returncode:
            raise DeliveryError("author worktree no longer descends from the recorded base")

    def _publish_stage(self, state: dict[str, Any], stage: str, progress: int) -> None:
        self._assert_claim(state)
        event = mission_adapter._producer_event(
            state["mission_id"],
            "mission.stage",
            {"stage": stage, "progress_percent": progress},
            {"task_id": state["root_task_id"]},
        )
        self.client.publish(state["mission_id"], event)

    def _reconcile(
        self,
        *,
        before_publish: Callable[[str, dict[str, Any]], None] | None = None,
        event_source: Callable[[str, dict[str, Any]], list[dict[str, Any]]] | None = None,
    ) -> None:
        mission_adapter.reconcile_pending(
            self.client,
            self.state_root,
            self.backend,
            dispatch_profile=self.profile["dispatch_profile"],
            before_publish=before_publish,
            event_source=event_source,
        )

    def _reconcile_active(self, state: dict[str, Any]) -> None:
        """Publish active execution state only while this run still owns the task."""
        self._reconcile(
            before_publish=lambda _mission_id, _event: self._assert_claim(state)
        )

    def _reconcile_completed(self, state: dict[str, Any]) -> None:
        """Publish final state from the exact durable Kanban completion record."""
        if state.get("phase") != "task_completed":
            raise DeliveryError("final reconciliation lacks durable Kanban completion authority")
        self._reconcile(
            before_publish=lambda _mission_id, _event: self._require_task_completion(state),
            event_source=lambda mission_id, adapter_state: self._completed_events(
                mission_id, adapter_state, state
            ),
        )

    def _ensure_claimed(self, state: dict[str, Any]) -> None:
        snapshot = self.backend.show(state["root_task_id"])
        task = snapshot.get("task", {})
        runs = snapshot.get("runs")
        if task.get("assignee") != self.profile["assignee"] or not isinstance(runs, list):
            raise DeliveryError("Kanban task is outside the approved assignee/run contract")
        if task.get("status") == "ready" and not runs:
            snapshot = self.backend.claim(
                state["root_task_id"], ttl_seconds=self.profile["claim_ttl_seconds"]
            )
            task = snapshot.get("task", {})
            runs = snapshot["runs"]
        if (
            task.get("status") != "running"
            or len(runs) != 1
            or runs[0].get("status") != "running"
        ):
            raise DeliveryError("Kanban task did not converge to one claimed run")
        state["run_id"] = str(runs[0]["id"])
        self._assert_claim(state)

    def _assert_claim(self, state: dict[str, Any], *, min_remaining_seconds: int = 60) -> None:
        task_id = state.get("root_task_id")
        run_id = state.get("run_id")
        if not isinstance(task_id, str) or not task_id or run_id is None:
            raise DeliveryError("delivery has no durable Kanban task/run identity")
        self.backend.verify_claim(
            task_id,
            str(run_id),
            min_remaining_seconds=min_remaining_seconds,
        )

    def _assert_nonroutable_assignee(self) -> None:
        hermes_home = pathlib.Path(
            os.environ.get("HERMES_HOME", str(pathlib.Path.home() / ".hermes"))
        ).expanduser()
        if (hermes_home / "profiles" / self.profile["assignee"]).is_dir():
            raise DeliveryError("reserved coordinator assignee resolves to a Hermes worker profile")

    def _validate_task_completion_snapshot(
        self, state: dict[str, Any], snapshot: dict[str, Any]
    ) -> bool:
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        if not isinstance(task, dict) or not isinstance(runs, list):
            raise DeliveryError("Kanban completion snapshot is invalid")
        if task.get("status") == "running":
            return False
        matching = [run for run in runs if str(run.get("id")) == str(state["run_id"])]
        expected_metadata = {"mission_events": self._events(state, cleanup=True)}
        if (
            task.get("status") not in {"done", "archived"}
            or task.get("result") != "success"
            or len(matching) != 1
            or matching[0].get("status") not in {"done", "completed"}
            or matching[0].get("outcome") != "completed"
            or matching[0].get("summary") != "Reviewed change merged, verified, and cleaned"
            or matching[0].get("metadata") != expected_metadata
        ):
            raise DeliveryError("Kanban task ended outside the approved completion contract")
        return True

    def _task_completion_persisted(self, state: dict[str, Any]) -> bool:
        return self._validate_task_completion_snapshot(
            state, self.backend.show(state["root_task_id"])
        )

    def _require_task_completion(self, state: dict[str, Any]) -> None:
        if not self._task_completion_persisted(state):
            raise DeliveryError("durable Kanban completion disappeared before publication")

    def _completed_events(
        self,
        mission_id: str,
        adapter_state: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        task_id = state["root_task_id"]
        if adapter_state.get("root_task_id") != task_id:
            raise DeliveryError("final reconciliation selected the wrong Kanban root")
        snapshot = self.backend.show(task_id)
        self._validate_task_completion_snapshot(state, snapshot)
        log_text = self.backend.read_log(task_id)
        self._require_task_completion(state)
        return mission_adapter.project_task_snapshot(
            mission_id, task_id, snapshot, log_text
        )

    def _recover_task_completion(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> bool:
        if not self._task_completion_persisted(state):
            return False
        state["phase"] = "task_completed"
        self._save(paths, state)
        self._reconcile_completed(state)
        return True

    def _failure_contract(
        self, state: dict[str, Any]
    ) -> tuple[str, str, list[dict[str, Any]]]:
        def finish(
            result: str, summary: str, events: list[dict[str, Any]]
        ) -> tuple[str, str, list[dict[str, Any]]]:
            pr_url = state.get("pr_url")
            if isinstance(pr_url, str) and pr_url:
                events.insert(-1, {
                    "type": "delivery.upsert",
                    "payload": {"kind": "pull_request", "status": "failed", "url": pr_url},
                })
            return result, summary, events

        if state.get("failure_kind") == "post_verify":
            pr_url = state.get("pr_url")
            if not isinstance(pr_url, str) or not pr_url:
                raise DeliveryError("post-verify failure has no merged PR identity")
            return (
                _POST_VERIFY_RESULT,
                _POST_VERIFY_SUMMARY,
                [
                    {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "passed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "review", "status": "passed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "ci", "status": "passed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "post-verify", "status": "failed"}},
                    {"type": "delivery.upsert", "payload": {
                        "kind": "pull_request", "status": "merged", "url": pr_url,
                    }},
                    {"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}},
                ],
            )
        if state.get("failure_kind") == "ci":
            return finish(
                _CI_RESULT,
                _CI_SUMMARY,
                [
                    {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "passed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "review", "status": "passed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "ci", "status": "failed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}},
                ],
            )
        if state.get("failure_kind") == "author_checks":
            return finish(
                _AUTHOR_CHECKS_RESULT,
                _AUTHOR_CHECKS_SUMMARY,
                [
                    {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "failed"}},
                    {"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}},
                ],
            )
        return finish(
            _REJECTION_RESULT,
            _REJECTION_SUMMARY,
            [
                {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "passed"}},
                {"type": "gate.upsert", "payload": {"gate_id": "review", "status": "failed"}},
                {"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}},
            ],
        )

    def _rejection_events(self) -> list[dict[str, Any]]:
        return self._failure_contract({})[2]

    def _validate_rejection_snapshot(
        self, state: dict[str, Any], snapshot: dict[str, Any]
    ) -> bool:
        result, summary, events = self._failure_contract(state)
        task = snapshot.get("task")
        runs = snapshot.get("runs")
        if not isinstance(task, dict) or not isinstance(runs, list):
            raise DeliveryError("Kanban rejection snapshot is invalid")
        if task.get("status") == "running":
            return False
        matching = [run for run in runs if str(run.get("id")) == str(state["run_id"])]
        if (
            task.get("status") not in {"done", "archived"}
            or task.get("result") != result
            or len(matching) != 1
            or matching[0].get("status") not in {"done", "completed"}
            or matching[0].get("outcome") != "completed"
            or matching[0].get("summary") != summary
            or matching[0].get("metadata") != {"mission_events": events}
        ):
            raise DeliveryError("Kanban task ended outside the approved rejection contract")
        return True

    def _rejection_persisted(self, state: dict[str, Any]) -> bool:
        return self._validate_rejection_snapshot(
            state, self.backend.show(state["root_task_id"])
        )

    def _require_rejection_completion(self, state: dict[str, Any]) -> None:
        if not self._rejection_persisted(state):
            raise DeliveryError("durable Kanban rejection disappeared before publication")

    def _rejected_events(
        self,
        mission_id: str,
        adapter_state: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        task_id = state["root_task_id"]
        if adapter_state.get("root_task_id") != task_id:
            raise DeliveryError("rejection reconciliation selected the wrong Kanban root")
        snapshot = self.backend.show(task_id)
        self._validate_rejection_snapshot(state, snapshot)
        return mission_adapter.project_task_snapshot(
            mission_id, task_id, snapshot, self.backend.read_log(task_id)
        )

    def _reconcile_rejected(self, state: dict[str, Any]) -> None:
        if state.get("phase") != "rejection_task_completed":
            raise DeliveryError("rejection reconciliation lacks durable Kanban authority")
        self._reconcile(
            before_publish=lambda _mission_id, _event: self._require_rejection_completion(state),
            event_source=lambda mission_id, adapter_state: self._rejected_events(
                mission_id, adapter_state, state
            ),
        )

    def _recover_rejection_completion(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> bool:
        if not self._rejection_persisted(state):
            return False
        state["phase"] = "rejection_task_completed"
        self._save(paths, state)
        self._reconcile_rejected(state)
        return True

    def _finish_rejection(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> dict[str, Any]:
        result, summary, events = self._failure_contract(state)
        if state["phase"] in {
            "review_rejected", "author_checks_failed", "ci_failed", "post_verify_failed"
        }:
            preserve_remote = False
            if state.get("pr_number") is not None and state.get("failure_kind") != "post_verify":
                preserve_remote = self._finalize_failed_pr(state)
            self._cleanup(state, paths, preserve_remote=preserve_remote)
            state["failed_pr_preserved"] = preserve_remote
            state["phase"] = "rejection_cleaned"
            self._save(paths, state)
        if state["phase"] == "rejection_cleaned":
            if not self._recover_rejection_completion(state, paths):
                self._assert_claim(state)
                self.backend.complete(
                    state["root_task_id"],
                    result=result,
                    summary=summary,
                    metadata={"mission_events": events},
                )
                if not self._recover_rejection_completion(state, paths):
                    raise DeliveryError("Kanban rejection did not reach terminal state")
        if state["phase"] == "rejection_task_completed":
            self._reconcile_rejected(state)
            if self.client.get_mission(state["mission_id"]).get("status") != "failed":
                raise DeliveryError("Central did not fail the rejected mission")
            self._archive_task(state, paths)
            state.update(phase="complete", outcome=result)
            self._save(paths, state)
        return {"action": state["phase"], "mission_id": state["mission_id"], "state": state}

    def _expand(self, command: list[str], state: dict[str, Any], paths: dict[str, pathlib.Path]) -> list[str]:
        values = {
            "worktree": str(paths["author"]),
            "verify_worktree": str(paths["verify"]),
            "candidate_sha": str(state.get("candidate_sha", "")),
            "default_sha": str(state.get("default_sha", "")),
            "mission_id": state["mission_id"],
            "pr_url": str(state.get("pr_url", "")),
        }
        return [argument.format_map(values) for argument in command]

    def _checks(
        self,
        name: str,
        checkout: pathlib.Path,
        state: dict[str, Any],
        paths: dict[str, pathlib.Path],
    ) -> list[dict[str, Any]]:
        records = []
        for command in self.profile[name]:
            expanded = self._expand(command, state, paths)
            self._run(expanded, cwd=checkout)
            records.append({"command": shlex.join(expanded), "exit_code": 0})
        return records

    def _changed_files(self, checkout: pathlib.Path) -> set[str]:
        result = self._run(
            ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=all"]
        )
        return {
            line[3:].split(" -> ")[-1]
            for line in result.stdout.splitlines()
            if len(line) > 3
        }

    def _candidate_fingerprint(self, checkout: pathlib.Path) -> str:
        digest = hashlib.sha256()
        diff = self._run(
            ["git", "-C", str(checkout), "diff", "--binary", "--no-ext-diff", "HEAD", "--"]
        ).stdout
        digest.update(diff.encode("utf-8"))
        untracked = self._run(
            ["git", "-C", str(checkout), "ls-files", "--others", "--exclude-standard", "-z"]
        ).stdout
        for relative in sorted(item for item in untracked.split("\0") if item):
            path = checkout / relative
            digest.update(relative.encode("utf-8"))
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8"))
            elif path.is_file():
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"missing")
        return digest.hexdigest()

    def _rollout(self, events_path: pathlib.Path) -> pathlib.Path:
        session_id = None
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id")
                break
        if not isinstance(session_id, str) or not session_id:
            raise DeliveryError("Codex stream has no thread.started session")
        matches = list(pathlib.Path(self.profile["codex_home"]).glob(f"sessions/**/rollout-*{session_id}.jsonl"))
        if len(matches) != 1:
            raise DeliveryError("exact Codex rollout could not be located")
        return matches[0]

    def _record_author(
        self,
        state: dict[str, Any],
        paths: dict[str, pathlib.Path],
        checks: list[dict[str, Any]],
    ) -> None:
        cycle = state["review_cycle"]
        route = self._current_route(state)
        actor = route["author"]
        events = paths["directory"] / f"author-{cycle}.jsonl"
        candidate = self._git(paths["author"], "rev-parse", "HEAD")
        cumulative = set(
            self._git(
                paths["author"], "diff", "--name-only", f"{state['base_sha']}..{candidate}"
            ).splitlines()
        )
        if cumulative != set(self.profile["required_files"]):
            raise DeliveryError("candidate does not contain the exact approved file set")
        rollout = self._rollout(events)
        telemetry = flow_contract.summarize_codex_events(
            events,
            component="author",
            model=actor["model"],
            reasoning_effort=actor["reasoning_effort"],
            rollout=rollout,
            sandbox="workspace-write",
            worktree=paths["author"],
            head=candidate,
        )
        summary = {
            "schema_version": 1,
            "repo": self.profile["repo"],
            "branch": state["branch"],
            "head_sha": candidate,
            "task_class": route["task_class"],
            "route_decision_id": route["decision_id"],
            "engine_family": "openai",
            "model": telemetry["model"],
            "reasoning_effort": telemetry.get("reasoning_effort"),
            "session_id": telemetry["session_id"],
            "changed_files": sorted(cumulative),
            "checks": checks,
        }
        mission_adapter._write_json(
            paths["directory"] / "author-summary.json", summary, private_parent=True
        )
        mission_adapter._write_json(
            paths["directory"] / "author-telemetry.json", telemetry, private_parent=True
        )
        state.update(
            phase="author_committed",
            candidate_sha=candidate,
            author_summary=summary,
            author_telemetry=telemetry,
        )
        state.pop("review_findings", None)
        self._save(paths, state)

    def _recover_author_commit(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> bool:
        """Checkpoint an already committed author turn without starting another model."""
        changed = self._changed_files(paths["author"])
        if changed:
            fingerprint = self._candidate_fingerprint(paths["author"])
            cycle = state["review_cycle"]
            events = paths["directory"] / f"author-{cycle}.jsonl"
            if not changed <= set(self.profile["required_files"]):
                raise DeliveryError("uncheckpointed author worktree escaped the exact allowlist")
            if state["phase"] == "needs_fix" and not events.is_file():
                return False
            if not events.is_file():
                raise DeliveryError("uncheckpointed author worktree is unsafe; refusing a second model")
            try:
                checks = self._checks("author_checks", paths["author"], state, paths)
            except DeliveryError as error:
                preserved = self._candidate_fingerprint(paths["author"]) == fingerprint
                if not preserved:
                    error = DeliveryError("author checks mutated the exact candidate")
                self._record_author_check_failure(state, paths, error, retryable=preserved)
                return True
            if self._candidate_fingerprint(paths["author"]) != fingerprint:
                raise DeliveryError("author recovery checks changed the exact candidate")
            self._git(paths["author"], "add", "--", *sorted(changed))
            self._assert_claim(state)
            self._git(paths["author"], "commit", "-m", self.profile["commit_message"])
            self._record_author(state, paths, checks)
            return True
        count_text = self._git(
            paths["author"], "rev-list", "--count", f"{state['base_sha']}..HEAD"
        )
        try:
            count = int(count_text)
        except ValueError as error:
            raise DeliveryError("invalid author commit count") from error
        cycle = state["review_cycle"]
        if count == cycle - 1:
            return False
        if count != cycle:
            raise DeliveryError("author history escaped the one-commit-per-cycle contract")
        events = paths["directory"] / f"author-{cycle}.jsonl"
        if not events.is_file():
            raise DeliveryError("author commit exists without its durable runtime event stream")
        checks = self._checks("author_checks", paths["author"], state, paths)
        if self._changed_files(paths["author"]):
            raise DeliveryError("author recovery checks changed the exact candidate")
        self._assert_claim(state)
        self._record_author(state, paths, checks)
        return True

    def _record_author_check_failure(
        self,
        state: dict[str, Any],
        paths: dict[str, pathlib.Path],
        error: DeliveryError,
        *,
        retryable: bool = True,
    ) -> None:
        failure = _bounded_diagnostic(str(error), "author checks failed")
        self._quality_failures(state)
        state["prior_author_failures"] = state.get("prior_author_failures", 0) + 1
        if retryable and state["review_cycle"] <= self.profile["max_review_cycles"]:
            state.update(
                phase="needs_fix",
                review_cycle=state["review_cycle"] + 1,
                review_findings=[failure],
            )
        else:
            state.update(
                phase="author_checks_failed",
                failure_kind="author_checks",
                failure_error=failure,
            )
        self._save(paths, state)

    def _author(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> None:
        cycle = state["review_cycle"]
        actor = self._actor(state, "author")
        events = paths["directory"] / f"author-{cycle}.jsonl"
        last = paths["directory"] / f"author-{cycle}-last.txt"
        findings = _sanitize_findings(state.get("review_findings", []))
        owner_answers = self._owner_answers(state)
        prompt = (
            "Implement the owner-approved mission in this exact repository. "
            "Read and obey all repository instructions. Do not commit, push, open a PR, merge, tag, release, "
            "deploy, use another agent, or change files outside the allowlist. Preserve the C#/.NET stack and "
            "use the smallest native implementation.\n\n"
            f"Goal: {self.profile['goal']}\n"
            f"Owner answers bound to this mission: {json.dumps(owner_answers)}\n"
            f"Exact allowed files: {json.dumps(self.profile['required_files'])}\n"
            f"Review findings to fix: {json.dumps(findings)}\n"
            "Run relevant focused tests if useful; the coordinator reruns the authoritative gates."
        )
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        with _temporary_private_output() as raw_last:
            result = self._run(
                [
                    self.profile["codex_bin"], "exec", "--ignore-user-config",
                    *self._reasoning_args(state, "author"),
                    "--model", actor["model"], "--sandbox", "workspace-write",
                    "--cd", str(paths["author"]), "--json", "--output-last-message", str(raw_last), "-",
                ],
                cwd=paths["author"], input_text=prompt,
                environment=self._model_env(paths),
            )
            _private_codex_events(events, result.stdout)
            if raw_last.is_file():
                _private_text(last, _bounded_diagnostic(raw_last.read_text(encoding="utf-8")))
        changed = self._changed_files(paths["author"])
        allowed = set(self.profile["required_files"])
        if not changed or not changed <= allowed:
            raise DeliveryError("author changed no files or escaped the exact allowlist")
        fingerprint = self._candidate_fingerprint(paths["author"])
        try:
            checks = self._checks("author_checks", paths["author"], state, paths)
        except DeliveryError as error:
            preserved = self._candidate_fingerprint(paths["author"]) == fingerprint
            if not preserved:
                error = DeliveryError("author checks mutated the exact candidate")
            self._record_author_check_failure(state, paths, error, retryable=preserved)
            return
        if self._candidate_fingerprint(paths["author"]) != fingerprint:
            raise DeliveryError("author checks changed the exact candidate")
        self._git(paths["author"], "add", "--", *sorted(changed))
        self._assert_claim(state)
        self._git(paths["author"], "commit", "-m", self.profile["commit_message"])
        self._record_author(state, paths, checks)

    def _remove_worktree(self, path: pathlib.Path) -> None:
        if path.exists():
            self._git(pathlib.Path(self.profile["source_checkout"]), "worktree", "remove", "--force", str(path))

    def _review(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> bool:
        route = self._current_route(state)
        actor = route["reviewer"]
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        self._remove_worktree(paths["review"])
        self._git(
            pathlib.Path(self.profile["source_checkout"]),
            "worktree", "add", "--detach", str(paths["review"]), state["candidate_sha"],
        )
        attestation = flow_contract.source_attestation(paths["review"], state["candidate_sha"])
        attestation_path = paths["directory"] / "review-source-attestation.json"
        mission_adapter._write_json(attestation_path, attestation, private_parent=True)
        schema_path = paths["directory"] / "review-schema.json"
        mission_adapter._write_json(
            schema_path,
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["verdict", "findings"],
                "properties": {
                    "verdict": {"type": "string", "enum": ["accept", "reject"]},
                    "findings": {"type": "array", "items": {"type": "string"}},
                },
            },
            private_parent=True,
        )
        cycle = state["review_cycle"]
        events = paths["directory"] / f"review-{cycle}.jsonl"
        last = paths["directory"] / f"review-{cycle}-last.json"
        marker = f"UAP_SOURCE_ATTESTATION_SHA256={attestation['sha256']}"
        prompt = (
            "Independently review this exact read-only candidate for correctness, regressions, security, and tests. "
            "Read repository instructions. Do not edit files, commit, push, or trust the author transcript. "
            f"The exact allowed file set is {json.dumps(self.profile['required_files'])}. "
            "Return accept only when no actionable finding remains. " + marker
        )
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        with _temporary_private_output() as raw_last:
            result = self._run(
                [
                    self.profile["codex_bin"], "exec", "--ignore-user-config",
                    *self._reasoning_args(state, "reviewer"),
                    "--model", actor["model"], "--sandbox", "read-only",
                    "--cd", str(paths["review"]), "--json", "--output-schema", str(schema_path),
                    "--output-last-message", str(raw_last), "-",
                ],
                cwd=paths["review"], input_text=prompt,
                environment=self._model_env(paths),
            )
            _private_codex_events(events, result.stdout)
            response = mission_adapter._read_json(raw_last)
        if (
            not isinstance(response, dict)
            or response.get("verdict") not in {"accept", "reject"}
            or not isinstance(response.get("findings"), list)
            or not all(isinstance(item, str) for item in response["findings"])
        ):
            raise DeliveryError("reviewer returned an invalid verdict")
        checks = self._checks("review_checks", paths["review"], state, paths)
        telemetry = flow_contract.summarize_codex_events(
            events,
            component="reviewer",
            model=actor["model"],
            reasoning_effort=actor["reasoning_effort"],
            rollout=self._rollout(events),
            sandbox="read-only",
            worktree=paths["review"],
            head=state["candidate_sha"],
            source_attestation_path=attestation_path,
        )
        findings = _sanitize_findings(response["findings"])
        response = {"verdict": response["verdict"], "findings": findings}
        mission_adapter._write_json(last, response, private_parent=True)
        verification = {
            "schema_version": 1,
            "reviewed_sha": state["candidate_sha"],
            "verdict": response["verdict"],
            "engine_family": "openai",
            "model": telemetry["model"],
            "reasoning_effort": telemetry.get("reasoning_effort"),
            "session_id": telemetry["session_id"],
            "review_mode": route["review_mode"],
            "route_decision_id": route["decision_id"],
            "findings": findings,
            "checks": checks,
            "review_cycle": cycle,
        }
        mission_adapter._write_json(paths["directory"] / "review-verification.json", verification, private_parent=True)
        mission_adapter._write_json(paths["directory"] / "review-telemetry.json", telemetry, private_parent=True)
        state.update(review_verification=verification, reviewer_telemetry=telemetry)
        if verification["verdict"] == "accept":
            state["phase"] = "reviewed"
            self._save(paths, state)
            return True
        state["prior_review_rejections"] = state.get("prior_review_rejections", 0) + 1
        if cycle > self.profile["max_review_cycles"]:
            state.update(
                phase="review_rejected",
                review_findings=verification["findings"],
            )
            self._save(paths, state)
            return False
        state.update(phase="needs_fix", review_cycle=cycle + 1, review_findings=verification["findings"])
        self._save(paths, state)
        return False

    def _pr(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> None:
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        fields = "number,url,state,headRefName,commits,baseRefName"
        bound = state.get("pr_number")
        if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
            raise DeliveryError("durable PR identity is invalid")
        if bound is not None:
            previous_head = state.get("pr_head_sha")
            if not isinstance(previous_head, str) or not previous_head:
                raise DeliveryError("durable PR head identity is missing")
            previous_base = state.get("pr_base_branch")
            if previous_base != self.profile["default_branch"]:
                raise DeliveryError("durable PR base identity is invalid")
            previous = json.loads(self._run([
                self.profile["gh_bin"], "pr", "view", str(bound),
                "--repo", self.profile["repo"], "--json", fields,
            ]).stdout)
            if (
                previous.get("number") != bound
                or previous.get("state") != "OPEN"
                or previous.get("headRefName") != state["branch"]
                or previous.get("baseRefName") != previous_base
            ):
                raise DeliveryError("durable PR changed before repair push")
            observed_head = _pr_head_oid(previous)
            if observed_head not in {previous_head, state["candidate_sha"]}:
                raise DeliveryError("durable PR changed before repair push")
        else:
            remote = self._git(
                paths["author"], "ls-remote", "--heads", "origin", state["branch"]
            )
            if remote:
                remote_fields = remote.split()
                if remote_fields != [
                    state["candidate_sha"], f"refs/heads/{state['branch']}"
                ]:
                    raise DeliveryError("initial PR branch identity is already occupied")
                observed_head = state["candidate_sha"]
            else:
                observed_head = None
        if observed_head != state["candidate_sha"]:
            self._assert_claim(
                state, min_remaining_seconds=self.profile["command_timeout_seconds"]
            )
            self._git(
                paths["author"], "push",
                f"--force-with-lease=refs/heads/{state['branch']}:{observed_head or ''}",
                "--set-upstream", "origin", state["branch"],
            )
        view = self._run(
            [
                self.profile["gh_bin"], "pr", "view",
                str(bound) if bound is not None else state["branch"],
                "--repo", self.profile["repo"], "--json", fields,
            ],
            check=False,
        )
        if view.returncode:
            if bound is not None:
                raise DeliveryError("durable PR could not be loaded for repair")
            self._assert_claim(
                state, min_remaining_seconds=self.profile["command_timeout_seconds"]
            )
            self._run(
                [
                    self.profile["gh_bin"], "pr", "create", "--repo", self.profile["repo"],
                    "--base", self.profile["default_branch"], "--head", state["branch"],
                    "--title", self.profile["pull_request_title"], "--body", self.profile["pull_request_body"],
                ],
                cwd=paths["author"],
            )
            view = self._run(
                [
                    self.profile["gh_bin"], "pr", "view", state["branch"],
                    "--repo", self.profile["repo"], "--json", fields,
                ]
            )
        info = json.loads(view.stdout)
        if (
            not isinstance(info.get("number"), int)
            or not isinstance(info.get("url"), str)
            or info.get("state") != "OPEN"
            or info.get("headRefName") != state["branch"]
            or _pr_head_oid(info) != state["candidate_sha"]
            or info.get("baseRefName") != self.profile["default_branch"]
            or (bound is not None and info.get("number") != bound)
        ):
            raise DeliveryError("GitHub returned invalid PR identity")
        state.update(
            phase="pr_open", pr_number=info["number"], pr_url=info["url"],
            pr_head_sha=state["candidate_sha"], pr_base_branch=info["baseRefName"],
        )
        self._save(paths, state)

    def _wait_ci(self, state: dict[str, Any]) -> None:
        deadline = time.monotonic() + self.profile["ci_timeout_seconds"]
        checks: Any = []
        while time.monotonic() < deadline:
            self._assert_claim(state)
            self._assert_pr_head(state)
            checks = self._ci_rollup(state)
            decision = _ci_decision(checks, self.profile["required_ci_checks"])
            if decision == "passed":
                state["ci_checks"] = _ci_summaries(checks)
                return
            if decision == "failed":
                raise CIFailed("PR CI failed or did not satisfy the exact required checks", checks)
            time.sleep(10)
        raise CIFailed("PR CI timed out", checks)

    def _ci_rollup(self, state: dict[str, Any]) -> Any:
        repo = self.profile["repo"]
        head = state.get("pr_head_sha")
        pr_number = state.get("pr_number")
        branch = state.get("branch")
        if (
            not isinstance(head, str) or not head
            or not isinstance(pr_number, int)
            or not isinstance(branch, str) or not branch
        ):
            raise DeliveryError("PR CI has no durable identity")
        value = json.loads(self._run([
            self.profile["gh_bin"], "api", "--method", "GET",
            f"repos/{repo}/actions/runs", "-f", f"head_sha={head}",
            "-f", "per_page=100",
        ]).stdout)
        runs = value.get("workflow_runs") if isinstance(value, dict) else None
        if not isinstance(runs, list) or value.get("total_count") != len(runs):
            raise DeliveryError("GitHub returned an invalid or truncated workflow run list")

        selected: dict[int, dict[str, Any]] = {}
        for run in runs:
            if (
                not isinstance(run, dict)
                or not isinstance(run.get("id"), int)
                or not isinstance(run.get("workflow_id"), int)
                or run.get("head_sha") != head
            ):
                raise DeliveryError("GitHub returned an invalid workflow run identity")
            pull_requests = run.get("pull_requests")
            if not isinstance(pull_requests, list):
                raise DeliveryError("GitHub returned an invalid workflow PR association")
            associated = any(
                isinstance(item, dict)
                and item.get("number") == pr_number
                and isinstance(item.get("head"), dict)
                and item["head"].get("ref") == branch
                and item["head"].get("sha") == head
                and isinstance(item.get("base"), dict)
                and item["base"].get("ref") == self.profile["default_branch"]
                for item in pull_requests
            )
            event = run.get("event")
            if (
                run.get("head_branch") != branch
                or (event == "pull_request" and not associated)
                or (event == "push" and pull_requests and not associated)
                or event not in {"pull_request", "push"}
            ):
                continue
            current = selected.get(run["workflow_id"])
            rank = (run.get("event") == "pull_request", run["id"])
            if current is None or rank > (
                current.get("event") == "pull_request", current["id"]
            ):
                selected[run["workflow_id"]] = run

        checks = []
        for run in sorted(selected.values(), key=lambda item: item["id"]):
            checks.append({
                "name": f"workflow:{run.get('name') or run['id']}",
                "status": str(run.get("status") or "").upper() or None,
                "conclusion": str(run.get("conclusion") or "").upper() or None,
            })
            jobs_value = json.loads(self._run([
                self.profile["gh_bin"], "api", "--method", "GET",
                f"repos/{repo}/actions/runs/{run['id']}/jobs",
                "-f", "filter=latest", "-f", "per_page=100",
            ]).stdout)
            jobs = jobs_value.get("jobs") if isinstance(jobs_value, dict) else None
            if not isinstance(jobs, list) or jobs_value.get("total_count") != len(jobs):
                raise DeliveryError("GitHub returned an invalid or truncated workflow job list")
            for job in jobs:
                if not isinstance(job, dict) or job.get("head_sha") != head:
                    raise DeliveryError("GitHub returned an invalid workflow job identity")
                checks.append({
                    "name": job.get("name"),
                    "status": str(job.get("status") or "").upper() or None,
                    "conclusion": str(job.get("conclusion") or "").upper() or None,
                })
        return checks

    def _require_ci_green_now(self, state: dict[str, Any]) -> None:
        checks = self._ci_rollup(state)
        decision = _ci_decision(checks, self.profile["required_ci_checks"])
        if decision == "failed":
            raise CIFailed("required PR CI failed at the merge boundary", checks)
        if decision != "passed":
            raise DeliveryError("required PR CI is not green at the merge boundary")
        state["ci_checks"] = _ci_summaries(checks)

    def _record_ci_failure(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path], error: CIFailed
    ) -> None:
        summaries = _ci_summaries(error.checks)
        details = ", ".join(f"{item['name']}={item['outcome']}" for item in summaries)
        finding = _bounded_diagnostic(f"{error}: {details or 'invalid check rollup'}")
        self._quality_failures(state)
        state["ci_checks"] = summaries
        state["prior_ci_failures"] = state.get("prior_ci_failures", 0) + 1
        if state["review_cycle"] <= self.profile["max_review_cycles"]:
            state.update(
                phase="needs_fix",
                review_cycle=state["review_cycle"] + 1,
                review_findings=[finding],
            )
        else:
            state.update(
                phase="ci_failed",
                failure_kind="ci",
                failure_error=finding,
            )
        self._save(paths, state)

    def _finalize_failed_pr(self, state: dict[str, Any]) -> bool:
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        fields = "state,headRefName,commits,baseRefName"
        expected_head = state.get("pr_head_sha")
        if not isinstance(expected_head, str) or not expected_head:
            raise DeliveryError("failed PR has no durable head identity")
        expected_base = state.get("pr_base_branch")
        if expected_base != self.profile["default_branch"]:
            raise DeliveryError("failed PR has no durable base identity")

        def inspect() -> dict[str, Any]:
            return json.loads(self._run(
                [
                    self.profile["gh_bin"], "pr", "view", str(state["pr_number"]),
                    "--repo", self.profile["repo"], "--json", fields,
                ]
            ).stdout)

        def require_identity(info: dict[str, Any], *states: str) -> None:
            if (
                info.get("headRefName") != state["branch"]
                or _pr_head_oid(info) != expected_head
                or info.get("baseRefName") != expected_base
                or info.get("state") not in states
            ):
                raise DeliveryError("failed PR identity no longer matches the durable candidate")

        info = inspect()
        require_identity(info, "OPEN", "CLOSED")
        source = pathlib.Path(self.profile["source_checkout"])
        remote = self._git(source, "ls-remote", "--heads", "origin", state["branch"])
        if remote:
            remote_fields = remote.split()
            if remote_fields != [expected_head, f"refs/heads/{state['branch']}"]:
                raise DeliveryError("failed PR branch moved before cleanup")
        if info.get("state") == "OPEN":
            if not remote:
                raise DeliveryError("open failed PR has no exact remote branch")
            return True
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        if remote:
            self._git(
                source, "push",
                f"--force-with-lease=refs/heads/{state['branch']}:{expected_head}",
                "origin", "--delete", state["branch"],
            )
            if self._git(source, "ls-remote", "--heads", "origin", state["branch"]):
                raise DeliveryError("failed PR branch cleanup did not converge")
        info = inspect()
        require_identity(info, "CLOSED")
        return False

    def _assert_pr_head(self, state: dict[str, Any]) -> None:
        info = json.loads(self._run(
            [
                self.profile["gh_bin"], "pr", "view", str(state["pr_number"]),
                "--repo", self.profile["repo"], "--json", "headRefName,commits,baseRefName",
            ]
        ).stdout)
        if (
            info.get("headRefName") != state["branch"]
            or _pr_head_oid(info) != state["candidate_sha"]
            or info.get("baseRefName") != state.get("pr_base_branch")
            or info.get("baseRefName") != self.profile["default_branch"]
        ):
            raise DeliveryError("PR identity no longer matches the reviewed candidate")

    def _validate_review(self, state: dict[str, Any]) -> None:
        flow_contract.validate_review(
            state["author_summary"],
            state["review_verification"],
            state["author_telemetry"],
            state["reviewer_telemetry"],
            self._current_route(state),
            self.policy,
            expected_repo=self.profile["repo"],
            current_head=state["candidate_sha"],
            ci_green=True,
        )

    def _merge(self, state: dict[str, Any]) -> None:
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        self._assert_pr_head(state)
        self._wait_ci(state)
        self._validate_review(state)
        info = json.loads(self._run(
            [
                self.profile["gh_bin"], "pr", "view", str(state["pr_number"]),
                "--repo", self.profile["repo"],
                "--json", "state,mergedAt,mergeCommit,url,headRefName,commits,baseRefName",
            ]
        ).stdout)
        if info.get("state") != "MERGED":
            self._assert_claim(
                state, min_remaining_seconds=self.profile["command_timeout_seconds"]
            )
            self._assert_pr_head(state)
            self._require_ci_green_now(state)
            merge_result = json.loads(self._run(
                [
                    self.profile["gh_bin"], "api", "--method", "PUT",
                    f"repos/{self.profile['repo']}/pulls/{state['pr_number']}/merge",
                    "-f", "merge_method=merge", "-f", f"sha={state['candidate_sha']}",
                ]
            ).stdout)
            if merge_result.get("merged") is not True:
                raise DeliveryError("GitHub rejected the exact-head merge")
            info = json.loads(self._run(
                [
                    self.profile["gh_bin"], "pr", "view", str(state["pr_number"]),
                    "--repo", self.profile["repo"],
                    "--json", "state,mergedAt,mergeCommit,url,headRefName,commits,baseRefName",
                ]
            ).stdout)
        if (
            info.get("state") != "MERGED"
            or not info.get("mergedAt")
            or info.get("headRefName") != state["branch"]
            or _pr_head_oid(info) != state["candidate_sha"]
            or info.get("baseRefName") != state.get("pr_base_branch")
            or info.get("baseRefName") != self.profile["default_branch"]
        ):
            raise DeliveryError("PR did not reach merged state")
        merge_sha = (info.get("mergeCommit") or {}).get("oid")
        if not isinstance(merge_sha, str) or not merge_sha:
            raise DeliveryError("GitHub returned no merge commit identity")
        source = pathlib.Path(self.profile["source_checkout"])
        self._git(source, "fetch", "--prune", "origin", self.profile["default_branch"])
        default_ref = f"origin/{self.profile['default_branch']}"
        if self._run(
            ["git", "-C", str(source), "merge-base", "--is-ancestor", state["candidate_sha"], merge_sha],
            check=False,
        ).returncode:
            raise DeliveryError("merge commit does not contain the reviewed candidate")
        if self._run(
            ["git", "-C", str(source), "merge-base", "--is-ancestor", merge_sha, default_ref],
            check=False,
        ).returncode:
            raise DeliveryError("merge commit is not on the fetched default branch")
        remote = self._git(source, "ls-remote", "--heads", "origin", state["branch"])
        if remote:
            if remote.split() != [
                state["candidate_sha"], f"refs/heads/{state['branch']}"
            ]:
                raise DeliveryError("merged PR branch moved before cleanup")
            self._git(
                source, "push",
                f"--force-with-lease=refs/heads/{state['branch']}:{state['candidate_sha']}",
                "origin", "--delete", state["branch"],
            )
            if self._git(source, "ls-remote", "--heads", "origin", state["branch"]):
                raise DeliveryError("merged PR branch cleanup did not converge")
        state["merge_sha"] = merge_sha

    def _post_verify(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> None:
        source = pathlib.Path(self.profile["source_checkout"])
        self._git(source, "fetch", "--prune", "origin", self.profile["default_branch"])
        default_ref = f"origin/{self.profile['default_branch']}"
        if self._run(
            ["git", "-C", str(source), "merge-base", "--is-ancestor", state["candidate_sha"], default_ref],
            check=False,
        ).returncode:
            raise DeliveryError("reviewed candidate is not an ancestor of the default branch")
        state["default_sha"] = self._git(source, "rev-parse", default_ref)
        self._remove_worktree(paths["verify"])
        self._git(source, "worktree", "add", "--detach", str(paths["verify"]), state["default_sha"])
        try:
            state["post_verify_checks"] = self._checks(
                "post_verify_checks", paths["verify"], state, paths
            )
        except DeliveryError as error:
            raise PostVerifyFailed(str(error)) from error

    @staticmethod
    def _repair_mission_id(mission_id: str) -> str:
        digest = hashlib.sha256(mission_id.encode()).hexdigest()[:32]
        return f"repair-{digest}"

    def _record_post_verify_failure(
        self,
        state: dict[str, Any],
        paths: dict[str, pathlib.Path],
        error: Exception,
    ) -> None:
        diagnostic = _bounded_diagnostic(str(error), "post-verify failed")
        repair = self.profile.get("post_verify_repair")
        if repair is None or state.get("repair_mission_id") is not None:
            state.update(
                phase="post_verify_failed",
                failure_kind="post_verify",
                failure_error=diagnostic,
            )
        else:
            state.update(
                phase="post_verify_repair_pending",
                post_verify_failure=diagnostic,
                failed_default_sha=state.get("default_sha", ""),
                repair_mission_id=self._repair_mission_id(state["mission_id"]),
            )
        self._save(paths, state)

    def _dispatch_post_verify_repair(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> dict[str, Any]:
        repair = self.profile.get("post_verify_repair")
        if not isinstance(repair, dict):
            raise DeliveryError("post-verify repair profile disappeared")
        child_id = state.get("repair_mission_id")
        if not isinstance(child_id, str) or not child_id:
            raise DeliveryError("post-verify repair identity is missing")
        context = {
            "schema_version": 1,
            "mission_id": child_id,
            "parent_mission_id": state["mission_id"],
            "dispatch_profile": repair["dispatch_profile"],
            "diagnostic": _bounded_diagnostic(
                str(state.get("post_verify_failure") or ""), "post-verify failed"
            ),
            "failed_default_sha": str(state.get("failed_default_sha") or ""),
        }
        child_paths = self._paths(child_id)
        mission_adapter._write_json(
            child_paths["repair_context"], context, private_parent=True
        )
        child = self.client.accept_mission(
            mission_id=child_id,
            goal=repair["goal"],
            dispatch_profile=repair["dispatch_profile"],
            parent_mission_id=state["mission_id"],
        )
        if (
            child.get("mission_id") != child_id
            or child.get("goal") != repair["goal"]
            or child.get("dispatch_profile") != repair["dispatch_profile"]
            or child.get("parent_mission_id") != state["mission_id"]
        ):
            raise DeliveryError("Central accepted the wrong post-verify repair mission")
        state["phase"] = "post_verify_repair_waiting"
        self._save(paths, state)
        return {
            "action": state["phase"],
            "mission_id": state["mission_id"],
            "repair_mission_id": child_id,
            "state": state,
        }

    def _observe_post_verify_repair(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> dict[str, Any] | None:
        child_id = state.get("repair_mission_id")
        repair = self.profile.get("post_verify_repair")
        if not isinstance(child_id, str) or not isinstance(repair, dict):
            raise DeliveryError("post-verify repair state is invalid")
        child = self.client.get_mission(child_id)
        if (
            child.get("mission_id") != child_id
            or child.get("goal") != repair["goal"]
            or child.get("dispatch_profile") != repair["dispatch_profile"]
            or child.get("parent_mission_id") != state["mission_id"]
        ):
            raise DeliveryError("post-verify repair mission identity changed")
        if child.get("status") in {"active", "waiting_owner"}:
            return {
                "action": state["phase"],
                "mission_id": state["mission_id"],
                "repair_mission_id": child_id,
                "state": state,
            }
        if child.get("status") == "completed":
            state["phase"] = "post_verify_repair_completed"
            self._save(paths, state)
            return None
        if child.get("status") not in {"failed", "cancelled"}:
            raise DeliveryError("post-verify repair has an invalid terminal status")
        self._record_post_verify_failure(
            state,
            paths,
            DeliveryError(
                _bounded_diagnostic(
                    str(child.get("error") or "repair mission failed"),
                    "repair mission failed",
                )
            ),
        )
        return None

    def _retry_post_verify_after_repair(
        self, state: dict[str, Any], paths: dict[str, pathlib.Path]
    ) -> None:
        failed_sha = state.get("failed_default_sha")
        try:
            self._post_verify(state, paths)
            if not failed_sha or state.get("default_sha") == failed_sha:
                raise PostVerifyFailed(
                    "repair mission completed without changing the default branch"
                )
        except PostVerifyFailed as error:
            self._record_post_verify_failure(state, paths, error)
            return
        state["phase"] = "verified"
        self._save(paths, state)

    def _events(self, state: dict[str, Any], *, cleanup: bool) -> list[dict[str, Any]]:
        events = [
            *(
                {"type": "change.upsert", "payload": {"path": path, "status": "modified"}}
                for path in self.profile["required_files"]
            ),
            {"type": "gate.upsert", "payload": {"gate_id": "tests", "status": "passed"}},
            {"type": "gate.upsert", "payload": {"gate_id": "review", "status": "passed"}},
            {"type": "gate.upsert", "payload": {"gate_id": "ci", "status": "passed"}},
            {"type": "gate.upsert", "payload": {"gate_id": "post-verify", "status": "passed"}},
            {"type": "delivery.upsert", "payload": {
                "kind": "pull_request", "status": "merged", "url": state["pr_url"],
            }},
            {"type": "delivery.upsert", "payload": {
                "kind": "default_branch", "status": "verified",
                "url": f"https://github.com/{self.profile['repo']}/commit/{state['default_sha']}",
            }},
        ]
        if cleanup:
            events.append({"type": "gate.upsert", "payload": {"gate_id": "cleanup", "status": "passed"}})
        return events

    def _cleanup(
        self,
        state: dict[str, Any],
        paths: dict[str, pathlib.Path],
        *,
        preserve_remote: bool = False,
    ) -> None:
        self._assert_claim(
            state, min_remaining_seconds=self.profile["command_timeout_seconds"]
        )
        source = pathlib.Path(self.profile["source_checkout"])
        for name in ("review", "verify", "author"):
            self._remove_worktree(paths[name])
        self._git(source, "branch", "-D", state["branch"], check=False)
        self._git(source, "worktree", "prune")
        if any(paths[name].exists() for name in ("review", "verify", "author")):
            raise DeliveryError("disposable worktree cleanup did not converge")
        if self._git(source, "branch", "--list", state["branch"]):
            raise DeliveryError("disposable local branch still exists")
        remote = self._git(source, "ls-remote", "--heads", "origin", state["branch"])
        if preserve_remote:
            if remote.split() != [
                state.get("pr_head_sha"), f"refs/heads/{state['branch']}"
            ]:
                raise DeliveryError("preserved failed PR branch identity changed")
        elif remote:
            raise DeliveryError("disposable remote branch still exists")

    def _archive_task(self, state: dict[str, Any], paths: dict[str, pathlib.Path]) -> None:
        if state.get("task_archived") is True:
            return
        self.backend.archive(state["root_task_id"])
        state["task_archived"] = True
        state["kanban_gc_ran"] = self.backend.gc()
        self._save(paths, state)

    def _prune_completed_states(self) -> None:
        cutoff = time.time() - _COMPLETED_STATE_RETENTION_SECONDS
        # Rename before recursive deletion so a crash after delivery-state.json
        # disappears still leaves a directory that the next tick can discover.
        for pending in self.state_root.glob(".prune-mission-*"):
            try:
                shutil.rmtree(pending)
            except FileNotFoundError:
                pass
        for path in self.state_root.glob("mission-*/delivery-state.json"):
            try:
                state = mission_adapter._read_json(path)
                retained_at = path.stat().st_mtime
            except FileNotFoundError:
                continue
            if (
                isinstance(state, dict)
                and state.get("dispatch_profile") == self.profile["dispatch_profile"]
                and state.get("phase") == "complete"
                and state.get("task_archived") is True
            ):
                if state.get("kanban_gc_ran") is not True:
                    state["kanban_gc_ran"] = self.backend.gc()
                    if state["kanban_gc_ran"] is not True:
                        continue
                    mission_adapter._write_json(
                        path,
                        state,
                        private_parent=True,
                        retained_mtime=retained_at,
                    )
                if retained_at >= cutoff:
                    continue
                pending = self.state_root / f".prune-{path.parent.name}"
                try:
                    path.parent.replace(pending)
                except FileNotFoundError:
                    continue
                try:
                    shutil.rmtree(pending)
                except FileNotFoundError:
                    pass

    def tick(self) -> dict[str, Any] | None:
        self._prune_completed_states()
        mission = self._mission()
        if mission is None:
            return None
        mission_id = mission["mission_id"]
        paths = self._paths(mission_id)
        with exclusive_lock(paths["lock"]):
            state = self._load_state(mission_id, paths)
            if state["phase"] in {
                "review_rejected", "author_checks_failed", "ci_failed", "rejection_cleaned",
                "post_verify_failed", "rejection_task_completed",
            }:
                return self._finish_rejection(state, paths)
            if mission.get("status") == "completed":
                if state.get("phase") == "cleaned":
                    self._recover_task_completion(state, paths)
                if state.get("phase") not in {"task_completed", "complete"}:
                    raise DeliveryError("Central completed before local delivery cleanup")
                self._archive_task(state, paths)
                state["phase"] = "complete"
                self._save(paths, state)
                return {"action": "complete", "mission_id": mission_id, "state": state}
            if mission.get("status") in {"failed", "cancelled"}:
                raise DeliveryError(f"mission is terminal: {mission.get('status')}")
            if mission.get("status") == "waiting_owner":
                return self._wait_for_owner(state, mission, paths)
            if state.get("phase") == "waiting_owner" and mission.get("answer") is None:
                raise DeliveryError("owner question cleared without a durable answer")
            answer = mission.get("answer")
            if isinstance(answer, dict):
                consumed = any(
                    item["question_id"] == answer.get("question_id")
                    for item in self._owner_answers(state)
                )
                if state.get("phase") in {"new", "waiting_owner", "owner_answer_pending"}:
                    self._resume_owner_answer(state, mission, paths)
                elif not consumed:
                    raise DeliveryError("owner answer has no durable execution checkpoint")
            self._ensure_route(state, paths)
            if state["phase"] == "cleaned":
                self._recover_task_completion(state, paths)
            if state["phase"] not in {
                "cleanup_pending", "cleaned", "task_completed", "complete"
            }:
                if state["phase"] != "new":
                    self._assert_claim(state)
                self._ensure_worktree(state, paths)
                self._save(paths, state)

            if state["phase"] == "post_verify_repair_pending":
                self._assert_claim(state)
                return self._dispatch_post_verify_repair(state, paths)

            if state["phase"] == "post_verify_repair_waiting":
                self._assert_claim(state)
                waiting = self._observe_post_verify_repair(state, paths)
                if waiting is not None:
                    return waiting
                if state["phase"] == "post_verify_failed":
                    return self._finish_rejection(state, paths)

            if state["phase"] == "post_verify_repair_completed":
                self._assert_claim(state)
                self._retry_post_verify_after_repair(state, paths)
                if state["phase"] == "post_verify_failed":
                    return self._finish_rejection(state, paths)

            if state["phase"] == "new":
                self._assert_nonroutable_assignee()
                handoff = mission_adapter.coordinator_tick(
                    self.client,
                    self.state_root,
                    self.backend,
                    dispatch_profile=self.profile["dispatch_profile"],
                    workspace=f"worktree:{paths['author']}",
                    assignee=self.profile["assignee"],
                    activate=True,
                )
                if not isinstance(handoff, dict):
                    raise DeliveryError("active mission handoff was not created or recovered")
                state["root_task_id"] = handoff["root_task_id"]
                self._ensure_claimed(state)
                state["phase"] = "claimed"
                self._save(paths, state)
                self._publish_stage(state, "implementing", 20)
                self._reconcile_active(state)

            if state["phase"] in {"claimed", "needs_fix"}:
                self._assert_claim(state)
                if not self._recover_author_commit(state, paths):
                    self._author(state, paths)

            if state["phase"] == "author_committed" and not state["crash_injected"]:
                self._assert_claim(state)
                state["crash_injected"] = True
                self._save(paths, state)
                raise InjectedCrash("approved crash after durable author commit before Central ACK")

            if state["phase"] == "author_committed":
                self._assert_claim(state)
                if self._git(paths["author"], "rev-parse", "HEAD") != state["candidate_sha"]:
                    raise DeliveryError("restart did not preserve the exact author commit")
                self._publish_stage(state, "testing", 50)
                self._reconcile_active(state)
                if not self._review(state, paths):
                    if state["phase"] == "review_rejected":
                        return self._finish_rejection(state, paths)
                    return {"action": state["phase"], "mission_id": mission_id, "state": state}

            if state["phase"] == "reviewed":
                self._assert_claim(state)
                self._publish_stage(state, "reviewing", 65)
                self._pr(state, paths)
                self._publish_stage(state, "delivering", 80)

            try:
                if state["phase"] == "pr_open":
                    self._assert_claim(state)
                    self._wait_ci(state)
                    self._validate_review(state)
                    state["phase"] = "ci_green"
                    self._save(paths, state)

                if state["phase"] == "ci_green":
                    self._assert_claim(state)
                    self._merge(state)
                    state["phase"] = "merged"
                    self._save(paths, state)
                    self._publish_stage(state, "verifying", 90)
            except CIFailed as error:
                self._record_ci_failure(state, paths, error)
                if state["phase"] == "ci_failed":
                    return self._finish_rejection(state, paths)
                return {"action": state["phase"], "mission_id": mission_id, "state": state}

            if state["phase"] == "merged":
                self._assert_claim(state)
                try:
                    self._post_verify(state, paths)
                except PostVerifyFailed as error:
                    self._record_post_verify_failure(state, paths, error)
                    if state["phase"] == "post_verify_failed":
                        return self._finish_rejection(state, paths)
                    return self._dispatch_post_verify_repair(state, paths)
                else:
                    state["phase"] = "verified"
                    self._save(paths, state)

            if state["phase"] == "verified":
                self._assert_claim(state)
                state["phase"] = "cleanup_pending"
                self._save(paths, state)

            if state["phase"] == "cleanup_pending":
                self._cleanup(state, paths)
                state["phase"] = "cleaned"
                self._save(paths, state)

            if state["phase"] == "cleaned":
                if not self._recover_task_completion(state, paths):
                    self._assert_claim(state)
                    self.backend.complete(
                        state["root_task_id"],
                        result="success",
                        summary="Reviewed change merged, verified, and cleaned",
                        metadata={"mission_events": self._events(state, cleanup=True)},
                    )
                    if not self._recover_task_completion(state, paths):
                        raise DeliveryError("Kanban completion did not reach terminal state")

            if state["phase"] == "task_completed":
                self._reconcile_completed(state)
                terminal = self.client.get_mission(mission_id)
                if terminal.get("status") != "completed":
                    raise DeliveryError("Central did not complete the fully verified mission")
                self._archive_task(state, paths)
                state["phase"] = "complete"
                self._save(paths, state)
            return {"action": state["phase"], "mission_id": mission_id, "state": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=pathlib.Path)
    parser.add_argument("--central-url", default=os.environ.get("HERMES_API_URL"))
    parser.add_argument("--state-root", type=pathlib.Path, default=pathlib.Path("/home/uap/swarm-out"))
    parser.add_argument("--hermes-bin", default="/home/uap/hermes-agent/.venv/bin/hermes")
    parser.add_argument("--board", default="default")
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
        producer_key = os.environ.get("HERMES_MISSION_PRODUCER_KEY", "").strip()
        if not producer_key:
            key_path = pathlib.Path.home() / ".config" / "mission-producer-key"
            if key_path.is_file():
                producer_key = key_path.read_text(encoding="utf-8").strip()
        client = mission_adapter.CentralMissionClient(
            args.central_url,
            os.environ.get("HERMES_API_TOKEN", ""),
            producer_key,
        )
        result = DeliveryCoordinator(
            profile,
            client,
            mission_adapter.HermesKanbanBackend(args.hermes_bin, args.board),
            args.state_root,
        ).tick()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except InjectedCrash as error:
        print(f"hermes-delivery-coordinator-injected-crash: {error}", file=sys.stderr)
        return 75
    except (
        DeliveryError,
        mission_adapter.AdapterError,
        flow_contract.ContractError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        diagnostic = _bounded_diagnostic(str(error), "delivery failed")
        print(f"hermes-delivery-coordinator-error: {diagnostic}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
