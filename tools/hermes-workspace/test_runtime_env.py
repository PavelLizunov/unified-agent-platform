#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile


TOOL = pathlib.Path(__file__).with_name("install_runtime_env.py")
SPEC = importlib.util.spec_from_file_location("install_runtime_env", TOOL)
assert SPEC and SPEC.loader
runtime_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_env)


def source_text() -> str:
    return "\n".join(
        f"{name}={value}"
        for name, value in {
            "COOKIE_SECURE": "0",
            "HERMES_API_TOKEN": "api-token",
            "HERMES_API_URL": "http://100.94.228.67:30642",
            "HERMES_CENTRAL_ONLY": "1",
            "HERMES_DASHBOARD_PASSWORD": "dashboard-password",
            "HERMES_DASHBOARD_URL": "http://100.94.228.67:30911",
            "HERMES_DASHBOARD_USERNAME": "dashboard-user",
            "HERMES_PASSWORD": "workspace-password",
            "HOST": "0.0.0.0",
            "PORT": "3000",
        }.items()
    ) + "\n"


def main() -> None:
    drop_in = pathlib.Path(__file__).with_name("systemd") / "10-uap-runtime-env.conf"
    assert drop_in.read_text(encoding="utf-8").splitlines() == [
        "[Service]",
        "EnvironmentFile=",
        "EnvironmentFile=/home/uap/.config/uap/hermes-workspace.env",
    ]
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        source = root / "legacy.env"
        target = root / "private" / "hermes-workspace.env"
        source.write_text(source_text(), encoding="utf-8")
        if os.name == "posix":
            source.chmod(0o600)

        owner = b"owner-capability-that-is-long-enough-123456"
        runtime_env.install(source, target, owner + b"\n")
        runtime_env.check(target)
        installed = target.read_text(encoding="utf-8")
        assert installed.count("HERMES_MISSION_OWNER_KEY=") == 1
        assert "owner-capability-that-is-long-enough-123456" in installed
        if os.name == "posix":
            assert target.stat().st_mode & 0o777 == 0o600
            assert target.parent.stat().st_mode & 0o777 == 0o700

        runtime_env.install(target, target, owner)
        runtime_env.check(target)

        source.write_text(source_text() + "UNKNOWN=value\n", encoding="utf-8")
        if os.name == "posix":
            source.chmod(0o600)
        try:
            runtime_env.install(source, target, owner)
            raise AssertionError("unknown runtime variable was accepted")
        except runtime_env.EnvironmentError:
            pass

        try:
            runtime_env.install(target, target, b"short")
            raise AssertionError("short owner capability was accepted")
        except runtime_env.EnvironmentError:
            pass
    print("hermes workspace runtime env checks passed")


if __name__ == "__main__":
    main()
