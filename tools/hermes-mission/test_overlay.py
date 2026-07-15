#!/usr/bin/env python3
"""Read-only integration check for the pinned central Hermes overlay."""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap


TOOL = pathlib.Path(__file__).with_name("apply_overlay.py")
COMMIT = "7c1a029553d87c43ecff8a3821336bc95872213b"
UPSTREAM = "https://github.com/NousResearch/hermes-agent"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), *map(str, args)],
        text=True,
        capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", nargs="?", type=pathlib.Path)
    args = parser.parse_args()
    source = args.checkout.resolve() if args.checkout else UPSTREAM
    with tempfile.TemporaryDirectory(prefix="hermes-mission-overlay-") as temp:
        clone = pathlib.Path(temp) / "hermes"
        clone.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=clone, check=True)
        subprocess.run(
            ["git", "fetch", "--quiet", "--depth=1", str(source), COMMIT],
            cwd=clone,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "--detach", "FETCH_HEAD"],
            cwd=clone,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        before = run(clone, "--check")
        assert before.returncode == 0 and "source-needs-overlay" in before.stdout, before.stderr
        first = run(clone)
        assert first.returncode == 0 and "overlay applied" in first.stdout, first.stderr
        second = run(clone)
        assert second.returncode == 0 and "overlay already applied" in second.stdout, second.stderr
        checked = run(clone, "--check")
        assert checked.returncode == 0 and checked.stdout.count("exact-patched") == 5, checked.stderr

        commands = (clone / "hermes_cli/commands.py").read_text(encoding="utf-8")
        gateway = (clone / "gateway/run.py").read_text(encoding="utf-8")
        api = (clone / "gateway/platforms/api_server.py").read_text(encoding="utf-8")
        kanban = (clone / "hermes_cli/kanban_db.py").read_text(encoding="utf-8")
        assert 'CommandDef("mission"' in commands
        assert 'if canonical == "mission"' in gateway
        assert api.count('self._app.router.add_') >= 4
        for route in (
            '"/api/missions"',
            '"/api/missions/{mission_id}"',
            '"/api/missions/{mission_id}/events"',
            '"/api/missions/{mission_id}/terminal"',
        ):
            assert route in api
        assert "X-Hermes-Mission-Producer-Key" in api
        assert "producer_key_valid" in api
        assert "notify_subscribers" in api
        assert "_handle_finish_mission" in api
        assert "atomic sticky initial block" not in kanban
        assert '"blocked",\n                        {"reason": None, "kind": "needs_input"}' in kanban
        assert "uq_tasks_active_idempotency" in kanban
        assert "def _harden_db_permissions" in kanban

        subprocess.run(
            [
                "python3",
                "-m",
                "py_compile",
                str(clone / "hermes_cli/uap_missions.py"),
                str(clone / "hermes_cli/commands.py"),
                str(clone / "hermes_cli/kanban_db.py"),
                str(clone / "gateway/run.py"),
                str(clone / "gateway/platforms/api_server.py"),
            ],
            check=True,
        )

        race = textwrap.dedent(
            """
            import contextlib
            import os
            import threading
            import time
            from pathlib import Path

            from hermes_cli import kanban_db as kb
            from hermes_cli import profiles

            profiles.profile_exists = lambda _name: True
            database = Path(os.environ["HERMES_KANBAN_DB"])
            Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
            with kb.connect_closing(database):
                pass

            created_inside_txn = threading.Event()
            release_create = threading.Event()
            dispatcher_connected = threading.Event()
            dispatch_go = threading.Event()
            dispatch_entered = threading.Event()
            spawned = []
            failures = []
            task_ids = []
            original_append = kb._append_event
            original_dispatch_locked = kb._dispatch_once_locked

            def observed_append(*args, **kwargs):
                original_append(*args, **kwargs)
                if len(args) >= 3 and args[2] == "created":
                    created_inside_txn.set()
                    if not release_create.wait(5):
                        raise AssertionError("dispatcher overlap was not released")

            kb._append_event = observed_append

            def observed_dispatch_locked(*args, **kwargs):
                dispatch_entered.set()
                return original_dispatch_locked(*args, **kwargs)

            kb._dispatch_once_locked = observed_dispatch_locked

            def create_blocked():
                try:
                    with kb.connect_closing(database) as conn:
                        task_ids.append(kb.create_task(
                            conn,
                            title="Atomic blocked handoff",
                            tenant="mission-race",
                            idempotency_key="central-mission:mission-race",
                            initial_status="blocked",
                        ))
                except BaseException as error:
                    failures.append(error)

            def dispatch_during_create():
                try:
                    with kb.connect_closing(database) as conn:
                        dispatcher_connected.set()
                        if not dispatch_go.wait(5):
                            raise AssertionError("dispatcher was not released")
                        kb.dispatch_once(
                            conn,
                            default_assignee="default",
                            spawn_fn=lambda task, _workspace: spawned.append(task.id) or 0,
                        )
                except BaseException as error:
                    failures.append(error)

            dispatcher = threading.Thread(target=dispatch_during_create)
            dispatcher.start()
            assert dispatcher_connected.wait(5)
            creator = threading.Thread(target=create_blocked)
            creator.start()
            assert created_inside_txn.wait(5)
            dispatch_go.set()
            assert dispatch_entered.wait(5)
            time.sleep(0.05)
            assert dispatcher.is_alive(), "dispatch_once did not block on the create transaction"
            release_create.set()
            creator.join(5)
            dispatcher.join(5)
            assert not creator.is_alive() and not dispatcher.is_alive()
            assert not failures, failures
            assert len(task_ids) == 1

            with kb.connect_closing(database) as conn:
                for _ in range(3):
                    kb.dispatch_once(
                        conn,
                        default_assignee="default",
                        spawn_fn=lambda task, _workspace: spawned.append(task.id) or 0,
                    )
                task = kb.get_task(conn, task_ids[0])
                assert task is not None
                assert task.status == "blocked"
                assert task.assignee is None
                assert task.block_kind == "needs_input"
                assert kb._has_sticky_block(conn, task.id)
                assert kb.list_runs(conn, task.id) == []
            assert spawned == []

            creator_barrier = threading.Barrier(2)
            concurrent_ids = []
            original_write_txn = kb.write_txn

            @contextlib.contextmanager
            def synchronized_write_txn(conn, *args, **kwargs):
                creator_barrier.wait(5)
                with original_write_txn(conn, *args, **kwargs):
                    yield

            kb.write_txn = synchronized_write_txn

            def create_same_root():
                try:
                    with kb.connect_closing(database) as conn:
                        concurrent_ids.append(kb.create_task(
                            conn,
                            title="Concurrent root",
                            tenant="mission-concurrent",
                            idempotency_key="central-mission:mission-concurrent",
                            initial_status="blocked",
                        ))
                except BaseException as error:
                    failures.append(error)

            creators = [threading.Thread(target=create_same_root) for _ in range(2)]
            for thread in creators:
                thread.start()
            for thread in creators:
                thread.join(5)
            kb.write_txn = original_write_txn
            assert all(not thread.is_alive() for thread in creators)
            assert not failures, failures
            assert len(concurrent_ids) == 2
            assert len(set(concurrent_ids)) == 1, concurrent_ids
            with kb.connect_closing(database) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE idempotency_key = ? "
                    "AND status != 'archived'",
                    ("central-mission:mission-concurrent",),
                ).fetchone()[0]
                task = kb.get_task(conn, concurrent_ids[0])
                assert count == 1
                assert task is not None and task.status == "blocked"
                assert kb._has_sticky_block(conn, task.id)
                assert kb.list_runs(conn, task.id) == []

            with kb.connect_closing(database) as conn:
                with kb.write_txn(conn):
                    conn.execute(
                        "UPDATE tasks SET priority = priority WHERE id = ?",
                        (concurrent_ids[0],),
                    )
                assert (database.parent.stat().st_mode & 0o777) == 0o700
                assert (database.stat().st_mode & 0o777) == 0o600
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(f"{database}{suffix}")
                    assert sidecar.exists(), sidecar
                    assert (sidecar.stat().st_mode & 0o777) == 0o600

            legacy = Path(os.environ["HERMES_HOME"]) / "legacy-duplicates.db"
            with kb.connect_closing(legacy) as conn:
                original = kb.create_task(
                    conn,
                    title="Legacy duplicate root",
                    tenant="mission-legacy",
                    idempotency_key="central-mission:mission-legacy",
                    initial_status="blocked",
                )
                conn.execute("DROP INDEX uq_tasks_active_idempotency")
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(tasks)")]
                values = list(conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (original,)
                ).fetchone())
                values[columns.index("id")] = "legacy-duplicate"
                conn.execute(
                    f"INSERT INTO tasks ({','.join(columns)}) VALUES "
                    f"({','.join('?' for _ in columns)})",
                    values,
                )
            try:
                kb.init_db(legacy)
                raise AssertionError("legacy duplicate migration did not fail closed")
            except RuntimeError as error:
                assert "duplicates must be resolved before migration" in str(error), error
            """
        )
        race_env = os.environ.copy()
        race_env["PYTHONPATH"] = str(clone)
        race_env["HERMES_HOME"] = str(pathlib.Path(temp) / "hermes-home")
        race_env["HERMES_KANBAN_DB"] = str(pathlib.Path(temp) / "atomic-kanban.db")
        subprocess.run([sys.executable, "-c", race], env=race_env, check=True)

        image_root = pathlib.Path(temp) / "image-root"
        for relative in (
            "hermes_cli/commands.py",
            "hermes_cli/kanban_db.py",
            "gateway/run.py",
            "gateway/platforms/api_server.py",
        ):
            target = image_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.check_output(["git", "show", f"{COMMIT}:{relative}"], cwd=clone)
            )
        image_apply = run(image_root, "--source-commit", COMMIT)
        assert image_apply.returncode == 0 and "overlay applied" in image_apply.stdout
        image_check = run(image_root, "--source-commit", COMMIT, "--check")
        assert image_check.returncode == 0 and image_check.stdout.count("exact-patched") == 5

        target = clone / "gateway/run.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr

    print("hermes mission overlay checks passed")


if __name__ == "__main__":
    main()
