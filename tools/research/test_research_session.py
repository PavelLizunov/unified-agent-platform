#!/usr/bin/env python3
"""Hermetic component test for the controlled research-session facade."""

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "clusters/prod/infra/files/hermes_research_session.py"
SPEC = importlib.util.spec_from_file_location("hermes_research_session", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> None:
    calls = []

    def success_runner(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(
                {
                    "summary": "Verified bounded answer.",
                    "citations": [
                        {
                            "url": "https://docs.example.com/source",
                            "title": "Primary source",
                            "snippet": "A bounded factual snippet.",
                            "source_time": "2026-07-20",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    with tempfile.TemporaryDirectory() as state:
        auth_home = Path(state) / "source-codex"
        auth_home.mkdir()
        (auth_home / "auth.json").write_text("{}", encoding="utf-8")
        first = MODULE.run_research_session(
            "Find the current primary-source fact",
            ["example.com"],
            3,
            state_root=state,
            codex_home=auth_home,
            runner=success_runner,
        )
        second = MODULE.run_research_session(
            "Find the current primary-source fact",
            ["example.com"],
            3,
            state_root=state,
            codex_home=auth_home,
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("completed request must be replayed from durable state")
            ),
        )
        assert first == second
        assert first["status"] == "complete"
        assert first["trust"] == "untrusted_external_content"
        assert len(calls) == 1
        command, kwargs = calls[0]
        assert command[:7] == [
            "codex", "--search", "--disable", "shell_tool",
            "--ask-for-approval", "never", "exec"
        ]
        assert "--ephemeral" in command and "--ignore-user-config" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert kwargs["env"].keys() <= {
            "PATH", "HOME", "CODEX_HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"
        }
        assert kwargs["env"]["HOME"] == kwargs["cwd"]
        child_auth = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        assert child_auth.parent.parent == Path(kwargs["cwd"])
        assert "UNTRUSTED EXTERNAL CONTENT" in kwargs["input"]
        assert "example.com" in kwargs["input"]

    with tempfile.TemporaryDirectory() as state:
        auth_home = Path(state) / "deployment-codex"
        auth_home.mkdir()
        (auth_home / "auth.json").write_text("{}", encoding="utf-8")
        with mock.patch.dict("os.environ", {"CODEX_HOME": ""}), mock.patch.object(
            MODULE, "DEFAULT_CODEX_HOME", str(auth_home)
        ):
            fallback = MODULE.run_research_session(
                "Use the deployment Codex authority",
                ["example.com"],
                1,
                state_root=state,
                runner=success_runner,
            )
        assert fallback["status"] == "complete"

    invalid = MODULE.run_research_session(
        "goal", ["https://example.com/private"], 5, state_root="unused"
    )
    assert invalid["error"] == "invalid_request" and invalid["retryable"] is False

    attempts = []

    def transient_runner(command, **_kwargs):
        attempts.append(command)
        return subprocess.CompletedProcess(command, 1, "", "HTTP 429 rate limit")

    with tempfile.TemporaryDirectory() as state:
        auth_home = Path(state) / "source-codex"
        auth_home.mkdir()
        (auth_home / "auth.json").write_text("{}", encoding="utf-8")
        failure = MODULE.run_research_session(
            "Check a transient provider response",
            max_sources=2,
            state_root=state,
            codex_home=auth_home,
            runner=transient_runner,
            sleeper=lambda _seconds: None,
        )
    assert len(attempts) == 2
    assert failure["error"] == "rate_limited" and failure["retryable"] is True
    assert "owner" not in failure["message"].lower()
    assert "429" not in json.dumps(failure)

    try:
        MODULE._validate_result(
            {
                "summary": "bad",
                "citations": [
                    {
                        "url": "http://127.0.0.1/secret",
                        "title": "bad",
                        "snippet": "bad",
                        "source_time": None,
                    }
                ],
            },
            (),
            1,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe citation URL must be rejected")

    print("controlled-research-session-ok")


if __name__ == "__main__":
    main()
