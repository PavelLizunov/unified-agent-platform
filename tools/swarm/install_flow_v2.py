#!/usr/bin/env python3
"""Install the Flow v2 contract and Hermes skill into one user's home."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import tempfile


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
_LEGACY_MODEL_FIELDS = {
    "author_model", "reviewer_model", "author_reasoning_effort", "reviewer_reasoning_effort",
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


def migrate_profile(path: pathlib.Path) -> bool:
    """Atomically migrate one stopped legacy profile to policy-authoritative schema v3."""
    path = path.expanduser().resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("flow-v2-install-error: delivery profile must be an object")
    if value.get("schema_version") == 3:
        from delivery_coordinator import load_profile

        load_profile(path)
        return False
    if value.get("schema_version") not in {1, 2}:
        raise SystemExit("flow-v2-install-error: only profile schema 1/2 can migrate to 3")
    migrated = {key: item for key, item in value.items() if key not in _LEGACY_MODEL_FIELDS}
    migrated.update(schema_version=3, max_review_cycles=3)
    migrated.setdefault("route_flags", [])
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            json.dump(migrated, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = pathlib.Path(handle.name)
        if os.name != "nt":
            temporary.chmod(0o600)
        from delivery_coordinator import load_profile

        load_profile(temporary)
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            path.chmod(0o600)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--migrate-profile", type=pathlib.Path)
    args = parser.parse_args()
    if args.check and args.migrate_profile:
        parser.error("--check cannot mutate --migrate-profile")
    source = pathlib.Path(__file__).resolve().parent
    (check if args.check else install)(source, args.home.expanduser().resolve())
    if args.migrate_profile:
        changed = migrate_profile(args.migrate_profile)
        print("hermes-flow-v2-profile-migrated" if changed else "hermes-flow-v2-profile-current")
    print("hermes-flow-v2-install-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
