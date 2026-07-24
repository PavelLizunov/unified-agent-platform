#!/usr/bin/env python3
"""Install the UAP mission module into the exact pinned Hermes checkout."""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import tempfile


UPSTREAM_COMMIT = "3ef6bbd201263d354fd83ec55b3c306ded2eb72a"
FILES = {
    "hermes_cli/commands.py": "41d16ee11e4a358313e3b20bec9a3e243857f6d4a0b969bf26b8f0e7975cde9f",
    "hermes_cli/kanban.py": "c91d1542d8fff562e77180de9feb83e6fda608ef5be6e9c5d524eea3c28ba4f4",
    "hermes_cli/kanban_db.py": "6adf52e2e8445afe51ce1d3bbf1676ca550d525c9c17035bde026587d46e9c3b",
    "hermes_cli/main.py": "d6bf89a33fb708376a7ab354cff8081a3c3726dbfb91d84bbb679cd667db596c",
    "gateway/run.py": "c6e0f443772e4a8a7eac0d9ccf9a4f659de5fc5493c572a69a46e4c61a8aa966",
    "gateway/platforms/api_server.py": "2b8725863c99617b756cfce44567bf8eec9ccf6c7a946269c1ae42260cafa0de",  # gitleaks:allow -- pinned source SHA-256
    "plugins/platforms/telegram/adapter.py": "b4fab048d4986ab49615a1b5abb0dafeade4a25196578bf93cb065b793d67c8b",
}
PATCHED_FILES = {
    "hermes_cli/commands.py": "baa727344aacefd6ba734215e10177085243a606db90b8db0088c0508db2cab0",
    "hermes_cli/kanban.py": "8e2ee10eaf89b769b7a232ea490e6fe6e909db4c8173e7d1447ba67e3bca1045",
    "hermes_cli/kanban_db.py": "482d53c69db8013afd52f431e00627579c5804262cc2a81bb3a3c2d21b0d7128",
    "hermes_cli/main.py": "be64ed4ff2c3abcff3616cf8ae5e242fa4fc80a0871413a931e06fe2d33627cb",
    "gateway/run.py": "5377ee10307a7913e5b1e057052fe3b4a673f07efca73c5e91f78b3c77f25ef5",
    "gateway/platforms/api_server.py": "a37559cbaa226474683e089271034874c3b48094dd28fa10b63e36a66988cb17",  # gitleaks:allow -- pinned patched SHA-256
    "plugins/platforms/telegram/adapter.py": "1b4864a3622b4d88dfdba8ec9b60b132bf4d0b1a06ab41a125157281f6dcbdca",
}
BUILD1_RUNTIME_FILES = (
    "hermes_cli/kanban.py",
    "hermes_cli/kanban_db.py",
    "hermes_cli/main.py",
)
# Older legacy build1 patched hashes that still trigger a re-overlay from
# pristine (legacy-needs-overlay).  The current v0.18.0 patched hashes are NOT
# listed here: they equal BUILD1_PATCHED_FILES and are caught earlier as
# exact-patched, so listing them would be dead.  These hashes never affect the
# rendered ConfigMap, which is generated from the v0.19 source.
LEGACY_BUILD1_PATCHED_FILES = {
    "hermes_cli/kanban.py": (
        "924dcf6b2b277575d1d065aff209347ce5abc96ab158bc80b749f4c3552992cd",
        "0727f59ca0fe089e042b270612c2c472f05015c39d6a271f37d86319820e7b88",
        "92d6c82cf7c7adf3eace25173aa00a8434367a4403f14942fee60013056bd6bb",
    ),
    "hermes_cli/kanban_db.py": (
        "0af7473294f6ed83bdf9ad42adaa7837b40feffb12c53b41de7ec43b2ceece87",
    ),
    # main.py's only legacy hash equalled BUILD1_PATCHED_FILES (caught earlier as
    # exact-patched), so it was dead and removed; no legacy main.py hash remains.
    "hermes_cli/main.py": (),
}

# Build-1 runs the PREVIOUS upstream pin (v0.18) until it is independently
# upgraded.  These tables are frozen at the v0.18 pristine/patched hashes so
# --build1-runtime never depends on the central UPSTREAM_COMMIT.
BUILD1_UPSTREAM_COMMIT = "7c1a029553d87c43ecff8a3821336bc95872213b"
BUILD1_FILES = {
    "hermes_cli/kanban.py": "81ab118098c027c9737b2d8f623d2b47aef340cf7d5ac81362c1759777bc3702",
    "hermes_cli/kanban_db.py": "7ea3133148f82006840fa4883c8ce5e588945e26c1fde3889cb55a48ceec7c64",
    "hermes_cli/main.py": "188b313db842bc449143438b1630b733eeea1e17e9c8d7dd04c9be9c229e8e74",
}
BUILD1_PATCHED_FILES = {
    "hermes_cli/kanban.py": "f87ec03731d8a38acc198bfa77602354f30d57b14eeec01d31b080d6486d4305",
    "hermes_cli/kanban_db.py": "44f462aec94cdc8f93ee00986ba2c90929d3c0c4b7dc79950eb6bb62a63e1500",
    "hermes_cli/main.py": "6b5c98f313f2f99d751847ed893d40456fb4b046569dcb60d119a54e3f7d3132",
}
RUNTIME_SOURCE = pathlib.Path(__file__).with_name("runtime.py")
RUNTIME_TARGET = "hermes_cli/uap_missions.py"
MEDIA_SOURCE = pathlib.Path(__file__).with_name("media.py")
MEDIA_TARGET = "hermes_cli/uap_media.py"


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
        text = replace(
            text,
            '    CommandDef("status", "Show session, model, token, and context info", "Session"),',
            '    CommandDef("status", "Показать состояние текущей сессии", "Session"),\n'
            '    CommandDef("projects", "Показать разрешённые проекты", "Session", gateway_only=True),\n'
            '    CommandDef("mission", "Показать текущую автономную задачу", "Session",\n'
            '               args_hint="[mission-id | answer <text>]", gateway_only=True),',
            "mission command",
        )
        text = replace(
            text,
            '    CommandDef("stop", "Kill all running background processes", "Session"),',
            '    CommandDef("stop", "Остановить текущий ответ", "Session"),',
            "owner stop description",
        )
        text = replace(
            text,
            '    CommandDef("help", "Show available commands", "Info"),',
            '    CommandDef("help", "Показать короткую справку", "Info"),',
            "owner help description",
        )
        text = replace(
            text,
            '''def gateway_help_lines() -> list[str]:
    """Generate gateway help text lines from the registry."""
    overrides = _resolve_config_gates()''',
            '''def gateway_help_lines() -> list[str]:
    """Generate gateway help text lines from the registry."""
    owner_commands = {
        value.strip() for value in os.environ.get("HERMES_OWNER_COMMANDS", "").split(",")
        if value.strip()
    }
    overrides = _resolve_config_gates()''',
            "owner help command policy",
        )
        text = replace(
            text,
            '''    for cmd in COMMAND_REGISTRY:
        if not _is_gateway_available(cmd, overrides):''',
            '''    for cmd in COMMAND_REGISTRY:
        if owner_commands and cmd.name not in owner_commands:
            continue
        if not _is_gateway_available(cmd, overrides):''',
            "owner help command filter",
        )
        return replace(
            text,
            '''    core_commands = _prioritize_telegram_menu_commands(list(telegram_bot_commands()))
    reserved_names = {n for n, _ in core_commands}''',
            '''    owner_commands = {
        value.strip() for value in os.environ.get("HERMES_OWNER_COMMANDS", "").split(",")
        if value.strip()
    }
    core_commands = _prioritize_telegram_menu_commands(list(telegram_bot_commands()))
    if owner_commands:
        core_commands = [entry for entry in core_commands if entry[0] in owner_commands]
        return core_commands[:max_commands], max(0, len(core_commands) - max_commands)
    reserved_names = {n for n, _ in core_commands}''',
            "owner Telegram menu filter",
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
    if relative == "plugins/platforms/telegram/adapter.py":
        text = replace(
            text,
            '''                file_obj = await msg.voice.get_file()
                audio_bytes = await file_obj.download_as_bytearray()''',
            '''                from hermes_cli.uap_media import download_telegram_file
                file_obj, audio_bytes = await download_telegram_file(msg.voice)''',
            "bounded Telegram voice download retry",
        )
        text = replace(
            text,
            '''                file_obj = await msg.audio.get_file()
                audio_bytes = await file_obj.download_as_bytearray()''',
            '''                from hermes_cli.uap_media import download_telegram_file
                file_obj, audio_bytes = await download_telegram_file(msg.audio)''',
            "bounded Telegram audio download retry",
        )
        text = replace(
            text,
            '''            await msg.reply_text(
                f"\\u26a0\\ufe0f Couldn't download your {kind}{named} "
                f"({exc.__class__.__name__}). Please try sending it again."
            )''',
            '''            await msg.reply_text(
                "\\u26a0\\ufe0f Telegram не отдал файл после 3 автоматических попыток. "
                "Отправьте его ещё раз или напишите текстом."
            )''',
            "Russian Telegram media failure",
        )
        return replace(
            text,
            '''        named = f" ({display_name})" if display_name else ""''',
            '''        event._uap_media_download_failed = True
        named = f" ({display_name})" if display_name else ""''',
            "failed Telegram media marker",
        )
    if relative == "gateway/run.py":
        owner_help = (
            "Напишите обычным сообщением, что нужно сделать. "
            "Hermes сам создаст задачу, выберет разрешённые модели и доведёт работу до результата.\n\n"
            "Если задача ждёт вашего ответа — просто напишите его обычным сообщением.\n\n"
            "/projects — разрешённые проекты\n"
            "/mission — текущая задача\n"
            "/status — состояние сессии\n"
            "/stop — остановить текущий ответ"
        )
        text = replace(
            text,
            '''                if _cmd_def_inner.name == "help":
                    return await self._handle_help_command(event)''',
            f'''                if _cmd_def_inner.name == "help":
                    if os.environ.get("HERMES_OWNER_COMMANDS", "").strip():
                        return {owner_help!r}
                    return await self._handle_help_command(event)''',
            "owner help during active run",
        )
        text = replace(
            text,
            '''        if canonical == "help":
            return await self._handle_help_command(event)''',
            f'''        if canonical == "help":
            if os.environ.get("HERMES_OWNER_COMMANDS", "").strip():
                return {owner_help!r}
            return await self._handle_help_command(event)''',
            "owner help",
        )
        text = replace(
            text,
            '''        if canonical == "status":
            return await self._handle_status_command(event)

        if canonical == "agents":''',
            '''        if canonical == "status":
            return await self._handle_status_command(event)

        if canonical == "mission":
            from hermes_cli.uap_missions import (
                MissionError, MissionProjectRequired, MissionStore, telegram_text,
            )

            store = MissionStore.default()
            platform = source.platform.value if source.platform else "unknown"
            chat_id = str(source.chat_id)
            thread_id = str(source.thread_id or "")
            requested = event.get_command_args().strip()
            if requested == "answer" or requested.startswith("answer "):
                mission_id = store.bound_mission(platform, chat_id, thread_id)
                answer = requested[len("answer"):].strip()
                if not mission_id:
                    return "К этому чату не привязана задача. Сначала укажите /mission <mission-id>."
                if not answer:
                    return "Формат: /mission answer <ваш ответ>"
                try:
                    from agent.redact import redact_sensitive_text

                    view = store.projection(mission_id)
                    question = view.get("question")
                    if not isinstance(question, dict):
                        return "У текущей задачи нет открытого вопроса владельцу."
                    store.answer(
                        mission_id,
                        question["question_id"],
                        redact_sensitive_text(answer, force=True),
                    )
                    return telegram_text(store.projection(mission_id))
                except MissionError as error:
                    return f"Задача недоступна: {error}"
            mission_id = requested or store.bound_mission(platform, chat_id, thread_id) or store.latest()
            if not mission_id:
                return "Автономных задач пока нет."
            try:
                if requested:
                    store.bind(mission_id, platform, chat_id, thread_id)
                return telegram_text(store.projection(mission_id))
            except MissionError as error:
                return f"Задача недоступна: {error}"

        if canonical == "projects":
            from hermes_cli.uap_missions import public_intake_projects

            projects = public_intake_projects("telegram")
            status_labels = {
                "ready": "Готовы к работе",
                "setup_required": "В реестре, профиль проверок готовится",
                "read_only": "Только просмотр",
                "archived": "Архив",
            }
            lines = [f"Проекты в GitHub: {len(projects)}"]
            for status in ("ready", "setup_required", "read_only", "archived"):
                names = [
                    project["label"] for project in projects
                    if project.get("status") == status
                ]
                if names:
                    lines.append(f"\\n{status_labels[status]} ({len(names)}):")
                    lines.append(" · ".join(names))
            lines.append(
                "\\nОбычную задачу можно запускать для проектов из раздела «Готовы к работе». "
                "Остальные уже известны Hermes, но не получат shell-доступ до установки точного профиля тестов."
            )
            return "\\n".join(lines)

        if canonical == "agents":''',
            "mission gateway handler",
        )
        text = replace(
            text,
            '''        if canonical == "voice":
            return await self._handle_voice_command(event)

        if self._draining:''',
            '''        if (
            canonical == "cancel"
            and source.platform
            and source.platform.value == "telegram"
        ):
            # /cancel is not an upstream Hermes command. Treat it as the
            # owner-facing mission draft escape without forwarding it to a model.
            command = None
            event.text = "отмена"

        if canonical == "voice":
            return await self._handle_voice_command(event)

        if getattr(event, "_uap_media_download_failed", False):
            return None

        if (
            not command
            and not is_internal
            and source.platform
            and source.platform.value == "telegram"
        ):
            from hermes_cli.uap_missions import (
                MissionError, MissionStore, image_generation_prompt, is_execution_goal,
                media_topic_pairs,
            )

            session_entry = self.session_store.get_or_create_session(source)
            source_message_id = str(event.message_id or "").strip()
            store = MissionStore.default()
            try:
                continuation = bool(
                    source_message_id
                    and store.owner_turn_continues_mission(
                        platform="telegram",
                        source_message_id=source_message_id,
                        session_id=session_entry.session_id,
                        chat_id=str(source.chat_id or ""),
                        thread_id=str(source.thread_id or ""),
                    )
                )
            except MissionError:
                continuation = True
            event._uap_owner_goal = bool(
                event.message_type in (MessageType.VOICE, MessageType.AUDIO)
                or image_generation_prompt(event.text or "")
                or (
                    str(source.chat_id or ""), str(source.thread_id or "")
                ) in media_topic_pairs()
                or is_execution_goal(event.text or "")
                or continuation
            )

        if self._draining:''',
            "ordinary Telegram mission intake marker",
        )
        text = replace(
            text,
            '''        # Build session context
        context = build_session_context(source, self.config, session_entry)''',
            '''        if getattr(event, "_uap_owner_goal", False):
            from agent.redact import redact_sensitive_text
            from hermes_cli.uap_missions import (
                image_generation_prompt, is_execution_goal,
                MissionError, MissionIntakeCancelled, MissionProjectRequired,
                MissionStore, notify_subscribers, telegram_text,
            )
            from hermes_cli.uap_media import execute_media_mission

            try:
                source_message_id = str(event.message_id or "").strip()
                if not source_message_id:
                    raise MissionError("mission intake requires a stable source message")
                goal_text = event.text or ""
                if any(
                    str(media_type).startswith("image/")
                    for media_type in (event.media_types or [])
                ):
                    raise MissionError(
                        "subscription image editing is unavailable: the production Codex adapter does not pass source images"
                    )
                if event.message_type in (MessageType.VOICE, MessageType.AUDIO):
                    audio_paths = [
                        path for index, path in enumerate(event.media_urls or [])
                        if (
                            (event.media_types[index] if index < len(event.media_types or []) else "").startswith("audio/")
                            or event.message_type in (MessageType.VOICE, MessageType.AUDIO)
                        )
                    ]
                    try:
                        _, transcripts = await self._enrich_message_with_transcription(
                            goal_text, audio_paths,
                        )
                    finally:
                        # Telegram caches inbound audio on the durable Hermes volume.
                        # Remove only files owned by that exact cache, on success or failure.
                        from gateway.platforms.base import get_audio_cache_dir
                        audio_cache = get_audio_cache_dir().resolve()
                        for audio_path in audio_paths:
                            try:
                                candidate = Path(audio_path)
                                if candidate.is_symlink():
                                    continue
                                candidate = candidate.resolve(strict=True)
                                if candidate.parent == audio_cache and candidate.is_file():
                                    candidate.unlink()
                            except OSError:
                                logger.warning("Failed to remove cached owner voice")
                    if not audio_paths or len(transcripts) != len(audio_paths):
                        raise MissionError(
                            "не удалось расшифровать голосовое сообщение; отправьте его ещё раз или напишите текстом"
                        )
                    goal_text = "\\n".join(transcripts)
                # The transcript is untrusted owner text. Redact before either
                # durable store sees it; STT has no authority beyond media decode.
                goal_text = redact_sensitive_text(goal_text, force=True)
                if (
                    event.message_type in (MessageType.VOICE, MessageType.AUDIO)
                    and not continuation
                    and image_generation_prompt(goal_text) is None
                    and not is_execution_goal(goal_text)
                ):
                    # Voice is only a transport. Once transcribed, ordinary
                    # conversation must follow the same admission rule as text.
                    event.text = goal_text
                    event.message_type = MessageType.TEXT
                    event.media_urls = []
                    event.media_types = []
                    event._uap_owner_goal = False
                    return await self._handle_message(event)
                store = MissionStore.default()
                accepted, _ = store.ingest_owner_turn(
                    goal_text,
                    platform="telegram",
                    source_message_id=source_message_id,
                    session_id=session_entry.session_id,
                    chat_id=str(source.chat_id or ""),
                    thread_id=str(source.thread_id or ""),
                )
                view = store.projection(accepted["mission_id"])
                if view.get("capability") == "media.image.generate":
                    view = await asyncio.to_thread(
                        execute_media_mission, store, accepted["mission_id"]
                    )
                response = telegram_text(view)
                artifact = store.media_artifact(accepted["mission_id"])
                if view.get("status") == "completed" and artifact:
                    terminal = store.events(accepted["mission_id"])[-1]

                    async def send_media(subscription, _text):
                        adapter = self.adapters.get(source.platform)
                        if adapter is None:
                            raise RuntimeError("Telegram adapter unavailable")
                        metadata = (
                            {"thread_id": subscription["thread_id"]}
                            if subscription["thread_id"] else None
                        )
                        result = await adapter.send_image_file(
                            subscription["chat_id"], artifact["path"],
                            caption="Изображение готово", metadata=metadata,
                        )
                        if result is not None and getattr(result, "success", True) is False:
                            raise RuntimeError(getattr(result, "error", "image delivery failed"))

                    await notify_subscribers(store, terminal, send_media)
                if not self.session_store.has_platform_message_id(
                    session_entry.session_id, source_message_id
                ):
                    self.session_store.append_to_transcript(
                        session_entry.session_id,
                        {
                            "role": "user",
                            "content": goal_text,
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
            except MissionIntakeCancelled:
                return (
                    "Выбор проекта отменён. Отправьте новую задачу обычным сообщением, "
                    "когда будете готовы."
                )
            except MissionProjectRequired as error:
                choices = "\\n".join(
                    f"• {project['label']} — {project['repository']}"
                    for project in error.projects
                )
                return (
                    "Для какого проекта выполнить задачу? Ответьте одним названием "
                    "или напишите «отмена»:\\n"
                    + choices
                )
            except MissionError as error:
                return f"Не удалось создать задачу: {error}"

        # Build session context
        context = build_session_context(source, self.config, session_entry)''',
            "ordinary Telegram mission intake",
        )
        text = replace(
            text,
            '''        def _stream_confirmed_final_delivery(
            consumer,
            final_text: str,
            *,
            previewed: bool = False,
        ) -> bool:
            """Return True only when the actual final reply reached the user."""
            if consumer is None:
                return False
            if getattr(consumer, "final_response_sent", False):
                return True
            if previewed:
                has_delivered_text = getattr(consumer, "has_delivered_text", None)
                if callable(has_delivered_text):
                    try:
                        return bool(has_delivered_text(final_text))
                    except Exception:
                        return False
            return False

        try:''',
            '''        def _stream_confirmed_final_delivery(
            consumer,
            final_text: str,
            *,
            previewed: bool = False,
        ) -> bool:
            """Return True only when the actual final reply reached the user."""
            if consumer is None:
                return False
            if getattr(consumer, "final_response_sent", False):
                return True
            if previewed:
                has_delivered_text = getattr(consumer, "has_delivered_text", None)
                if callable(has_delivered_text):
                    try:
                        return bool(has_delivered_text(final_text))
                    except Exception:
                        return False
            return False

        def _delivery_ledger_confirms_final_delivery(
            session_key_value: str,
            message_ref: str,
            final_text: str,
        ) -> bool:
            """Return True when the exact normal final send was acknowledged."""
            if not session_key_value or not message_ref or not final_text:
                return False
            try:
                from gateway import delivery_ledger as _delivery_ledger

                if not _delivery_ledger.ledger_enabled():
                    return False
                obligation_id = _delivery_ledger.compute_obligation_id(
                    session_key_value, message_ref, final_text,
                )
                with (
                    _delivery_ledger._DB_LOCK,
                    _delivery_ledger._connect() as connection,
                ):
                    row = connection.execute(
                        "SELECT state FROM delivery_obligations "
                        "WHERE obligation_id=?",
                        (obligation_id,),
                    ).fetchone()
                return bool(row and row[0] == "delivered")
            except Exception:
                logger.debug(
                    "delivery ledger confirmation lookup failed",
                    exc_info=True,
                )
                return False

        try:''',
            "queued follow-up delivery confirmation helper",
        )
        text = replace(
            text,
            '''                    _already_streamed = _stream_confirmed_final_delivery(
                        _sc,
                        first_response,
                        previewed=_previewed,
                    )
                    # Apply the same predicate as the normal completed-turn path.''',
            '''                    _already_streamed = _stream_confirmed_final_delivery(
                        _sc,
                        first_response,
                        previewed=_previewed,
                    )
                    _ledger_delivered = _delivery_ledger_confirms_final_delivery(
                        session_key,
                        str(getattr(event, "message_id", "") or ""),
                        first_response,
                    )
                    # Apply the same predicate as the normal completed-turn path.''',
            "queued follow-up delivery ledger lookup",
        )
        return replace(
            text,
            '''                    elif first_response and not _already_streamed:
                        try:
                            logger.info(
                                "Queued follow-up for session %s: final stream delivery not confirmed; sending first response before continuing.",
                                session_key or "?",
                            )
                            await adapter.send(
                                source.chat_id,
                                first_response,
                                metadata=_status_thread_metadata,
                            )
                        except Exception as e:
                            logger.warning("Failed to send first response before queued message: %s", e)
                    elif first_response:
                        logger.info(
                            "Queued follow-up for session %s: skipping resend because final streamed delivery was confirmed.",
                            session_key or "?",
                        )''',
            '''                    elif first_response and not (
                        _already_streamed or _ledger_delivered
                    ):
                        try:
                            logger.info(
                                "Queued follow-up for session %s: final delivery not confirmed; sending first response before continuing.",
                                session_key or "?",
                            )
                            await adapter.send(
                                source.chat_id,
                                first_response,
                                metadata=_status_thread_metadata,
                            )
                        except Exception as e:
                            logger.warning("Failed to send first response before queued message: %s", e)
                    elif first_response:
                        logger.info(
                            "Queued follow-up for session %s: skipping resend because final delivery was confirmed (streamed=%s ledger=%s).",
                            session_key or "?",
                            _already_streamed,
                            _ledger_delivered,
                        )''',
            "queued follow-up duplicate final suppression",
        )
    if relative == "gateway/platforms/api_server.py":
        text = replace(
            text,
            "from agent.redact import redact_sensitive_text",
            "from agent.redact import redact_sensitive_text\n"
            "from hermes_cli.uap_missions import (\n"
            "    MissionError, MissionProjectRequired, MissionStore, NOTIFICATION_SEND_TIMEOUT_SECONDS,\n"
            "    image_generation_prompt, is_execution_goal, notify_subscribers, owner_key_valid,\n"
            "    producer_key_valid, project_setup_execution_goal, project_setup_system_prompt,\n"
            "    project_setup_target, project_setup_target_from_system_prompt,\n"
            "    public_intake_projects, sanitize_producer_submission,\n"
            "    terminal_request_allowed,\n"
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
        text = replace(
            text,
            '''        model = body.get("model") or self._model_name
        system_prompt = body.get("system_prompt")''',
            '''        model = body.get("model") or self._model_name
        system_prompt = body.get("system_prompt")
        try:
            if body.get("setup_project_id") is not None:
                system_prompt = project_setup_system_prompt(
                    project_setup_target("workspace", body.get("setup_project_id"))
                )
        except MissionError as error:
            return web.json_response(
                _openai_error(str(error), code="project_setup_failed"), status=400
            )''',
            "setup-bound session creation",
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
        setup_target = None
        try:
            if body.get("setup_project_id") is not None:
                setup_target = project_setup_target(
                    "workspace", body.get("setup_project_id")
                )
            elif session_entry is not None:
                setup_target = project_setup_target_from_system_prompt(
                    "workspace", session_entry.get("system_prompt")
                )
            store = self._missions()
            continuation = bool(
                source_message_id is not None
                and store.owner_turn_continues_mission(
                    platform="workspace",
                    source_message_id=source_message_id,
                    session_id=session_id,
                )
            )
        except MissionError as error:
            return web.json_response(
                _openai_error(str(error), code="project_setup_failed"), status=400
            )
        if source_message_id is not None and (
            continuation
            or is_execution_goal(user_message)
            or image_generation_prompt(user_message) is not None
        ):
            try:
                if not isinstance(user_message, str):
                    raise MissionError("mission intake requires a text goal")
                intake_text = user_message
                intake_project_id = body.get("project_id")
                if setup_target is not None and not continuation:
                    intake_text = project_setup_execution_goal(
                        setup_target, user_message
                    )
                    intake_project_id = "uap"
                owner_event, _ = store.ingest_owner_turn(
                    redact_sensitive_text(intake_text, force=True),
                    platform="workspace",
                    source_message_id=source_message_id,
                    session_id=session_id,
                    project_id=intake_project_id,
                )
                mission_id = owner_event["mission_id"]
                view = store.projection(mission_id)
                if view.get("capability") == "media.image.generate":
                    from hermes_cli.uap_media import execute_media_mission
                    view = await asyncio.to_thread(execute_media_mission, store, mission_id)
                if owner_event["type"] == "mission.answer":
                    response_text = (
                        f"Ответ принят для задачи {mission_id}. "
                        "Выполнение продолжится автоматически."
                    )
                elif view.get("status") == "completed" and view.get("artifacts"):
                    artifact = view["artifacts"][0]
                    response_text = (
                        f"Изображение готово для задачи {mission_id}: {artifact['name']}. "
                        "Оно сохранено в Central mission."
                    )
                else:
                    response_text = (
                        f"Задача {mission_id} принята. Выполнение начнётся автоматически; "
                        "от вас ничего не требуется."
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
            except MissionProjectRequired as error:
                return web.json_response(
                    {"error": str(error), "projects": error.projects}, status=409
                )
            except MissionError as error:
                return web.json_response(
                    _openai_error(str(error), code="mission_intake_failed"), status=400
                )
            stream_identity = (
                mission_id if owner_event["type"] == "mission.accepted"
                else f"{mission_id}:{source_message_id}"
            )
            digest = hashlib.sha256(stream_identity.encode("utf-8")).hexdigest()[:32]
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
        system_prompt = body.get("system_message") or body.get("instructions")
        if setup_target is not None:
            setup_prompt = project_setup_system_prompt(setup_target)
            system_prompt = (
                f"{setup_prompt}\\n\\n{system_prompt}" if system_prompt else setup_prompt
            )''',
            "ordinary Workspace mission intake",
        )
        stream_and_tail = replace(
            stream_and_tail,
            '''        session_id = request.match_info["session_id"]
        _, err = await self._get_existing_session_or_404(session_id)''',
            '''        session_id = request.match_info["session_id"]
        session_entry, err = await self._get_existing_session_or_404(session_id)''',
            "setup session binding lookup",
        )
        text = before_stream + stream_marker + stream_and_tail
        methods = '''    def _missions(self) -> MissionStore:
        if self._mission_store is None:
            self._mission_store = MissionStore.default()
        return self._mission_store

    async def _handle_mission_projects(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            platform = request.query.get("platform", "workspace")
            return web.json_response({"projects": public_intake_projects(platform)})
        except MissionError as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_create_project_onboarding(
        self, request: "web.Request"
    ) -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not owner_key_valid(request.headers.get("X-Hermes-Mission-Owner-Key")):
            return web.json_response({"error": "Invalid mission owner key"}, status=401)
        if request.headers.get("X-Hermes-Mission-Producer-Key") is not None:
            return web.json_response(
                {"error": "Ambiguous mission capability"}, status=401
            )
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {
                "name", "description", "preset",
            }:
                raise MissionError(
                    "project onboarding request must contain name, description and preset"
                )
            if any(
                not isinstance(body[field], str)
                for field in ("name", "description", "preset")
            ):
                raise MissionError("project onboarding fields must be strings")
            onboarding, created = self._missions().request_project_onboarding(
                body["name"],
                redact_sensitive_text(body["description"], force=True),
                body["preset"],
            )
            return web.json_response(
                {"created": created, "onboarding": onboarding},
                status=201 if created else 200,
            )
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_get_project_onboarding(
        self, request: "web.Request"
    ) -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            onboarding = self._missions().project_onboarding(
                request.match_info["request_id"]
            )
            return web.json_response({"onboarding": onboarding})
        except MissionError as error:
            status = 404 if str(error) == "project onboarding request not found" else 400
            return web.json_response({"error": str(error)}, status=status)

    async def _handle_pending_project_onboarding(
        self, request: "web.Request"
    ) -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not producer_key_valid(
            request.headers.get("X-Hermes-Mission-Producer-Key")
        ):
            return web.json_response({"error": "Invalid mission producer key"}, status=401)
        return web.json_response(
            {"onboarding": self._missions().pending_project_onboarding()}
        )

    async def _handle_advance_project_onboarding(
        self, request: "web.Request"
    ) -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not producer_key_valid(
            request.headers.get("X-Hermes-Mission-Producer-Key")
        ):
            return web.json_response({"error": "Invalid mission producer key"}, status=401)
        try:
            body = await request.json()
            if (
                not isinstance(body, dict)
                or not {"expected_checkpoint", "checkpoint"} <= set(body)
                or set(body) - {
                    "expected_checkpoint", "checkpoint", "error_code",
                }
            ):
                raise MissionError("invalid project onboarding transition")
            onboarding, advanced = self._missions().advance_project_onboarding(
                request.match_info["request_id"],
                body.get("expected_checkpoint"),
                body.get("checkpoint"),
                error_code=body.get("error_code"),
            )
            return web.json_response(
                {"advanced": advanced, "onboarding": onboarding}
            )
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            status = 404 if str(error) == "project onboarding request not found" else 400
            return web.json_response({"error": str(error)}, status=status)

    async def _handle_record_project_onboarding_invocation(
        self, request: "web.Request"
    ) -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        if not producer_key_valid(
            request.headers.get("X-Hermes-Mission-Producer-Key")
        ):
            return web.json_response({"error": "Invalid mission producer key"}, status=401)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"invocation"}:
                raise MissionError("invalid project onboarding invocation")
            onboarding, recorded = self._missions().record_project_onboarding_invocation(
                request.match_info["request_id"], body["invocation"]
            )
            return web.json_response(
                {"recorded": recorded, "onboarding": onboarding}
            )
        except (MissionError, TypeError, ValueError, json.JSONDecodeError) as error:
            status = 404 if str(error) == "project onboarding request not found" else 400
            return web.json_response({"error": str(error)}, status=status)

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
                    delivery_mode=body.get("delivery_mode"),
                    parent_mission_id=body.get("parent_mission_id"),
                )
            else:
                if not owner_key_valid(owner_key):
                    return web.json_response(
                        {"error": "Invalid mission owner key"}, status=401
                    )
                allowed = {
                    "goal", "platform", "source_message_id", "session_id",
                    "chat_id", "thread_id", "project_id",
                }
                if unknown := set(body) - allowed:
                    raise MissionError(
                        "unknown owner intake fields: " + ", ".join(sorted(unknown))
                    )
                for name in allowed & body.keys():
                    if not isinstance(body[name], str):
                        raise MissionError(f"invalid {name}")
                event, created = store.ingest_owner_turn(
                    redact_sensitive_text(body.get("goal"), force=True),
                    platform=body.get("platform"),
                    source_message_id=body.get("source_message_id"),
                    session_id=body.get("session_id"),
                    chat_id=body.get("chat_id"),
                    thread_id=body.get("thread_id"),
                    project_id=body.get("project_id"),
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
            store = self._missions()
            mission_id = request.match_info["mission_id"]
            payload = store.workspace_payload(mission_id, after)
            payload["channels"] = store.channel_evidence(mission_id)
            return web.json_response(payload)
        except MissionError as error:
            status = 404 if str(error) == "mission not found" else 400
            return web.json_response({"error": str(error)}, status=status)
        except (TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    async def _handle_get_mission_artifact(self, request: "web.Request") -> "web.Response":
        if auth_error := self._check_auth(request):
            return auth_error
        try:
            path, artifact = self._missions().media_artifact_file(
                request.match_info["mission_id"], request.match_info["artifact_id"]
            )
            return web.FileResponse(
                path,
                headers={
                    "Content-Type": artifact["media_type"],
                    "Content-Disposition": f'inline; filename="{artifact["name"]}"',
                    "Cache-Control": "private, max-age=31536000, immutable",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except MissionError as error:
            status = 404 if str(error) == "artifact not found" else 400
            return web.json_response({"error": str(error)}, status=status)

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
            if event.get("type") == "mission.completed":
                artifact = store.media_artifact(event["mission_id"])
                if artifact:
                    media = await asyncio.wait_for(
                        adapter.send_image_file(
                            subscription["chat_id"], artifact["path"],
                            caption="Изображение готово",
                            metadata=metadata,
                        ),
                        timeout=NOTIFICATION_SEND_TIMEOUT_SECONDS,
                    )
                    if media is not None and getattr(media, "success", True) is False:
                        raise RuntimeError(getattr(media, "error", "mission image delivery failed"))

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
            "    def _api_key_passes_startup_guard(self) -> bool:",
            methods + "    def _api_key_passes_startup_guard(self) -> bool:",
            "mission handlers",
        )
        return replace(
            text,
            '''            ("POST", "/v1/chat/completions", self._handle_chat_completions),''',
            '''            ("POST", "/v1/chat/completions", self._handle_chat_completions),
            ("GET", "/api/mission-projects", self._handle_mission_projects),
            ("POST", "/api/project-onboarding", self._handle_create_project_onboarding),
            ("GET", "/api/project-onboarding/pending", self._handle_pending_project_onboarding),
            ("GET", "/api/project-onboarding/{request_id}", self._handle_get_project_onboarding),
            ("POST", "/api/project-onboarding/{request_id}/advance", self._handle_advance_project_onboarding),
            ("POST", "/api/project-onboarding/{request_id}/invocation", self._handle_record_project_onboarding_invocation),
            ("GET", "/api/missions", self._handle_list_missions),
            ("POST", "/api/missions", self._handle_create_mission),
            ("GET", "/api/missions/{mission_id}", self._handle_get_mission),
            ("GET", "/api/missions/{mission_id}/artifacts/{artifact_id}", self._handle_get_mission_artifact),
            ("POST", "/api/missions/{mission_id}/events", self._handle_append_mission_event),
            ("POST", "/api/missions/{mission_id}/answer", self._handle_answer_mission),
            ("POST", "/api/missions/{mission_id}/terminal", self._handle_finish_mission),''',
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
    active_commit = BUILD1_UPSTREAM_COMMIT if args.build1_runtime else UPSTREAM_COMMIT
    if head != active_commit:
        raise SystemExit("upstream commit fingerprint mismatch")

    if args.build1_runtime:
        selected_files = BUILD1_FILES
        active_patched = BUILD1_PATCHED_FILES
    else:
        selected_files = FILES
        active_patched = PATCHED_FILES
    if args.print_patched_hashes:
        for relative, expected in selected_files.items():
            path = root / relative
            if sha(path) != expected:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")
            print(f'{relative}={hashlib.sha256(transform(relative, path.read_text()).encode()).hexdigest()}')
        return

    assets = {
        RUNTIME_TARGET: RUNTIME_SOURCE,
        MEDIA_TARGET: MEDIA_SOURCE,
    }
    statuses: list[str] = []
    source_paths: list[tuple[str, pathlib.Path, str]] = []
    for relative, expected in selected_files.items():
        path = root / relative
        actual = sha(path)
        if actual == expected:
            statuses.append(f"{relative}: source-needs-overlay")
            source_paths.append((relative, path, path.read_text()))
        elif actual == active_patched[relative]:
            statuses.append(f"{relative}: exact-patched")
        elif (
            args.build1_runtime
            and actual in LEGACY_BUILD1_PATCHED_FILES.get(relative, ())
        ):
            pristine = subprocess.check_output(
                ["git", "show", f"{active_commit}:{relative}"],
                cwd=root,
                text=True,
            )
            if hashlib.sha256(pristine.encode()).hexdigest() != expected:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")
            statuses.append(f"{relative}: legacy-needs-overlay")
            source_paths.append((relative, path, pristine))
        else:
            raise SystemExit(f"upstream fingerprint mismatch: {relative}")
    missing_assets: list[tuple[pathlib.Path, pathlib.Path]] = []
    if not args.build1_runtime:
        for relative, source in assets.items():
            target = root / relative
            if not target.exists():
                statuses.append(f"{relative}: source-needs-overlay")
                missing_assets.append((target, source))
            elif sha(target) == sha(source):
                statuses.append(f"{relative}: exact-patched")
            else:
                raise SystemExit(f"upstream fingerprint mismatch: {relative}")

    if args.check:
        print("\n".join(statuses))
        return

    for relative, path, source_text in source_paths:
        atomic_write(path, transform(relative, source_text))
        if sha(path) != active_patched[relative]:
            raise SystemExit(f"overlay output fingerprint mismatch: {relative}")
    for target, source in missing_assets:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, source.read_text(encoding="utf-8"))
    print("overlay applied" if source_paths or missing_assets else "overlay already applied")


if __name__ == "__main__":
    main()
