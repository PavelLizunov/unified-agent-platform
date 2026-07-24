#!/usr/bin/env python3
"""Read-only integration check for the pinned central Hermes overlay."""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import types
from unittest import mock


TOOL = pathlib.Path(__file__).with_name("apply_overlay.py")
INSTALLER = TOOL.parents[1] / "swarm" / "install_flow_v2.py"
COMMIT = "3ef6bbd201263d354fd83ec55b3c306ded2eb72a"
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
    parser.add_argument("--build1-checkout", type=pathlib.Path, default=None,
                        help="Local v0.18 checkout for the build1 regression")
    args = parser.parse_args()
    source = args.checkout.resolve() if args.checkout else UPSTREAM
    with tempfile.TemporaryDirectory(prefix="hermes-mission-overlay-") as temp:
        tool_spec = importlib.util.spec_from_file_location("apply_overlay", TOOL)
        overlay = importlib.util.module_from_spec(tool_spec)
        assert tool_spec.loader
        tool_spec.loader.exec_module(overlay)
        assert "924dcf6b2b277575d1d065aff209347ce5abc96ab158bc80b749f4c3552992cd" in (
            overlay.LEGACY_BUILD1_PATCHED_FILES["hermes_cli/kanban.py"]
        )
        assert "unknown" not in overlay.LEGACY_BUILD1_PATCHED_FILES["hermes_cli/kanban.py"]
        atomic_target = pathlib.Path(temp) / "atomic-target.py"
        atomic_target.write_text("before\n", encoding="utf-8")
        with mock.patch.object(overlay.os, "replace", side_effect=OSError("simulated crash")):
            try:
                overlay.atomic_write(atomic_target, "after\n")
                raise AssertionError("interrupted atomic overlay write did not fail")
            except OSError:
                pass
        assert atomic_target.read_text(encoding="utf-8") == "before\n"
        assert list(atomic_target.parent.glob(f".{atomic_target.name}.*")) == []
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

        # --- Build-1 exact v0.18 regression (separate root) ---
        import apply_overlay as _ov_b1
        b1_commit = _ov_b1.BUILD1_UPSTREAM_COMMIT
        b1_root = pathlib.Path(temp) / "build1-hermes"
        b1_root.mkdir()
        # A supplied --build1-checkout is used as a LOCAL git source (no network):
        # the exact v0.18 commit is fetched from it by SHA, exactly as the central
        # checkout fetches COMMIT from `source`.  Without a checkout the commit is
        # fetched from UPSTREAM (network).  Either way the working tree comes from
        # the exact commit object, so the v0.18 exact-hash check holds and never
        # depends on the supplied checkout's working-tree state.
        b1_source = args.build1_checkout.resolve() if args.build1_checkout else UPSTREAM
        subprocess.run(["git", "init", "--quiet"], cwd=b1_root, check=True)
        subprocess.run(
            ["git", "fetch", "--quiet", "--depth=1", str(b1_source), b1_commit],
            cwd=b1_root, check=True, timeout=120,
        )
        subprocess.run(
            ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            cwd=b1_root, check=True, stdout=subprocess.DEVNULL,
        )
        # Apply + check the v0.18 build1 overlay on the exact v0.18 root
        b1_apply = run(b1_root, "--source-commit", b1_commit, "--build1-runtime")
        assert b1_apply.returncode == 0, f"build1 apply failed: {b1_apply.stderr}"
        b1_check = run(b1_root, "--source-commit", b1_commit, "--build1-runtime", "--check")
        assert b1_check.returncode == 0, f"build1 check failed: {b1_check.stderr}"
        assert b1_check.stdout.count("exact-patched") == 3, (
            f"build1 expected 3 exact-patched, got: {b1_check.stdout}"
        )
        # Installer against the exact v0.18 root
        if INSTALLER.is_file():
            installer_spec = importlib.util.spec_from_file_location(
                "install_flow_v2", INSTALLER
            )
            installer = importlib.util.module_from_spec(installer_spec)
            assert installer_spec.loader
            installer_spec.loader.exec_module(installer)
            build1_home = pathlib.Path(temp) / "build1-home"
            installer.install(INSTALLER.parent, build1_home, b1_root)
            installer.check(INSTALLER.parent, build1_home, b1_root)
            for installed in installer._files(INSTALLER.parent).values():
                assert (build1_home / installed).is_file()
        assert not (clone / "hermes_cli/uap_missions.py").exists()

        before = run(clone, "--check")
        assert before.returncode == 0 and "source-needs-overlay" in before.stdout, before.stderr
        first = run(clone)
        assert first.returncode == 0 and "overlay applied" in first.stdout, first.stderr
        second = run(clone)
        assert second.returncode == 0 and "overlay already applied" in second.stdout, second.stderr
        checked = run(clone, "--check")
        assert checked.returncode == 0 and checked.stdout.count("exact-patched") == 9, checked.stderr

        commands = (clone / "hermes_cli/commands.py").read_text(encoding="utf-8")
        gateway = (clone / "gateway/run.py").read_text(encoding="utf-8")
        telegram = (clone / "plugins/platforms/telegram/adapter.py").read_text(encoding="utf-8")
        api = (clone / "gateway/platforms/api_server.py").read_text(encoding="utf-8")
        kanban_cli = (clone / "hermes_cli/kanban.py").read_text(encoding="utf-8")
        kanban = (clone / "hermes_cli/kanban_db.py").read_text(encoding="utf-8")
        hermes_main = (clone / "hermes_cli/main.py").read_text(encoding="utf-8")
        assert 'CommandDef("mission"' in commands
        assert 'CommandDef("projects"' in commands
        assert 'HERMES_OWNER_COMMANDS' in commands
        assert 'CommandDef("status", "Показать состояние текущей сессии"' in commands
        assert 'CommandDef("projects", "Показать разрешённые проекты"' in commands
        assert 'CommandDef("mission", "Показать текущую автономную задачу"' in commands
        assert 'CommandDef("stop", "Остановить текущий ответ"' in commands
        assert 'CommandDef("help", "Показать короткую справку"' in commands
        assert 'if canonical == "mission"' in gateway
        assert 'if canonical == "projects"' in gateway
        assert (
            "session_entry = self.session_store.get_or_create_session(source)\n"
            '            source_message_id = str(event.message_id or "").strip()'
        ) in gateway
        assert "Проекты в GitHub" in gateway
        assert "профиль проверок готовится" in gateway
        assert "Hermes сам создаст задачу" in gateway
        assert "К этому чату не привязана задача" in gateway
        assert "У текущей задачи нет открытого вопроса владельцу" in gateway
        assert "Автономных задач пока нет" in gateway
        assert "не удалось расшифровать голосовое сообщение" in gateway
        assert "Не удалось создать задачу" in gateway
        assert "Mission intake unavailable" not in gateway
        assert "voice transcription failed" not in gateway
        assert 'key = f"{split_key}:message:{event.message_id}"' in telegram
        telegram_tree = ast.parse(telegram)
        telegram_adapter = next(
            node for node in telegram_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TelegramAdapter"
        )
        enqueue_node = next(
            node for node in telegram_adapter.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_enqueue_text_event"
        )
        enqueue_module = ast.fix_missing_locations(
            ast.Module(body=[enqueue_node], type_ignores=[])
        )
        enqueue_namespace = {
            "asyncio": asyncio,
            "logger": mock.Mock(),
            "MessageEvent": object,
        }
        exec(
            compile(enqueue_module, "<telegram-enqueue>", "exec"),
            enqueue_namespace,
        )
        enqueue_text_event = enqueue_namespace["_enqueue_text_event"]

        class TextSource:
            def __init__(self, user_id):
                self.user_id = user_id

        class TextEvent:
            def __init__(self, message_id, text, user_id="owner"):
                self.message_id = message_id
                self.text = text
                self.source = TextSource(user_id)
                self.media_urls = []
                self.media_types = []

        class TextBatchHarness:
            _SPLIT_THRESHOLD = 4000

            def __init__(self):
                self._pending_text_batches = {}
                self._pending_text_batch_tasks = {}

            @staticmethod
            def _should_drop_delayed_delivery():
                return False

            @staticmethod
            def _text_batch_key(_event):
                return "topic"

            async def _flush_text_batch(self, _key):
                await asyncio.sleep(60)

        async def check_text_batch_identities():
            short = TextBatchHarness()
            enqueue_text_event(short, TextEvent("100", "first"))
            enqueue_text_event(short, TextEvent("101", "second"))
            assert set(short._pending_text_batches) == {
                "topic:sender:owner:message:100",
                "topic:sender:owner:message:101",
            }
            assert short._pending_text_batches[
                "topic:sender:owner:message:100"
            ].text == "first"
            assert short._pending_text_batches[
                "topic:sender:owner:message:101"
            ].text == "second"

            split = TextBatchHarness()
            enqueue_text_event(split, TextEvent("200", "a" * 4000))
            enqueue_text_event(split, TextEvent("201", "tail"))
            assert set(split._pending_text_batches) == {"topic:sender:owner"}
            assert split._pending_text_batches[
                "topic:sender:owner"
            ].message_id == "200"
            assert split._pending_text_batches[
                "topic:sender:owner"
            ].text.endswith("\ntail")

            other_sender = TextBatchHarness()
            enqueue_text_event(
                other_sender, TextEvent("300", "a" * 4000, user_id="owner-a")
            )
            enqueue_text_event(
                other_sender, TextEvent("301", "tail", user_id="owner-b")
            )
            assert set(other_sender._pending_text_batches) == {
                "topic:sender:owner-a",
                "topic:sender:owner-b:message:301",
            }

            tasks = [
                *short._pending_text_batch_tasks.values(),
                *split._pending_text_batch_tasks.values(),
                *other_sender._pending_text_batch_tasks.values(),
            ]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(check_text_batch_identities())
        assert "def _delivery_ledger_confirms_final_delivery(" in gateway
        assert "_already_streamed or _ledger_delivered" in gateway
        gateway_tree = ast.parse(gateway)
        delivery_helper_node = next(
            node for node in ast.walk(gateway_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_delivery_ledger_confirms_final_delivery"
        )
        delivery_helper_module = ast.fix_missing_locations(
            ast.Module(body=[delivery_helper_node], type_ignores=[])
        )
        delivery_helper_namespace = {"logger": mock.Mock()}
        exec(
            compile(delivery_helper_module, "<delivery-helper>", "exec"),
            delivery_helper_namespace,
        )
        delivery_helper = delivery_helper_namespace[
            "_delivery_ledger_confirms_final_delivery"
        ]
        delivery_state = {"value": "delivered"}

        class DeliveryConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params):
                assert "WHERE obligation_id=?" in query
                assert params == ("expected-obligation",)
                return self

            def fetchone(self):
                return (delivery_state["value"],)

        fake_delivery_ledger = types.SimpleNamespace(
            ledger_enabled=lambda: True,
            compute_obligation_id=lambda *_args: "expected-obligation",
            _DB_LOCK=mock.MagicMock(),
            _connect=DeliveryConnection,
        )
        fake_gateway = types.ModuleType("gateway")
        fake_gateway.delivery_ledger = fake_delivery_ledger
        with mock.patch.dict(sys.modules, {"gateway": fake_gateway}):
            assert delivery_helper("session", "message", "final") is True
            delivery_state["value"] = "pending"
            assert delivery_helper("session", "message", "final") is False
            assert delivery_helper("", "message", "final") is False
        assert '_http_route_table' in api
        assert 'def _api_key_passes_startup_guard' in api
        assert 'def _port_is_available' not in api
        assert 'add_route' in api
        assert api.count('"/api/mission') >= 4
        for route in (
            '"/api/missions"',
            '"/api/mission-projects"',
            '"/api/project-onboarding"',
            '"/api/project-onboarding/pending"',
            '"/api/project-onboarding/{request_id}"',
            '"/api/project-onboarding/{request_id}/advance"',
            '"/api/project-onboarding/{request_id}/invocation"',
            '"/api/missions/{mission_id}"',
            '"/api/missions/{mission_id}/events"',
            '"/api/missions/{mission_id}/answer"',
            '"/api/missions/{mission_id}/terminal"',
        ):
            assert route in api
        assert "X-Hermes-Mission-Producer-Key" in api
        assert "producer_key_valid" in api
        assert "X-Hermes-Mission-Owner-Key" in api
        assert "owner_key_valid" in api
        assert 'if not isinstance(body, dict)' in api
        assert 'producer_key = request.headers.get("X-Hermes-Mission-Producer-Key")' in api
        assert 'delivery_mode=body.get("delivery_mode")' in api
        assert 'parent_mission_id=body.get("parent_mission_id")' in api
        assert "store.ingest_owner_turn(" in api
        assert "if not owner_key_valid(owner_key)" in api
        assert "Ambiguous mission capability" in api
        assert '"goal", "platform", "source_message_id", "session_id"' in api
        assert '"chat_id", "thread_id", "project_id"' in api
        assert "unknown owner intake fields" in api
        assert "request_project_onboarding(" in api
        assert "pending_project_onboarding()" in api
        assert "advance_project_onboarding(" in api
        assert "record_project_onboarding_invocation(" in api
        assert "project onboarding request must contain name, description and preset" in api
        assert "notify_subscribers" in api
        assert "complete_if_ready" in api
        assert "payload[\"channels\"] = store.channel_evidence(mission_id)" in api
        assert "_handle_answer_mission" in api
        assert "_handle_finish_mission" in api
        append_handler = api[
            api.index("    async def _handle_append_mission_event"):
            api.index("    async def _handle_answer_mission")
        ]
        assert append_handler.index("store.complete_if_ready(mission_id)") < append_handler.index(
            "await self._notify_mission(store, event)"
        )
        assert append_handler.index("store.complete_if_ready(mission_id)") < append_handler.index(
            "await self._notify_mission(store, terminal)"
        )
        assert append_handler.index(
            "await self._notify_mission(store, terminal)"
        ) < append_handler.index("store.restore_parent_after_terminal_notification(mission_id)")
        list_handler = api[
            api.index("    async def _handle_list_missions"):
            api.index("    async def _handle_create_mission")
        ]
        assert "store.pending_terminal_notification(" in list_handler
        assert list_handler.index("await self._notify_mission(store, notification)") < (
            list_handler.index("store.restore_parent_after_terminal_notification(")
        )
        terminal_handler = api[api.index("    async def _handle_finish_mission"):]
        assert terminal_handler.index(
            "await self._notify_mission(store, event, defer=False)"
        ) < terminal_handler.index(
            'store.restore_parent_after_terminal_notification(event["mission_id"])'
        )
        assert 'requested.startswith("answer ")' in gateway
        assert "store.answer(" in gateway
        assert 'is_execution_goal(event.text or "")' in gateway
        assert "store.owner_turn_continues_mission(" in gateway
        assert 'platform="telegram"' in gateway
        assert 'source_message_id = str(event.message_id or "").strip()' in gateway
        assert "store.ingest_owner_turn(" in gateway
        assert "_enrich_message_with_transcription(" in gateway
        assert "event.message_type in (MessageType.VOICE, MessageType.AUDIO)" in gateway
        assert 'getattr(event, "_uap_media_download_failed", False)' in gateway
        assert "download_telegram_file(msg.voice)" in telegram
        assert "download_telegram_file(msg.audio)" in telegram
        assert "Telegram не отдал файл после 3 автоматических попыток" in telegram
        assert "event._uap_media_download_failed = True" in telegram
        assert "candidate.parent == audio_cache" in gateway
        assert "candidate.unlink()" in gateway
        assert "len(transcripts) != len(audio_paths)" in gateway
        assert "goal_text = redact_sensitive_text(goal_text, force=True)" in gateway
        assert "and not is_execution_goal(goal_text)" in gateway
        assert "event.message_type = MessageType.TEXT" in gateway
        assert "event._uap_owner_goal = False" in gateway
        assert "return await self._handle_message(event)" in gateway
        assert "MissionProjectRequired" in gateway
        assert "MissionIntakeCancelled" in gateway
        assert 'canonical == "cancel"' in gateway
        assert 'event.text = "отмена"' in gateway
        assert "Для какого проекта выполнить задачу?" in gateway
        assert "или напишите «отмена»" in gateway
        assert "Выбор проекта отменён." in gateway
        assert 'reason="owner-intake"' in (clone / "hermes_cli/uap_missions.py").read_text(
            encoding="utf-8"
        )
        stream_handler = api[
            api.index("    async def _handle_session_chat_stream"):
            api.index("    async def _handle_chat_completions")
        ]
        synchronous_handler = api[
            api.index("    async def _handle_session_chat("):
            api.index("    async def _handle_session_chat_stream")
        ]
        assert 'source_message_id = body.get("source_message_id")' not in synchronous_handler
        assert 'source_message_id = body.get("source_message_id")' in stream_handler
        assert "is_execution_goal(user_message)" in stream_handler
        assert "project_setup_target(" in stream_handler
        assert "project_setup_target_from_system_prompt(" in stream_handler
        assert "project_setup_system_prompt(setup_target)" in stream_handler
        assert "project_setup_execution_goal(" in stream_handler
        assert 'platform="workspace"' in stream_handler
        assert "project_id=intake_project_id" in stream_handler
        assert '"projects": error.projects' in stream_handler
        assert 'code="mission_intake_failed"' in stream_handler
        create_session_handler = api[
            api.index("    async def _handle_create_session("):
            api.index("    async def _handle_get_session(")
        ]
        assert 'body.get("setup_project_id")' in create_session_handler
        assert "project_setup_system_prompt(" in create_session_handler
        assert 'owner_event["type"] == "mission.answer"' in stream_handler
        assert "Ответ принят для задачи" in stream_handler
        assert 'f"{mission_id}:{source_message_id}"' in stream_handler
        assert stream_handler.index("store.ingest_owner_turn(") < stream_handler.index(
            "system_prompt = body.get"
        )
        assert "atomic sticky initial block" not in kanban
        assert '"blocked",\n                        {"reason": None, "kind": "needs_input"}' in kanban
        assert "uq_tasks_active_idempotency" in kanban
        assert "def _harden_db_permissions" in kanban
        assert "kb.unblock_task(conn, tid, reason=reason)" in kanban_cli
        assert 'p_claim.add_argument("--claimer"' in kanban_cli
        assert "claimer=args.claimer" in kanban_cli
        assert 'payload["reason"] = reason' in kanban
        assert '"--require-idle"' in kanban_cli
        assert "GC deferred: board is not idle" in kanban_cli
        assert "with kb.write_txn(conn):" in kanban_cli
        assert 'return args.func(args)' in hermes_main
        assert 'raise SystemExit(main())' in hermes_main
        assert "strict: bool = False" in kanban
        assert "if strict:" in kanban
        assert "shutil.rmtree(path)" in kanban_cli
        assert "strict=True" in kanban_cli

        subprocess.run(
            [
                "python3",
                "-m",
                "py_compile",
                str(clone / "hermes_cli/uap_missions.py"),
                str(clone / "hermes_cli/commands.py"),
                str(clone / "hermes_cli/kanban.py"),
                str(clone / "hermes_cli/kanban_db.py"),
                str(clone / "hermes_cli/main.py"),
                str(clone / "gateway/run.py"),
                str(clone / "gateway/platforms/api_server.py"),
            ],
            check=True,
        )

        race = textwrap.dedent(
            """
            import contextlib
            import os
            import shutil
            import threading
            import time
            from pathlib import Path
            from types import SimpleNamespace

            from hermes_cli import kanban as cli
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

                reference = "owner-answer:q-product:0123456789abcdef"
                assert kb.unblock_task(conn, task.id, reason=reference)
                sticky = next(
                    event for event in reversed(kb.list_events(conn, task.id))
                    if event.kind in {"blocked", "unblocked"}
                )
                assert sticky.kind == "unblocked"
                assert sticky.payload["reason"] == reference

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

            idle_args = SimpleNamespace(
                require_idle=True,
                event_retention_days=30,
                log_retention_days=30,
            )
            original_gc_logs = kb.gc_worker_logs
            gc_log_calls = []

            def observed_gc_logs(*args, **kwargs):
                gc_log_calls.append(True)
                return original_gc_logs(*args, **kwargs)

            kb.gc_worker_logs = observed_gc_logs
            assert cli._cmd_gc(idle_args) == 3
            assert gc_log_calls == []

            with kb.connect_closing(database) as conn:
                with kb.write_txn(conn):
                    scratch = kb.workspaces_root() / concurrent_ids[0]
                    scratch.mkdir(parents=True, exist_ok=True)
                    conn.execute(
                        "UPDATE tasks SET status = 'archived', workspace_kind = 'scratch', "
                        "workspace_path = ?",
                        (str(scratch),),
                    )

            def failed_gc_logs(*args, **kwargs):
                assert kwargs.get("strict") is True
                raise PermissionError("simulated worker log cleanup failure")

            kb.gc_worker_logs = failed_gc_logs
            assert cli._cmd_gc(idle_args) == 1
            kb.gc_worker_logs = original_gc_logs

            original_rmtree = shutil.rmtree

            def failed_rmtree(_path):
                raise PermissionError("simulated workspace cleanup failure")

            shutil.rmtree = failed_rmtree
            assert cli._cmd_gc(idle_args) == 1
            assert scratch.exists()
            shutil.rmtree = original_rmtree

            outside = Path(os.environ["HERMES_HOME"]).parent / "outside-scratch"
            outside.mkdir()
            with kb.connect_closing(database) as conn:
                with kb.write_txn(conn):
                    conn.execute(
                        "UPDATE tasks SET workspace_path = ? WHERE id = ?",
                        (str(outside), concurrent_ids[0]),
                    )
            assert cli._cmd_gc(idle_args) == 1
            assert outside.is_dir()
            scratch_root = kb.workspaces_root()
            root_guard_sentinel = scratch_root / "root-guard-sentinel"
            root_guard_sentinel.mkdir(parents=True, exist_ok=True)
            with kb.connect_closing(database) as conn:
                with kb.write_txn(conn):
                    conn.execute(
                        "UPDATE tasks SET workspace_path = ? WHERE id = ?",
                        (str(scratch_root), concurrent_ids[0]),
                    )
            assert cli._cmd_gc(idle_args) == 1
            assert root_guard_sentinel.is_dir()
            scratch.mkdir(parents=True, exist_ok=True)
            with kb.connect_closing(database) as conn:
                with kb.write_txn(conn):
                    conn.execute(
                        "UPDATE tasks SET workspace_path = ? WHERE id = ?",
                        (str(scratch), concurrent_ids[0]),
                    )

            gc_entered = threading.Event()
            release_gc = threading.Event()

            def paused_gc_logs(*args, **kwargs):
                assert kwargs.get("strict") is True
                gc_entered.set()
                if not release_gc.wait(5):
                    raise AssertionError("concurrent creator did not reach idle GC")
                return original_gc_logs(*args, **kwargs)

            kb.gc_worker_logs = paused_gc_logs
            gc_results = []

            def run_idle_gc():
                try:
                    gc_results.append(cli._cmd_gc(idle_args))
                except BaseException as error:
                    failures.append(error)

            def create_during_gc():
                try:
                    with kb.connect_closing(database) as conn:
                        kb.create_task(
                            conn,
                            title="Created during GC",
                            tenant="mission-gc-race",
                            idempotency_key="central-mission:mission-gc-race",
                            initial_status="blocked",
                        )
                except BaseException as error:
                    failures.append(error)

            gc_thread = threading.Thread(target=run_idle_gc)
            gc_thread.start()
            assert gc_entered.wait(5)
            creator_thread = threading.Thread(target=create_during_gc)
            creator_thread.start()
            time.sleep(0.05)
            assert creator_thread.is_alive(), "creator bypassed the idle GC write lock"
            release_gc.set()
            gc_thread.join(5)
            creator_thread.join(5)
            kb.gc_worker_logs = original_gc_logs
            assert not gc_thread.is_alive() and not creator_thread.is_alive()
            assert not failures, failures
            assert gc_results == [0]
            assert cli._cmd_gc(idle_args) == 3

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
        hermes_executable = (
            source / ".venv/bin/hermes"
            if isinstance(source, pathlib.Path)
            else None
        )
        if hermes_executable is not None and hermes_executable.is_file():
            executable_gc = subprocess.run(
                [
                    str(hermes_executable),
                    "kanban",
                    "--board",
                    "default",
                    "gc",
                    "--require-idle",
                ],
                env=race_env,
                text=True,
                capture_output=True,
            )
            assert executable_gc.returncode == 3, executable_gc.stderr
            assert executable_gc.stdout.strip() == "GC deferred: board is not idle"
            project_list = subprocess.run(
                [str(hermes_executable), "project", "list"],
                env=race_env,
                text=True,
                capture_output=True,
            )
            assert project_list.returncode == 0, project_list.stderr

        image_root = pathlib.Path(temp) / "image-root"
        for relative in (
            "hermes_cli/commands.py",
            "hermes_cli/kanban.py",
            "hermes_cli/kanban_db.py",
            "hermes_cli/main.py",
            "gateway/run.py",
            "gateway/platforms/api_server.py",
            "plugins/platforms/telegram/adapter.py",
        ):
            target = image_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.check_output(["git", "show", f"{COMMIT}:{relative}"], cwd=clone)
            )
        image_apply = run(image_root, "--source-commit", COMMIT)
        assert image_apply.returncode == 0 and "overlay applied" in image_apply.stdout
        image_check = run(image_root, "--source-commit", COMMIT, "--check")
        assert image_check.returncode == 0 and image_check.stdout.count("exact-patched") == 9

        target = clone / "gateway/run.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr



        # --- Native v0.19 replacements (read from the exact v0.19 clone) ---
        middleware = (clone / "hermes_cli/dashboard_auth/middleware.py").read_text(encoding="utf-8")
        assert "supports_password" in middleware, "v0.19 middleware must natively guard SSO password providers"
        server = (clone / "tui_gateway/server.py").read_text(encoding="utf-8")
        assert "stored_session_id" in server, "v0.19 server.py must natively emit stored_session_id"

    # --- Build-1 module-level regression ---
    import apply_overlay as ov_mod
    assert ov_mod.BUILD1_UPSTREAM_COMMIT == "7c1a029553d87c43ecff8a3821336bc95872213b"
    assert set(ov_mod.BUILD1_FILES) == {"hermes_cli/kanban.py", "hermes_cli/kanban_db.py", "hermes_cli/main.py"}
    assert set(ov_mod.BUILD1_PATCHED_FILES) == set(ov_mod.BUILD1_FILES)
    assert ov_mod.UPSTREAM_COMMIT != ov_mod.BUILD1_UPSTREAM_COMMIT

    print("hermes mission overlay checks passed")


if __name__ == "__main__":
    main()
