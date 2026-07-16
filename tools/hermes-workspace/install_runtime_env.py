#!/usr/bin/env python3
"""Atomically install the protected build-1 Workspace runtime environment."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import tempfile
import urllib.parse


OWNER_KEY = "HERMES_MISSION_OWNER_KEY"
EXPECTED_KEYS = {
    "COOKIE_SECURE",
    "HERMES_API_TOKEN",
    "HERMES_API_URL",
    "HERMES_CENTRAL_ONLY",
    "HERMES_DASHBOARD_PASSWORD",
    "HERMES_DASHBOARD_URL",
    "HERMES_DASHBOARD_USERNAME",
    OWNER_KEY,
    "HERMES_PASSWORD",
    "HOST",
    "PORT",
}
_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class EnvironmentError(ValueError):
    pass


def _private_file(path: pathlib.Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise EnvironmentError(f"runtime environment is not a regular file: {path}")
    if os.name == "posix":
        stat = path.stat()
        if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
            raise EnvironmentError(f"runtime environment is not owner-only: {path}")


def _parse(path: pathlib.Path, *, owner_key_required: bool) -> dict[str, str]:
    _private_file(path)
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw:
            raise EnvironmentError("runtime environment line has no equals sign")
        name, value = raw.split("=", 1)
        if not _NAME.fullmatch(name) or name in values:
            raise EnvironmentError("runtime environment has an invalid or duplicate key")
        if not value or "\x00" in value:
            raise EnvironmentError(f"runtime environment value is empty: {name}")
        values[name] = value
    expected = EXPECTED_KEYS if owner_key_required else EXPECTED_KEYS - {OWNER_KEY}
    if set(values) != expected and set(values) != EXPECTED_KEYS:
        raise EnvironmentError("runtime environment keys do not match the closed contract")
    if owner_key_required and set(values) != EXPECTED_KEYS:
        raise EnvironmentError("runtime environment has no owner capability")
    return values


def _validate(values: dict[str, str]) -> None:
    if set(values) != EXPECTED_KEYS or values["HERMES_CENTRAL_ONLY"] != "1":
        raise EnvironmentError("runtime environment violates central-only contract")
    for name in ("HERMES_API_URL", "HERMES_DASHBOARD_URL"):
        parsed = urllib.parse.urlsplit(values[name])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise EnvironmentError(f"runtime environment URL is invalid: {name}")
    try:
        port = int(values["PORT"])
    except ValueError as error:
        raise EnvironmentError("runtime environment PORT is invalid") from error
    if not 1 <= port <= 65535:
        raise EnvironmentError("runtime environment PORT is invalid")
    owner = values[OWNER_KEY]
    if not 32 <= len(owner.encode("utf-8")) <= 512 or any(
        character in owner for character in "\r\n\x00"
    ):
        raise EnvironmentError("owner capability is invalid")


def install(source: pathlib.Path, target: pathlib.Path, owner_key: bytes) -> None:
    if len(owner_key) > 514:
        raise EnvironmentError("owner capability is too large")
    owner_key = owner_key.rstrip(b"\r\n")
    try:
        owner = owner_key.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EnvironmentError("owner capability is not UTF-8") from error
    values = _parse(source.resolve(), owner_key_required=False)
    values[OWNER_KEY] = owner
    _validate(values)

    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(target.parent, 0o700)
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as handle:
            for name in sorted(values):
                handle.write(f"{name}={values[name]}\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = pathlib.Path(handle.name)
        if os.name == "posix":
            temporary.chmod(0o600)
        os.replace(temporary, target)
        temporary = None
        if os.name == "posix":
            target.chmod(0o600)
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def check(target: pathlib.Path) -> None:
    _validate(_parse(target.expanduser().resolve(), owner_key_required=True))
    if os.name == "posix" and target.expanduser().resolve().parent.stat().st_mode & 0o077:
        raise EnvironmentError("runtime environment directory is not owner-only")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=pathlib.Path, required=True)
    parser.add_argument("--source", type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.source is not None:
                parser.error("--check does not accept --source")
            check(args.target)
        else:
            if args.source is None:
                parser.error("--source is required when installing")
            install(args.source, args.target, sys.stdin.buffer.read(515))
        print("hermes-workspace-runtime-env-ok")
        return 0
    except (EnvironmentError, OSError, UnicodeError) as error:
        print(f"hermes-workspace-runtime-env-error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
