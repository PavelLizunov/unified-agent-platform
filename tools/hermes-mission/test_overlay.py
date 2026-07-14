#!/usr/bin/env python3
"""Read-only integration check for the pinned central Hermes overlay."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import tempfile


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
        assert checked.returncode == 0 and checked.stdout.count("exact-patched") == 4, checked.stderr

        commands = (clone / "hermes_cli/commands.py").read_text(encoding="utf-8")
        gateway = (clone / "gateway/run.py").read_text(encoding="utf-8")
        api = (clone / "gateway/platforms/api_server.py").read_text(encoding="utf-8")
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

        subprocess.run(
            [
                "python3",
                "-m",
                "py_compile",
                str(clone / "hermes_cli/uap_missions.py"),
                str(clone / "hermes_cli/commands.py"),
                str(clone / "gateway/run.py"),
                str(clone / "gateway/platforms/api_server.py"),
            ],
            check=True,
        )

        image_root = pathlib.Path(temp) / "image-root"
        for relative in (
            "hermes_cli/commands.py",
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
        assert image_check.returncode == 0 and image_check.stdout.count("exact-patched") == 4

        target = clone / "gateway/run.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        tampered = run(clone)
        assert tampered.returncode != 0
        assert "fingerprint mismatch" in tampered.stderr

    print("hermes mission overlay checks passed")


if __name__ == "__main__":
    main()
