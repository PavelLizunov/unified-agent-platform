#!/usr/bin/env python3
"""Install the Flow v2 contract and Hermes skill into one user's home."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil


FILES = {
    "flow_contract.py": pathlib.Path("swarm-bin/flow_contract.py"),
    "flow-policy.json": pathlib.Path("swarm-bin/flow-policy.json"),
    "hermes-flow-v2/SKILL.md": pathlib.Path(".hermes/skills/hermes-flow-v2/SKILL.md"),
}


def install(source: pathlib.Path, home: pathlib.Path) -> None:
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (home / FILES["flow_contract.py"]).chmod(0o755)


def check(source: pathlib.Path, home: pathlib.Path) -> None:
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            raise SystemExit(f"flow-v2-install-error: stale or missing {dst}")
    if os.name != "nt" and not (home / FILES["flow_contract.py"]).stat().st_mode & 0o111:
        raise SystemExit("flow-v2-install-error: flow_contract.py is not executable")


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
