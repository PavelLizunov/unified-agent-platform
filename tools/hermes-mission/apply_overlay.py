#!/usr/bin/env python3
"""Install the UAP mission module into the exact pinned Hermes checkout."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess


UPSTREAM_COMMIT = "7c1a029553d87c43ecff8a3821336bc95872213b"
FILES = {
    "hermes_cli/commands.py": "028c9aa215dc7796bc9f12125bc6ebd03474e3d32f196e6dcd18c4f41841223a",
    "hermes_cli/kanban_db.py": "7ea3133148f82006840fa4883c8ce5e588945e26c1fde3889cb55a48ceec7c64",
    "gateway/run.py": "f25c56ba85a471e864264bad27e4dd656102a36199a78fc79c7540c95dbcea79",
    "gateway/platforms/api_server.py": "303f84d485c67a96d86f88badb5d111e842e5744448f30a18353e6a4c30c0240",  # gitleaks:allow -- pinned source SHA-256
}
PATCHED_FILES = {
    "hermes_cli/commands.py": "a15d100256f8e7fec986bd44fbbae47b561e3e7a2b206bce0c2740e30431a173",
    "hermes_cli/kanban_db.py": "9610e5d3fb6a4448c72835396e583958c0f1b6c8db95ef0f69637bf0528897da",
    "gateway/run.py": "72fe0d51d8752942f48b37b469870de83ddfa00d2f726f33cb84df4214ca0d1e",
        "gateway/platforms/api_server.py": "6305e75eef3ba6f128fb022983a8a5276f074a8d29b6ed329073bcd87433297b",  # gitleaks:allow -- pinned patched SHA-256
}
RUNTIME_SOURCE = pathlib.Path(__file__).with_name("runtime.py")
RUNTIME_TARGET = "hermes_cli/uap_missions.py"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"overlay fragment mismatch: {name}")
    return text.replace(old, new, 1)


def transform(relative: str, text: str) -> str:
    if relative == "hermes_cli/commands.py":
        return replace(
            text,
            '    CommandDef("status", "Show session, model, token, and context info", "Session"),',
            '    CommandDef("status", "Show session, model, token, and context info", "Session"),\n'
            '    CommandDef("mission", "Show or follow one central UAP mission", "Session",\n'
            '               args_hint="[mission-id]", gateway_only=True),',
            "mission command",
        )
    if relative == "hermes_cli/kanban_db.py":
        text = replace(
            text,
            '''                _append_event(
                    conn,
                    task_id,
                    "created",
                    {
                        "assignee": assignee,
                        "status": task_status,
                        "parents": list(parents),
                        "tenant": tenant,
                        "branch_name": branch_name,
                        "skills": list(skills_list) if skills_list else None,
                        "goal_mode": bool(goal_mode) or None,
                    },
                )''',
            '''                _append_event(
                    conn,
                    task_id,
                    "created",
                    {
                        "assignee": assignee,
                        "status": task_status,
                        "parents": list(parents),
                        "tenant": tenant,
                        "branch_name": branch_name,
                        "skills": list(skills_list) if skills_list else None,
                        "goal_mode": bool(goal_mode) or None,
                    },
                )
                if task_status == "blocked":
                    conn.execute(
                        "UPDATE tasks SET block_kind = 'needs_input' WHERE id = ?",
                        (task_id,),
                    )
                    _append_event(
                        conn,
                        task_id,
                        "blocked",
                        {"reason": None, "kind": "needs_input"},
                    )''',
            "atomic sticky initial block",
        )
        text = replace(
            text,
            '''    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key)"
    )''',
            '''    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key)"
    )
    duplicate = conn.execute(
        "SELECT idempotency_key, COUNT(*) AS task_count FROM tasks "
        "WHERE idempotency_key IS NOT NULL AND status != 'archived' "
        "GROUP BY idempotency_key HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate:
        raise RuntimeError(
            "active Kanban idempotency duplicates must be resolved before migration: "
            f"{duplicate['idempotency_key']} ({duplicate['task_count']} rows)"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_idempotency "
        "ON tasks(idempotency_key) "
        "WHERE idempotency_key IS NOT NULL AND status != 'archived'"
    )''',
            "active idempotency uniqueness",
        )
        text = replace(
            text,
            '''        except sqlite3.IntegrityError:
            if attempt == 1:
                raise
            # Retry with a fresh id.
            continue''',
            '''        except sqlite3.IntegrityError:
            if idempotency_key:
                row = conn.execute(
                    "SELECT id FROM tasks WHERE idempotency_key = ? "
                    "AND status != 'archived' ORDER BY created_at DESC LIMIT 1",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    return row["id"]
            if attempt == 1:
                raise
            # Retry with a fresh id.
            continue''',
            "concurrent idempotency recovery",
        )
        text = replace(
            text,
            '''def connect(
    db_path: Optional[Path] = None,''',
            '''def _harden_db_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    os.chmod(path.parent, 0o700)
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        if candidate.exists():
            os.chmod(candidate, 0o600)


def connect(
    db_path: Optional[Path] = None,''',
            "owner-only Kanban database",
        )
        text = replace(
            text,
            '''        conn = _sqlite_connect(path)
        try:''',
            '''        conn = _sqlite_connect(path)
        _harden_db_permissions(path)
        try:''',
            "fast-path Kanban permissions",
        )
        return replace(
            text,
            '''        conn = _sqlite_connect(path)
        try:''',
            '''        conn = _sqlite_connect(path)
        _harden_db_permissions(path)
        try:''',
            "init-path Kanban permissions",
        )
    if relative == "gateway/run.py":
        return replace(
            text,
            '''        if canonical == "status":
            return await self._handle_status_command(event)

        if canonical == "agents":''',
            '''        if canonical == "status":
            return await self._handle_status_command(event)

        if canonical == "mission":
            from hermes_cli.uap_missions import MissionError, MissionStore, telegram_text

            store = MissionStore.default()
            platform = source.platform.value if source.platform else "unknown"
            chat_id = str(source.chat_id)
            thread_id = str(source.thread_id or "")
            requested = event.get_command_args().strip()
            mission_id = requested or store.bound_mission(platform, chat_id, thread_id) or store.latest()
            if not mission_id:
                return "No central missions yet."
            try:
                if requested:
                    store.bind(mission_id, platform, chat_id, thread_id)
                return telegram_text(store.projection(mission_id))
            except MissionError as error:
                return f"Mission unavailable: {error}"

        if canonical == "agents":''',
            "mission gateway handler",
        )
    if relative == "gateway/platforms/api_server.py":
        text = replace(
            text,
            "from agent.redact import redact_sensitive_text",
            "from agent.redact import redact_sensitive_text\n"
            "from hermes_cli.uap_missions import (\n"
            "    MissionError, MissionStore, NOTIFICATION_SEND_TIMEOUT_SECONDS,\n"
            "    notify_subscribers, producer_key_valid,\n"
            "    sanitize_producer_submission, terminal_request_allowed,\n"
            ")",
            "mission imports",
        )
        text = replace(
            text,
            "        self._session_db: Optional[Any] = None  # Lazy-init SessionDB for session continuity",
            "        self._session_db: Optional[Any] = None  # Lazy-init SessionDB for session continuity\n"
            "        self._mission_store: Optional[MissionStore] = None",
            "mission store",
        )
        methods = '''    def _missions(self) -> MissionStore:
        if self._mission_store is None:
            self._mission_store = MissionStore.default()
        return self._mission_store

    async def _handle_list_missions(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            limit = int(request.query.get("limit", "20"))
            store = self._missions()
            reconcile = request.query.get("reconcile", "0")
            if reconcile not in {"0", "1"}:
                raise MissionError("invalid reconcile selector")
            missions = (
                store.dispatch_candidates(
                    request.query.get("dispatch_profile"),
                    limit,
                    reconcile=reconcile == "1",
                )
                if "dispatch_profile" in request.query
                else store.list(limit)
            )
            return web.json_response({"missions": missions})
        except (MissionError, TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_create_mission(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            body = await request.json()
            if body.get("parent_mission_id") is not None and not producer_key_valid(
                request.headers.get("X-Hermes-Mission-Producer-Key")
            ):
                return web.json_response(
                    {"error": "Invalid mission producer key"}, status=401
                )
            store = self._missions()
            event, created = store.accept(
                redact_sensitive_text(body.get("goal"), force=True),
                mission_id=body.get("mission_id"),
                session_id=body.get("session_id"),
                run_id=body.get("run_id"),
                dispatch_profile=body.get("dispatch_profile"),
                parent_mission_id=body.get("parent_mission_id"),
            )
            return web.json_response({
                "created": created,
                **store.workspace_payload(event["mission_id"]),
            }, status=201 if created else 200)
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_get_mission(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            after = int(request.query.get("after", "0"))
            return web.json_response(
                self._missions().workspace_payload(request.match_info["mission_id"], after)
            )
        except MissionError as error:
            status = 404 if str(error) == "mission not found" else 400
            return web.json_response({"error": str(error)}, status=status)
        except (TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _notify_mission(
        self, store: MissionStore, event: Dict[str, Any], *, defer: bool = True
    ) -> None:
        async def send(subscription: Dict[str, Any], text: str) -> None:
            from gateway.run import _gateway_runner_ref

            runner = _gateway_runner_ref()
            if runner is None:
                raise RuntimeError("gateway runner unavailable")
            adapter = next(
                (candidate for platform, candidate in runner.adapters.items()
                 if platform.value == subscription["platform"]),
                None,
            )
            if adapter is None:
                raise RuntimeError(f"platform unavailable: {subscription['platform']}")
            metadata = None
            if subscription["thread_id"]:
                metadata = {"thread_id": subscription["thread_id"]}
            result = await asyncio.wait_for(
                adapter.send(subscription["chat_id"], text, metadata=metadata),
                timeout=NOTIFICATION_SEND_TIMEOUT_SECONDS,
            )
            if result is not None and getattr(result, "success", True) is False:
                raise RuntimeError(getattr(result, "error", "mission notification failed"))

        try:
            await notify_subscribers(store, event, send)
        except Exception as error:
            if not defer:
                raise
            logger.warning("Mission notification deferred: %s", error)

    async def _handle_append_mission_event(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not producer_key_valid(request.headers.get("X-Hermes-Mission-Producer-Key")):
            return web.json_response({"error": "Invalid mission producer key"}, status=401)
        try:
            mission_id = request.match_info["mission_id"]
            body = sanitize_producer_submission(
                mission_id,
                await request.json(),
                lambda value: redact_sensitive_text(value, force=True),
            )
            store = self._missions()
            event, created = store.append_producer(mission_id, body)
            if created:
                await self._notify_mission(store, event)
            completed = store.complete_if_ready(mission_id)
            if completed is None:
                notification = store.completion_notification(mission_id)
                if notification is not None:
                    await self._notify_mission(store, notification, defer=False)
                    completed = store.complete_if_ready(mission_id)
                    if completed is None:
                        raise RuntimeError("mission completion checkpoint did not converge")
            if completed is not None and completed[1]:
                await self._notify_mission(store, completed[0])
            return web.json_response({
                "created": created,
                "event": event,
                "mission": store.projection(event["mission_id"]),
            }, status=201 if created else 200)
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_finish_mission(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not terminal_request_allowed(request.remote):
            return web.json_response(
                {"error": "Mission terminal authority is local only"}, status=403
            )
        try:
            body = await request.json()
            status = str(body.get("status") or "").strip()
            if status == "completed":
                raise MissionError("completed mission requires the automatic delivery contract")
            terminal = {
                "failed": ("mission.failed", "error"),
                "cancelled": ("mission.cancelled", "reason"),
            }.get(status)
            if terminal is None:
                raise MissionError("invalid mission terminal status")
            message = redact_sensitive_text(body.get("message"), force=True).strip()
            if not message:
                raise MissionError("mission terminal message is required")
            event_type, payload_field = terminal
            fingerprint = hashlib.sha256(
                f"{status}:{message}".encode("utf-8")
            ).hexdigest()[:32]
            store = self._missions()
            event, created = store.append_central(
                request.match_info["mission_id"],
                {
                    "schema_version": 1,
                    "mission_id": request.match_info["mission_id"],
                    "type": event_type,
                    "source": "central-hermes",
                    "correlation": {"producer_event_id": f"central:{fingerprint}"},
                    "payload": {payload_field: message},
                },
            )
            if created:
                await self._notify_mission(store, event)
            return web.json_response({
                "created": created,
                "event": event,
                "mission": store.projection(event["mission_id"]),
            }, status=201 if created else 200)
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)

'''
        text = replace(
            text,
            "    def _port_is_available(self) -> bool:",
            methods + "    def _port_is_available(self) -> bool:",
            "mission handlers",
        )
        return replace(
            text,
            '''            self._app.router.add_post("/api/sessions/{session_id}/chat/stream", self._handle_session_chat_stream)
            self._app.router.add_post("/v1/chat/completions", self._handle_chat_completions)''',
            '''            self._app.router.add_post("/api/sessions/{session_id}/chat/stream", self._handle_session_chat_stream)
            self._app.router.add_get("/api/missions", self._handle_list_missions)
            self._app.router.add_post("/api/missions", self._handle_create_mission)
            self._app.router.add_get("/api/missions/{mission_id}", self._handle_get_mission)
            self._app.router.add_post("/api/missions/{mission_id}/events", self._handle_append_mission_event)
            self._app.router.add_post("/api/missions/{mission_id}/terminal", self._handle_finish_mission)
            self._app.router.add_post("/v1/chat/completions", self._handle_chat_completions)''',
            "mission routes",
        )
    raise SystemExit(f"no transform for {relative}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source-commit", help=argparse.SUPPRESS)
    parser.add_argument("--print-patched-hashes", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.checkout.resolve()
    head = args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if head != UPSTREAM_COMMIT:
        raise SystemExit("upstream commit fingerprint mismatch")

    if args.print_patched_hashes:
        for relative, expected in FILES.items():
            path = root / relative
            if sha(path) != expected:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")
            print(f'{relative}={hashlib.sha256(transform(relative, path.read_text()).encode()).hexdigest()}')
        return

    runtime_hash = sha(RUNTIME_SOURCE)
    target = root / RUNTIME_TARGET
    statuses: list[str] = []
    source_paths: list[tuple[str, pathlib.Path]] = []
    for relative, expected in FILES.items():
        path = root / relative
        actual = sha(path)
        if actual == expected:
            statuses.append(f"{relative}: source-needs-overlay")
            source_paths.append((relative, path))
        elif actual == PATCHED_FILES[relative]:
            statuses.append(f"{relative}: exact-patched")
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {relative}")
    runtime_missing = not target.exists()
    if runtime_missing:
        statuses.append(f"{RUNTIME_TARGET}: source-needs-overlay")
    elif sha(target) == runtime_hash:
        statuses.append(f"{RUNTIME_TARGET}: exact-patched")
    else:
        raise SystemExit(f"upstream fingerprint mismatch: {RUNTIME_TARGET}")

    if args.check:
        print("\n".join(statuses))
        return

    for relative, path in source_paths:
        path.write_text(transform(relative, path.read_text()), encoding="utf-8")
        if sha(path) != PATCHED_FILES[relative]:
            raise SystemExit(f"overlay output fingerprint mismatch: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if runtime_missing:
        shutil.copyfile(RUNTIME_SOURCE, target)
    print("overlay applied" if source_paths or runtime_missing else "overlay already applied")


if __name__ == "__main__":
    main()
