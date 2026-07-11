"""Mechanism test for ADR-027's pinned Hermes compatibility patch."""

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "clusters/prod/infra/hermes-agent-config.yaml"


def main() -> None:
    import yaml

    script = yaml.safe_load(PATCH.read_text(encoding="utf-8"))["data"]["runtime-compat.py"]
    failure = '    if file_mutation_result_landed(tool_name, result):\n        return False, ""\n'
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        (target / "display.py").write_text(failure + "\n    data = safe_json_loads(result)\n")
        (target / "tool_guardrails.py").write_text(failure + '\n    if tool_name == "terminal":\n')
        (target / "codex_runtime.py").write_text(
            "        def _on_codex_event(note: dict) -> None:\n"
            "            # Bridge Codex app-server item/started notifications to Hermes\n"
            "\n    # If the turn signalled the underlying client is wedged (deadline\n"
        )
        (target / "cli.py").write_text(
            '                        if isinstance(result, dict) and result.get("failed"):\n'
            "                            _exit_code = 1\n"
        )
        (target / "dashboard_auth_middleware.py").write_text(
            "    provider = providers[0]\n    prefix = prefix_from_request(request)\n"
        )
        (target / "codex_event_projector.py").write_text(
            '        if item_type == "userMessage":\n'
            "            return self._project_user_message(item)\n"
        )
        (target / "server.py").write_text(
            '    info: dict = {\n        "model": getattr(agent, "model", ""),\n'
        )
        (target / "web_index.js").write_text(
            "if(n===`session.info`){let e=oq(a);e!==void 0&&i?.(e)}"
        )
        script_path = target / "patch.py"
        script_path.write_text(script)

        subprocess.run([sys.executable, str(script_path), str(target)], check=True)
        subprocess.run([sys.executable, str(script_path), str(target)], check=True)

        assert 'tool_name == "exec_command"' in (target / "display.py").read_text()
        assert 'tool_name == "exec_command"' in (target / "tool_guardrails.py").read_text()
        codex_runtime = (target / "codex_runtime.py").read_text()
        assert 'item.get("type") == "commandExecution"' in codex_runtime
        assert "session.request_interrupt()" in codex_runtime
        assert "_toolguard_controlled_halt_response" in codex_runtime
        assert "terminal_message" in codex_runtime
        assert "without a terminal" in codex_runtime
        cli = (target / "cli.py").read_text()
        assert 'result.get("partial")' in cli
        assert 'result.get("completed") is False' in cli
        assert 'getattr(provider, "supports_password", False)' in (
            target / "dashboard_auth_middleware.py"
        ).read_text()
        assert "Codex echoes the input item" in (
            target / "codex_event_projector.py"
        ).read_text()
        assert '"session_id": session_key' in (target / "server.py").read_text()
        web = (target / "web_index.js").read_text()
        assert "searchParams.set(`resume`,e)" in web
        assert "history.replaceState" in web
        assert "let e=a.session_id" in web


if __name__ == "__main__":
    import sys

    main()
