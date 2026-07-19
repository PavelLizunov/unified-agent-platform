#!/usr/bin/env python3
"""Install the Flow v2 contract and Hermes skill into one user's home."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
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
    "profiles/delivery-flow-pilot-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-flow-pilot-registered-v4.json"
    ),
    "profiles/delivery-flow-pilot-owner-gate-v4.json": pathlib.Path(
        ".config/uap/delivery-flow-pilot-owner-gate-v4.json"
    ),
    "profiles/delivery-vpnctl-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-vpnctl-registered-v4.json"
    ),
    "profiles/delivery-vpnrouter-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-vpnrouter-registered-v4.json"
    ),
    "profiles/delivery-vpnrouter-gateway-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-vpnrouter-gateway-registered-v4.json"
    ),
    "profiles/delivery-suflyor-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-suflyor-registered-v4.json"
    ),
    "profiles/delivery-spark-runner-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-spark-runner-registered-v4.json"
    ),
    "profiles/delivery-subfleet-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-subfleet-registered-v4.json"
    ),
    "profiles/delivery-slipstream-rust-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-slipstream-rust-registered-v4.json"
    ),
    "profiles/delivery-uap-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-uap-registered-v4.json"
    ),
    "profiles/delivery-gs-ninitux-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-gs-ninitux-registered-v4.json"
    ),
    "profiles/delivery-ninitux-landing-registered-v4.json": pathlib.Path(
        ".config/uap/delivery-ninitux-landing-registered-v4.json"
    ),
}
_PRIVATE_TARGETS = {
    pathlib.Path(".config/uap/delivery-flow-pilot-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-flow-pilot-owner-gate-v4.json"),
    pathlib.Path(".config/uap/delivery-vpnctl-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-vpnrouter-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-vpnrouter-gateway-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-suflyor-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-spark-runner-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-subfleet-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-slipstream-rust-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-uap-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-gs-ninitux-registered-v4.json"),
    pathlib.Path(".config/uap/delivery-ninitux-landing-registered-v4.json"),
}
_LEGACY_MODEL_FIELDS = {
    "author_model", "reviewer_model", "author_reasoning_effort", "reviewer_reasoning_effort",
}


def _build1_overlay(
    source: pathlib.Path,
    hermes_root: pathlib.Path,
    *,
    check: bool,
    runner=subprocess.run,
) -> None:
    command = [
        sys.executable,
        str(source.parent / "hermes-mission" / "apply_overlay.py"),
        str(hermes_root),
        "--build1-runtime",
    ]
    if check:
        command.append("--check")
    result = runner(command, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit(
            "flow-v2-install-error: build-1 Hermes overlay failed: "
            + ((result.stderr or result.stdout).strip() or "unknown error")
        )
    if check and result.stdout.count("exact-patched") != 3:
        raise SystemExit("flow-v2-install-error: build-1 Hermes overlay is not exact")


def install(
    source: pathlib.Path, home: pathlib.Path, hermes_root: pathlib.Path | None = None
) -> None:
    if hermes_root is not None:
        _build1_overlay(source, hermes_root, check=False)
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if os.name != "nt" and relative_target in _PRIVATE_TARGETS:
            dst.parent.chmod(0o700)
            dst.chmod(0o600)
    for executable in ("flow_contract.py", "mission_adapter.py", "delivery_coordinator.py"):
        (home / FILES[executable]).chmod(0o755)


def check(
    source: pathlib.Path, home: pathlib.Path, hermes_root: pathlib.Path | None = None
) -> None:
    for relative_source, relative_target in FILES.items():
        src = source / relative_source
        dst = home / relative_target
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            raise SystemExit(f"flow-v2-install-error: stale or missing {dst}")
        if os.name != "nt" and relative_target in _PRIVATE_TARGETS:
            if dst.parent.stat().st_mode & 0o777 != 0o700:
                raise SystemExit(f"flow-v2-install-error: insecure profile directory {dst.parent}")
            if dst.stat().st_mode & 0o777 != 0o600:
                raise SystemExit(f"flow-v2-install-error: insecure profile mode {dst}")
    if os.name != "nt":
        for executable in ("flow_contract.py", "mission_adapter.py", "delivery_coordinator.py"):
            if not (home / FILES[executable]).stat().st_mode & 0o111:
                raise SystemExit(f"flow-v2-install-error: {executable} is not executable")
    if hermes_root is not None:
        _build1_overlay(source, hermes_root, check=True)


def _systemd_unit_state(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"flow-v2-install-error: cannot verify {unit} is inactive") from error
    return result.stdout.strip() or "unknown"


def _require_profile_units_inactive(path: pathlib.Path, unit_state=None) -> None:
    prefix, suffix = "delivery-", ".json"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        raise SystemExit("flow-v2-install-error: profile must be named delivery-<instance>.json")
    instance = path.name[len(prefix):-len(suffix)]
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not instance or any(character not in allowed for character in instance):
        raise SystemExit("flow-v2-install-error: invalid delivery profile instance")
    inspect = unit_state or _systemd_unit_state
    for kind in ("timer", "service"):
        unit = f"hermes-delivery-coordinator@{instance}.{kind}"
        state = inspect(unit)
        if state != "inactive":
            raise SystemExit(f"flow-v2-install-error: {unit} must be inactive (got {state})")


def _require_all_profile_units_inactive(home: pathlib.Path, unit_state=None) -> None:
    for path in sorted((home / ".config/uap").glob("delivery-*.json")):
        _require_profile_units_inactive(path, unit_state)


def migrate_profile(path: pathlib.Path, *, unit_state=None) -> bool:
    """Validate a current profile or atomically migrate stopped schema 1/2 to v3."""
    path = path.expanduser().resolve()
    _require_profile_units_inactive(path, unit_state)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("flow-v2-install-error: delivery profile must be an object")
    if value.get("schema_version") in {3, 4}:
        from delivery_coordinator import load_profile

        load_profile(path)
        return False
    if value.get("schema_version") not in {1, 2}:
        raise SystemExit(
            "flow-v2-install-error: only profile schema 1/2 can migrate to 3; "
            "schema 3/4 are already current"
        )
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
    parser.add_argument(
        "--hermes-root",
        type=pathlib.Path,
        default=pathlib.Path("/home/uap/hermes-agent"),
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--migrate-profile", type=pathlib.Path)
    args = parser.parse_args()
    if args.check and args.migrate_profile:
        parser.error("--check cannot mutate --migrate-profile")
    source = pathlib.Path(__file__).resolve().parent
    home = args.home.expanduser().resolve()
    hermes_root = args.hermes_root.expanduser().resolve()
    _require_all_profile_units_inactive(home)
    (check if args.check else install)(source, home, hermes_root)
    if args.migrate_profile:
        changed = migrate_profile(args.migrate_profile)
        print("hermes-flow-v2-profile-migrated" if changed else "hermes-flow-v2-profile-current")
    print("hermes-flow-v2-install-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
