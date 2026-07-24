"""Mechanism test for ADR-027's pinned Hermes compatibility patch."""

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "clusters/prod/infra/hermes-agent-config.yaml"


def check(condition: bool, message: str = "runtime-compat check failed") -> None:
    """Raise AssertionError when *condition* is false.  Unlike bare ``assert``,
    this is never stripped by ``python -O``."""
    if not condition:
        raise AssertionError(message)


def main() -> None:
    import yaml

    script = yaml.safe_load(PATCH.read_text(encoding="utf-8"))["data"]["runtime-compat.py"]
    failure = '    if file_mutation_result_landed(tool_name, result):\n        return False, ""\n'
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        (target / "display.py").write_text(failure + "\n    data = safe_json_loads(result)\n")
        (target / "tool_guardrails.py").write_text(failure + '\n    if tool_name == "terminal":\n')
        (target / "codex_runtime.py").write_text(
            "            if item_type in _CODEX_TOOL_ITEM_TYPES:\n"
            "                _fire_tool_completed(item)\n"
            '            elif item_type == "agentMessage":\n'
            "\n    # If the turn signalled the underlying client is wedged (deadline\n"
        )
        (target / "cli.py").write_text(
            '                        if isinstance(result, dict) and result.get("failed"):\n'
            "                            _exit_code = 1\n"
            '                            if os.environ.get("HERMES_KANBAN_TASK") and result.get(\n'
        )
        (target / "codex_event_projector.py").write_text(
            '        if item_type == "userMessage":\n'
            "            return self._project_user_message(item)\n"
        )
        (target / "web_index.js").write_text(
            "if(n===`session.info`){let e=LJ(a);e!==void 0&&i?.(e)}"
        )
        script_path = target / "patch.py"
        script_path.write_text(script)

        subprocess.run([sys.executable, str(script_path), str(target)], check=True)
        subprocess.run([sys.executable, str(script_path), str(target)], check=True)

        check('tool_name == "exec_command"' in (target / "display.py").read_text())
        check('tool_name == "exec_command"' in (target / "tool_guardrails.py").read_text())
        codex_runtime = (target / "codex_runtime.py").read_text()
        check('item_type == "commandExecution"' in codex_runtime)
        check("session.request_interrupt()" in codex_runtime)
        check("_toolguard_controlled_halt_response" in codex_runtime)
        check("turn.final_text" in codex_runtime)
        check("not turn.interrupted" in codex_runtime)
        check("turn.error is None" in codex_runtime)
        check("without a terminal" in codex_runtime)
        cli = (target / "cli.py").read_text()
        check('result.get("partial")' in cli)
        check('result.get("completed") is False' in cli)
        check(
            "Codex echoes the input item"
            in (target / "codex_event_projector.py").read_text()
        )
        web = (target / "web_index.js").read_text()
        check("a.stored_session_id" in web)
        check("searchParams.set(`resume`,e)" in web)
        check("history.replaceState" in web)
        check("let n=LJ(a)" in web)

    _run_post_turn_decision(codex_runtime)

    print("hermes-runtime-compat-ok")



def _run_post_turn_decision(codex_runtime_src: str) -> None:
    """Execute the injected post-turn decision block with minimal fakes."""
    from types import SimpleNamespace

    # Extract the decision block: from "guardrail_halt = getattr" to the
    # line before "# If the turn signalled" (the second occurrence).
    start = codex_runtime_src.index("guardrail_halt = getattr(agent")
    end = codex_runtime_src.index(
        "    # If the turn signalled the underlying client is wedged (deadline",
        start,
    )
    block = codex_runtime_src[start:end]
    # Dedent from 4-space method level to top-level for exec
    lines = block.split("\n")
    dedented = "\n".join(
        line[4:] if line.startswith("    ") else line for line in lines
    )
    code = compile(dedented, "<post-turn-decision>", "exec")

    FAILURE_TEXT = (
        "Codex app-server turn ended after a tool result without a terminal "
        "assistant response; the session was retired."
    )
    HALT_TEXT = "guardrail controlled halt"

    def make_agent(halt=None):
        agent = SimpleNamespace()
        if halt is not None:
            agent._tool_guardrail_halt_decision = halt
        agent._toolguard_controlled_halt_response = lambda h: HALT_TEXT
        return agent

    def run(turn, agent):
        exec(code, {"agent": agent, "turn": turn, "getattr": getattr, "str": str})

    # (a) Existing turn.error is preserved verbatim
    turn = SimpleNamespace(
        final_text="", projected_messages=[], interrupted=False,
        error="OAuth refresh died", should_retire=False,
    )
    run(turn, make_agent())
    check(turn.error == "OAuth refresh died", f"error overwritten: {turn.error}")
    check(turn.final_text == "", f"final_text overwritten: {turn.final_text}")

    # (b) Empty final_text with a projected plan/assistant message -> synthetic failure
    turn = SimpleNamespace(
        final_text="",
        projected_messages=[{"role": "assistant", "content": "plan step 1"}],
        interrupted=False, error=None, should_retire=False,
    )
    run(turn, make_agent())
    check(turn.final_text == FAILURE_TEXT, f"final_text: {turn.final_text}")
    check(turn.interrupted is True, "interrupted must be set on synthetic failure")
    check(turn.error == FAILURE_TEXT, f"error: {turn.error}")
    check(turn.should_retire is True, "should_retire must be set on synthetic failure")

    # (c) Non-empty final_text remains successful
    turn = SimpleNamespace(
        final_text="Here is the answer.",
        projected_messages=[{"role": "assistant", "content": "Here is the answer."}],
        interrupted=False, error=None, should_retire=False,
    )
    run(turn, make_agent())
    check(turn.final_text == "Here is the answer.", f"final_text: {turn.final_text}")
    check(turn.error is None, f"error must stay None: {turn.error}")
    check(turn.interrupted is False, "interrupted must stay False on success")
    check(turn.should_retire is False, "should_retire must stay False on success")

    # (d) Guardrail halt produces controlled halt text, not failure
    turn = SimpleNamespace(
        final_text="", projected_messages=[], interrupted=True,
        error="halted", should_retire=False,
    )
    run(turn, make_agent(halt="some-decision"))
    check(turn.final_text == HALT_TEXT, f"final_text: {turn.final_text}")
    check(turn.interrupted is False, "interrupted must be cleared on controlled halt")
    check(turn.error is None, f"error must be cleared on controlled halt: {turn.error}")
    check(turn.should_retire is False, "should_retire must stay False on controlled halt")
    check(
        any(m.get("content") == HALT_TEXT for m in turn.projected_messages),
        "controlled halt text must be projected",
    )


if __name__ == "__main__":
    main()
