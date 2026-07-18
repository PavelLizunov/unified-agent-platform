#!/usr/bin/env python3
"""Install the UAP mission module into the exact pinned Hermes checkout."""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import tempfile


UPSTREAM_COMMIT = "7c1a029553d87c43ecff8a3821336bc95872213b"
FILES = {
    "hermes_cli/commands.py": "028c9aa215dc7796bc9f12125bc6ebd03474e3d32f196e6dcd18c4f41841223a",
    "hermes_cli/kanban.py": "81ab118098c027c9737b2d8f623d2b47aef340cf7d5ac81362c1759777bc3702",
    "hermes_cli/kanban_db.py": "7ea3133148f82006840fa4883c8ce5e588945e26c1fde3889cb55a48ceec7c64",
    "hermes_cli/main.py": "188b313db842bc449143438b1630b733eeea1e17e9c8d7dd04c9be9c229e8e74",
    "gateway/run.py": "f25c56ba85a471e864264bad27e4dd656102a36199a78fc79c7540c95dbcea79",
    "gateway/platforms/api_server.py": "303f84d485c67a96d86f88badb5d111e842e5744448f30a18353e6a4c30c0240",  # gitleaks:allow -- pinned source SHA-256
}
PATCHED_FILES = {
    "hermes_cli/commands.py": "05a3e7d121b17984f0bcede0d9b2a20ecf14fa0066d6ac1f711ab8abfe117ab2",
    "hermes_cli/kanban.py": "f87ec03731d8a38acc198bfa77602354f30d57b14eeec01d31b080d6486d4305",
    "hermes_cli/kanban_db.py": "44f462aec94cdc8f93ee00986ba2c90929d3c0c4b7dc79950eb6bb62a63e1500",
    "hermes_cli/main.py": "6b5c98f313f2f99d751847ed893d40456fb4b046569dcb60d119a54e3f7d3132",
    "gateway/run.py": "7b83f8adaf44d9b85e492329060a61cfedda328346b69a11a1c2e3451484e5c8",
    "gateway/platforms/api_server.py": "e7ab1798573e78dbe26234ac625be82fa103cb429b71dabfc0a1b6186cf1c731",  # gitleaks:allow -- pinned patched SHA-256
}
BUILD1_RUNTIME_FILES = (
    "hermes_cli/kanban.py",
    "hermes_cli/kanban_db.py",
    "hermes_cli/main.py",
)
LEGACY_BUILD1_PATCHED_FILES = {
    "hermes_cli/kanban.py": (
        "924dcf6b2b277575d1d065aff209347ce5abc96ab158bc80b749f4c3552992cd",
        "0727f59ca0fe089e042b270612c2c472f05015c39d6a271f37d86319820e7b88",
        "92d6c82cf7c7adf3eace25173aa00a8434367a4403f14942fee60013056bd6bb",
    ),
    "hermes_cli/kanban_db.py": (
        "0af7473294f6ed83bdf9ad42adaa7837b40feffb12c53b41de7ec43b2ceece87",
    ),
}
RUNTIME_SOURCE = pathlib.Path(__file__).with_name("runtime.py")
RUNTIME_TARGET = "hermes_cli/uap_missions.py"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"overlay fragment mismatch: {name}")
    return text.replace(old, new, 1)


def atomic_write(path: pathlib.Path, text: str) -> None:
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(text)
            temporary = pathlib.Path(handle.name)
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        temporary.chmod(mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def transform(relative: str, text: str) -> str:
    if relative == "hermes_cli/commands.py":
        return replace(
            text,
            '    CommandDef("status", "Show session, model, token, and context info", "Session"),',
            '    CommandDef("status", "Show session, model, token, and context info", "Session"),\n'
            '    CommandDef("mission", "Show, bind, or answer one central UAP mission", "Session",\n'
            '               args_hint="[mission-id | answer <text>]", gateway_only=True),',
            "mission command",
        )
    if relative == "hermes_cli/kanban.py":
        text = replace(
            text,
            '''    p_claim.add_argument("--ttl", type=int, default=kb.DEFAULT_CLAIM_TTL_SECONDS,
                         help="Claim TTL in seconds (default: 900)")''',
            '''    p_claim.add_argument("--ttl", type=int, default=kb.DEFAULT_CLAIM_TTL_SECONDS,
                         help="Claim TTL in seconds (default: 900)")
    p_claim.add_argument("--claimer", default=None, help=argparse.SUPPRESS)''',
            "explicit claim provenance option",
        )
        text = replace(
            text,
            '''        task = kb.claim_task(conn, args.task_id, ttl_seconds=args.ttl)''',
            '''        task = kb.claim_task(
            conn, args.task_id, ttl_seconds=args.ttl, claimer=args.claimer
        )''',
            "explicit claim provenance binding",
        )
        text = replace(
            text,
            '''    author = _profile_author() if reason else None
    failed: list[str] = []''',
            '''    failed: list[str] = []''',
            "atomic unblock audit author removal",
        )
        text = replace(
            text,
            '''            if reason:
                kb.add_comment(conn, tid, author, f"UNBLOCK: {reason}")
            if not kb.unblock_task(conn, tid):''',
            '''            if not kb.unblock_task(conn, tid, reason=reason):''',
            "atomic unblock audit reference",
        )
        text = replace(
            text,
            '''    p_gc.add_argument("--log-retention-days", type=int, default=30,
                      help="Delete worker log files older than N days (default: 30)")''',
            '''    p_gc.add_argument("--log-retention-days", type=int, default=30,
                      help="Delete worker log files older than N days (default: 30)")
    p_gc.add_argument("--require-idle", action="store_true",
                      help="Fail closed unless the board is idle while old logs are removed")''',
            "atomic idle GC option",
        )
        return replace(
            text,
            '''def _cmd_gc(args: argparse.Namespace) -> int:
    """Remove scratch workspaces of archived tasks, prune old events, and
    delete old worker logs."""
    import shutil
    scratch_root = kb.workspaces_root()
    removed_ws = 0
    with kb.connect_closing() as conn:
        rows = conn.execute(
            "SELECT id, workspace_kind, workspace_path FROM tasks WHERE status = 'archived'"
        ).fetchall()
    for row in rows:
        if row["workspace_kind"] != "scratch":
            continue
        path = Path(row["workspace_path"] or (scratch_root / row["id"]))
        try:
            path = path.resolve()
        except OSError:
            continue
        try:
            path.relative_to(scratch_root.resolve())
        except ValueError:
            # Safety: never delete outside the scratch root.
            continue
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed_ws += 1

    event_days = getattr(args, "event_retention_days", 30)
    log_days = getattr(args, "log_retention_days", 30)
    with kb.connect_closing() as conn:
        removed_events = kb.gc_events(
            conn, older_than_seconds=event_days * 24 * 3600,
        )
    removed_logs = kb.gc_worker_logs(
        older_than_seconds=log_days * 24 * 3600,
    )
    print(f"GC complete: {removed_ws} workspace(s), "
          f"{removed_events} event row(s), {removed_logs} log file(s) removed")
    return 0''',
            '''def _cmd_gc(args: argparse.Namespace) -> int:
    """Remove scratch workspaces of archived tasks, prune old events, and
    delete old worker logs."""
    import shutil
    import stat
    import sys
    try:
        scratch_root = kb.workspaces_root().resolve()
    except (OSError, RuntimeError) as error:
        print(
            f"GC failed: scratch root: {type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    event_days = getattr(args, "event_retention_days", 30)
    log_days = getattr(args, "log_retention_days", 30)
    removed_logs = None
    if getattr(args, "require_idle", False):
        with kb.connect_closing() as conn:
            with kb.write_txn(conn):
                if conn.execute(
                    "SELECT 1 FROM tasks WHERE status NOT IN ('done', 'archived') LIMIT 1"
                ).fetchone():
                    print("GC deferred: board is not idle")
                    return 3
                try:
                    removed_logs = kb.gc_worker_logs(
                        older_than_seconds=log_days * 24 * 3600,
                        strict=True,
                    )
                except OSError as error:
                    print(
                        f"GC failed: worker log cleanup: {type(error).__name__}",
                        file=sys.stderr,
                    )
                    return 1

    removed_ws = 0
    with kb.connect_closing() as conn:
        rows = conn.execute(
            "SELECT id, workspace_kind, workspace_path FROM tasks WHERE status = 'archived'"
        ).fetchall()
    for row in rows:
        if row["workspace_kind"] != "scratch":
            continue
        path = Path(row["workspace_path"] or (scratch_root / row["id"]))
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            print(
                f"GC failed: scratch workspace path: {type(error).__name__}",
                file=sys.stderr,
            )
            return 1
        try:
            path.relative_to(scratch_root)
        except ValueError:
            print("GC failed: scratch workspace is outside the scratch root", file=sys.stderr)
            return 1
        if path == scratch_root:
            print("GC failed: scratch workspace is the scratch root", file=sys.stderr)
            return 1
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            print(
                f"GC failed: scratch workspace inspection: {type(error).__name__}",
                file=sys.stderr,
            )
            return 1
        if not stat.S_ISDIR(mode):
            print("GC failed: scratch workspace is not a directory", file=sys.stderr)
            return 1
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as error:
            print(
                f"GC failed: scratch workspace cleanup: {type(error).__name__}",
                file=sys.stderr,
            )
            return 1
        removed_ws += 1

    with kb.connect_closing() as conn:
        removed_events = kb.gc_events(
            conn, older_than_seconds=event_days * 24 * 3600,
        )
    if removed_logs is None:
        try:
            removed_logs = kb.gc_worker_logs(
                older_than_seconds=log_days * 24 * 3600,
                strict=True,
            )
        except OSError as error:
            print(
                f"GC failed: worker log cleanup: {type(error).__name__}",
                file=sys.stderr,
            )
            return 1
    print(f"GC complete: {removed_ws} workspace(s), "
          f"{removed_events} event row(s), {removed_logs} log file(s) removed")
    return 0''',
            "atomic idle GC",
        )
    if relative == "hermes_cli/kanban_db.py":
        text = replace(
            text,
            "import sqlite3\nimport subprocess",
            "import sqlite3\nimport stat\nimport subprocess",
            "strict worker log file type",
        )
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
        text = replace(
            text,
            '''        conn = _sqlite_connect(path)
        try:''',
            '''        conn = _sqlite_connect(path)
        _harden_db_permissions(path)
        try:''',
            "init-path Kanban permissions",
        )
        text = replace(
            text,
            '''def unblock_task(conn: sqlite3.Connection, task_id: str) -> bool:
    """Transition ``blocked``/``scheduled`` -> ready or todo.''',
            '''def unblock_task(
    conn: sqlite3.Connection, task_id: str, *, reason: Optional[str] = None
) -> bool:
    """Transition ``blocked``/``scheduled`` -> ready or todo.''',
            "atomic unblock audit signature",
        )
        text = replace(
            text,
            '''    state) holds for the rest of this function's lifetime.
    """
    now = int(time.time())
    with write_txn(conn):''',
            '''    state) holds for the rest of this function's lifetime.
    """
    if reason is not None:
        reason = reason.strip()
        if not reason or len(reason) > 256:
            raise ValueError("unblock reason must contain 1..256 characters")
    now = int(time.time())
    with write_txn(conn):''',
            "atomic unblock audit validation",
        )
        text = replace(
            text,
            '''        _append_event(
            conn, task_id, "unblocked",
            {"status": new_status} if new_status != "ready" else None,
        )''',
            '''        payload = {} if new_status == "ready" else {"status": new_status}
        if reason:
            payload["reason"] = reason
        _append_event(conn, task_id, "unblocked", payload or None)''',
            "atomic unblock audit event",
        )
        return replace(
            text,
            '''def gc_worker_logs(
    *, older_than_seconds: int = 30 * 24 * 3600,
    board: Optional[str] = None,
) -> int:
    """Delete worker log files older than ``older_than_seconds``. Returns
    the number of files removed. Kept separate from ``gc_events`` because
    log files live on disk, not in SQLite. Scoped to ``board`` (defaults
    to the active board) — per-board isolation means deleting logs from
    board A cannot touch board B's logs."""
    log_dir = worker_logs_dir(board=board)
    if not log_dir.exists():
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for p in log_dir.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed''',
            '''def gc_worker_logs(
    *, older_than_seconds: int = 30 * 24 * 3600,
    board: Optional[str] = None,
    strict: bool = False,
) -> int:
    """Delete worker log files older than ``older_than_seconds``. Returns
    the number of files removed. Kept separate from ``gc_events`` because
    log files live on disk, not in SQLite. Scoped to ``board`` (defaults
    to the active board) — per-board isolation means deleting logs from
    board A cannot touch board B's logs."""
    log_dir = worker_logs_dir(board=board)
    try:
        entries = list(log_dir.iterdir())
    except FileNotFoundError:
        return 0
    except OSError:
        if strict:
            raise
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for p in entries:
        try:
            metadata = p.stat()
            if stat.S_ISREG(metadata.st_mode) and metadata.st_mtime < cutoff:
                p.unlink()
                removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            if strict:
                raise
            continue
    return removed''',
            "strict worker log GC",
        )
    if relative == "hermes_cli/main.py":
        text = replace(
            text,
            '''    if hasattr(args, "func"):
        args.func(args)''',
            '''    if hasattr(args, "func"):
        return args.func(args)''',
            "subcommand exit propagation",
        )
        return replace(
            text,
            '''if __name__ == "__main__":
    main()''',
            '''if __name__ == "__main__":
    raise SystemExit(main())''',
            "module exit propagation",
        )
    if relative == "gateway/run.py":
        text = replace(
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
            if requested == "answer" or requested.startswith("answer "):
                mission_id = store.bound_mission(platform, chat_id, thread_id)
                answer = requested[len("answer"):].strip()
                if not mission_id:
                    return "No mission is bound to this chat. Use /mission <mission-id> first."
                if not answer:
                    return "Usage: /mission answer <your answer>"
                try:
                    from agent.redact import redact_sensitive_text

                    view = store.projection(mission_id)
                    question = view.get("question")
                    if not isinstance(question, dict):
                        return "The bound mission has no open owner question."
                    store.answer(
                        mission_id,
                        question["question_id"],
                        redact_sensitive_text(answer, force=True),
                    )
                    return telegram_text(store.projection(mission_id))
                except MissionError as error:
                    return f"Mission unavailable: {error}"
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
        text = replace(
            text,
            '''        if canonical == "voice":
            return await self._handle_voice_command(event)

        if self._draining:''',
            '''        if canonical == "voice":
            return await self._handle_voice_command(event)

        if (
            not command
            and not is_internal
            and source.platform
            and source.platform.value == "telegram"
        ):
            event._uap_owner_goal = True

        if self._draining:''',
            "ordinary Telegram mission intake marker",
        )
        return replace(
            text,
            '''        # Build session context
        context = build_session_context(source, self.config, session_entry)''',
            '''        if getattr(event, "_uap_owner_goal", False):
            from agent.redact import redact_sensitive_text
            from hermes_cli.uap_missions import MissionError, MissionStore, telegram_text

            try:
                source_message_id = str(event.message_id or "").strip()
                if not source_message_id:
                    raise MissionError("mission intake requires a stable source message")
                store = MissionStore.default()
                accepted, _ = store.ingest_owner_goal(
                    redact_sensitive_text(event.text, force=True),
                    platform="telegram",
                    source_message_id=source_message_id,
                    session_id=session_entry.session_id,
                    chat_id=str(source.chat_id or ""),
                    thread_id=str(source.thread_id or ""),
                )
                response = telegram_text(store.projection(accepted["mission_id"]))
                if not self.session_store.has_platform_message_id(
                    session_entry.session_id, source_message_id
                ):
                    self.session_store.append_to_transcript(
                        session_entry.session_id,
                        {
                            "role": "user",
                            "content": event.text,
                            "platform_message_id": source_message_id,
                            "timestamp": event.timestamp,
                        },
                    )
                    self.session_store.append_to_transcript(
                        session_entry.session_id,
                        {
                            "role": "assistant",
                            "content": response,
                            "platform_message_id": f"uap-mission:{source_message_id}",
                        },
                    )
                return response
            except MissionError as error:
                return f"Mission intake unavailable: {error}"

        # Build session context
        context = build_session_context(source, self.config, session_entry)''',
            "ordinary Telegram mission intake",
        )
    if relative == "gateway/platforms/api_server.py":
        text = replace(
            text,
            "from agent.redact import redact_sensitive_text",
            "from agent.redact import redact_sensitive_text\n"
            "from hermes_cli.uap_missions import (\n"
            "    MissionError, MissionStore, NOTIFICATION_SEND_TIMEOUT_SECONDS,\n"
            "    notify_subscribers, owner_key_valid, producer_key_valid,\n"
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
        stream_marker = '''    async def _handle_session_chat_stream(self, request: "web.Request") -> "web.StreamResponse":'''
        if text.count(stream_marker) != 1:
            raise RuntimeError("overlay anchor mismatch for session chat stream")
        before_stream, stream_and_tail = text.split(stream_marker, 1)
        stream_and_tail = replace(
            stream_and_tail,
            '''        user_message, err = _session_chat_user_message(body)
        if err is not None:
            return err
        system_prompt = body.get("system_message") or body.get("instructions")''',
            '''        user_message, err = _session_chat_user_message(body)
        if err is not None:
            return err
        source_message_id = body.get("source_message_id")
        if source_message_id is not None:
            try:
                if not isinstance(user_message, str):
                    raise MissionError("mission intake requires a text goal")
                store = self._missions()
                accepted, _ = store.ingest_owner_goal(
                    redact_sensitive_text(user_message, force=True),
                    platform="workspace",
                    source_message_id=source_message_id,
                    session_id=session_id,
                )
                mission_id = accepted["mission_id"]
                response_text = (
                    f"Mission {mission_id} accepted. Delivery continues automatically; "
                    "no owner action is required."
                )
                database = self._ensure_session_db()
                receipt = f"workspace:{source_message_id}"
                if not database.has_platform_message_id(session_id, receipt):
                    database.append_message(
                        session_id, "user", user_message, platform_message_id=receipt
                    )
                    database.append_message(
                        session_id,
                        "assistant",
                        response_text,
                        platform_message_id=f"{receipt}:mission",
                    )
            except MissionError as error:
                return web.json_response(
                    _openai_error(str(error), code="mission_intake_failed"), status=400
                )
            digest = hashlib.sha256(mission_id.encode("utf-8")).hexdigest()[:32]
            run_id = f"run_{digest}"
            message_id = f"msg_{digest}"
            now = time.time()
            events = (
                ("run.started", {
                    "session_id": session_id, "run_id": run_id, "seq": 1, "ts": now,
                    "user_message": {"role": "user", "content": user_message},
                }),
                ("message.started", {
                    "session_id": session_id, "run_id": run_id, "seq": 2, "ts": now,
                    "message": {"id": message_id, "role": "assistant"},
                }),
                ("assistant.completed", {
                    "session_id": session_id, "run_id": run_id, "seq": 3, "ts": now,
                    "message_id": message_id, "content": response_text,
                    "completed": True, "partial": False, "interrupted": False,
                }),
                ("run.completed", {
                    "session_id": session_id, "run_id": run_id, "seq": 4, "ts": now,
                    "message_id": message_id, "completed": True,
                    "messages": [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": response_text},
                    ],
                    "usage": {},
                }),
                ("done", {
                    "session_id": session_id, "run_id": run_id, "seq": 5, "ts": now,
                }),
            )
            payload = "".join(
                f"event: {name}\\ndata: {json.dumps(data, ensure_ascii=False)}\\n\\n"
                for name, data in events
            ).encode("utf-8")
            return web.Response(
                body=payload,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Hermes-Session-Id": session_id,
                },
            )
        system_prompt = body.get("system_message") or body.get("instructions")''',
            "ordinary Workspace mission intake",
        )
        text = before_stream + stream_marker + stream_and_tail
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
            notification = store.pending_terminal_notification(
                request.query.get("dispatch_profile")
            )
            if notification is not None:
                await self._notify_mission(store, notification)
                if store.completion_notification(notification["mission_id"]) is None:
                    store.restore_parent_after_terminal_notification(
                        notification["mission_id"]
                    )
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
            if not isinstance(body, dict):
                raise MissionError("mission request must be an object")
            store = self._missions()
            producer_key = request.headers.get("X-Hermes-Mission-Producer-Key")
            owner_key = request.headers.get("X-Hermes-Mission-Owner-Key")
            if producer_key is not None and owner_key is not None:
                return web.json_response(
                    {"error": "Ambiguous mission capability"}, status=401
                )
            if producer_key is not None:
                if not producer_key_valid(producer_key):
                    return web.json_response(
                        {"error": "Invalid mission producer key"}, status=401
                    )
                event, created = store.accept(
                    redact_sensitive_text(body.get("goal"), force=True),
                    mission_id=body.get("mission_id"),
                    session_id=body.get("session_id"),
                    run_id=body.get("run_id"),
                    dispatch_profile=body.get("dispatch_profile"),
                    parent_mission_id=body.get("parent_mission_id"),
                )
            else:
                if not owner_key_valid(owner_key):
                    return web.json_response(
                        {"error": "Invalid mission owner key"}, status=401
                    )
                allowed = {
                    "goal", "platform", "source_message_id", "session_id",
                    "chat_id", "thread_id",
                }
                if unknown := set(body) - allowed:
                    raise MissionError(
                        "unknown owner intake fields: " + ", ".join(sorted(unknown))
                    )
                for name in allowed & body.keys():
                    if not isinstance(body[name], str):
                        raise MissionError(f"invalid {name}")
                event, created = store.ingest_owner_goal(
                    redact_sensitive_text(body.get("goal"), force=True),
                    platform=body.get("platform"),
                    source_message_id=body.get("source_message_id"),
                    session_id=body.get("session_id"),
                    chat_id=body.get("chat_id"),
                    thread_id=body.get("thread_id"),
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
            completed = store.complete_if_ready(mission_id)
            if completed is None and created:
                await self._notify_mission(store, event)
            terminal = completed[0] if completed is not None else store.completion_notification(mission_id)
            if terminal is not None:
                await self._notify_mission(store, terminal)
            if (
                store.projection(mission_id)["status"] in {"completed", "failed", "cancelled"}
                and store.completion_notification(mission_id) is None
            ):
                store.restore_parent_after_terminal_notification(mission_id)
            return web.json_response({
                "created": created,
                "event": event,
                "mission": store.projection(event["mission_id"]),
            }, status=201 if created else 200)
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_answer_mission(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not owner_key_valid(request.headers.get("X-Hermes-Mission-Owner-Key")):
            return web.json_response({"error": "Invalid mission owner key"}, status=401)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"question_id", "text"}:
                raise MissionError("mission answer must contain question_id and text")
            store = self._missions()
            event, created = store.answer(
                request.match_info["mission_id"],
                body.get("question_id"),
                redact_sensitive_text(body.get("text"), force=True),
            )
            await self._notify_mission(store, event)
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
            await self._notify_mission(store, event, defer=False)
            store.restore_parent_after_terminal_notification(event["mission_id"])
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
            self._app.router.add_post("/api/missions/{mission_id}/answer", self._handle_answer_mission)
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
    parser.add_argument("--build1-runtime", action="store_true")
    args = parser.parse_args()
    root = args.checkout.resolve()
    head = args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if head != UPSTREAM_COMMIT:
        raise SystemExit("upstream commit fingerprint mismatch")

    selected_files = (
        {relative: FILES[relative] for relative in BUILD1_RUNTIME_FILES}
        if args.build1_runtime
        else FILES
    )
    if args.print_patched_hashes:
        for relative, expected in selected_files.items():
            path = root / relative
            if sha(path) != expected:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")
            print(f'{relative}={hashlib.sha256(transform(relative, path.read_text()).encode()).hexdigest()}')
        return

    runtime_hash = sha(RUNTIME_SOURCE)
    target = root / RUNTIME_TARGET
    statuses: list[str] = []
    source_paths: list[tuple[str, pathlib.Path, str]] = []
    for relative, expected in selected_files.items():
        path = root / relative
        actual = sha(path)
        if actual == expected:
            statuses.append(f"{relative}: source-needs-overlay")
            source_paths.append((relative, path, path.read_text()))
        elif actual == PATCHED_FILES[relative]:
            statuses.append(f"{relative}: exact-patched")
        elif (
            args.build1_runtime
            and actual in LEGACY_BUILD1_PATCHED_FILES.get(relative, ())
        ):
            pristine = subprocess.check_output(
                ["git", "show", f"{UPSTREAM_COMMIT}:{relative}"],
                cwd=root,
                text=True,
            )
            if hashlib.sha256(pristine.encode()).hexdigest() != expected:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")
            statuses.append(f"{relative}: legacy-needs-overlay")
            source_paths.append((relative, path, pristine))
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {relative}")
    runtime_missing = not args.build1_runtime and not target.exists()
    if not args.build1_runtime:
        if runtime_missing:
            statuses.append(f"{RUNTIME_TARGET}: source-needs-overlay")
        elif sha(target) == runtime_hash:
            statuses.append(f"{RUNTIME_TARGET}: exact-patched")
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {RUNTIME_TARGET}")

    if args.check:
        print("\n".join(statuses))
        return

    for relative, path, source_text in source_paths:
        atomic_write(path, transform(relative, source_text))
        if sha(path) != PATCHED_FILES[relative]:
            raise SystemExit(f"overlay output fingerprint mismatch: {relative}")
    if not args.build1_runtime:
        target.parent.mkdir(parents=True, exist_ok=True)
        if runtime_missing:
            atomic_write(target, RUNTIME_SOURCE.read_text(encoding="utf-8"))
    print("overlay applied" if source_paths or runtime_missing else "overlay already applied")


if __name__ == "__main__":
    main()
