#!/usr/bin/env python3
"""Install the Flow v2 contract and Hermes skill into one user's home."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil


FILES = {
    "flow_contract.py": pathlib.Path("swarm-bin/flow_contract.py"),
    "mission_adapter.py": pathlib.Path("swarm-bin/mission_adapter.py"),
    "delivery_coordinator.py": pathlib.Path("swarm-bin/delivery_coordinator.py"),
    "systemd/hermes-delivery-coordinator@.service": pathlib.Path(
        ".config/systemd/user/hermes-delivery-coordinator@.service"
    ),
    "systemd/hermes-delivery-coordinator@.timer": pathlib.Path(
        ".config/systemd/user/hermes-delivery-coordinator@.timer"
    ),
    "flow-policy.json": pathlib.Path("swarm-bin/flow-policy.json"),
    "hermes-flow-v2/SKILL.md": pathlib.Path(".hermes/skills/hermes-flow-v2/SKILL.md"),
}


def install(source: pathlib.Path, home: pathlib.Path) -> None:
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    for executable in ("flow_contract.py", "mission_adapter.py", "delivery_coordinator.py"):
        (home / FILES[executable]).chmod(0o755)


def check(source: pathlib.Path, home: pathlib.Path) -> None:
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            raise SystemExit(f"flow-v2-install-error: stale or missing {dst}")
    if os.name != "nt":
        for executable in ("flow_contract.py", "mission_adapter.py", "delivery_coordinator.py"):
            if not (home / FILES[executable]).stat().st_mode & 0o111:
                raise SystemExit(f"flow-v2-install-error: {executable} is not executable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = pathlib.Path(__file__).resolve().parent
    (check if args.check else install)(source, args.home.expanduser().resolve())
    print("hermes-flow-v2-install-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
