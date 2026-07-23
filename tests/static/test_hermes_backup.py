#!/usr/bin/env python3
"""Static and hermetic gate for the authoritative Hermes backup."""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import tempfile
import zipfile
from contextlib import closing

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools/hermes-mission/backup_validate.py"
SPEC = importlib.util.spec_from_file_location("backup_validate", VALIDATOR_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _sqlite(path: pathlib.Path, statement: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()


def _archive(
    root: pathlib.Path,
    *,
    include_mission: bool = True,
    corrupt_mission: bool = False,
) -> pathlib.Path:
    state = root / "state.db"
    mission = root / "missions-v1.sqlite3"
    _sqlite(state, "CREATE TABLE sessions(id TEXT PRIMARY KEY)")
    if corrupt_mission:
        mission.write_bytes(b"not a sqlite database")
    else:
        _sqlite(
            mission,
            "CREATE TABLE mission_events(mission_id TEXT, sequence INTEGER)",
        )
    archive = root / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(state, "state.db")
        output.writestr("auth.json", "{}")
        output.writestr(".codex/auth.json", "{}")
        output.writestr(".env", "managed=true")
        output.writestr(".codex/state.sqlite", b"derived")
        if include_mission:
            output.write(mission, "missions-v1.sqlite3")
    return archive


def _expect_failure(path: pathlib.Path, fragment: str) -> None:
    try:
        validator.validate_archive(path)
    except validator.BackupValidationError as error:
        assert fragment in str(error), error
    else:
        raise AssertionError(f"backup unexpectedly passed: {path}")


def main() -> None:
    backup_manifest = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-agent-backup.yaml").read_text(
            encoding="utf-8"
        )
    )
    deployment = next(
        document
        for document in yaml.safe_load_all(
            (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(
                encoding="utf-8"
            )
        )
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "hermes-agent"
    )
    pod_spec = backup_manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    dump = next(
        container
        for container in pod_spec["initContainers"]
        if container["name"] == "dump"
    )
    gateway = next(
        container
        for container in deployment["spec"]["template"]["spec"]["containers"]
        if container["name"] == "gateway"
    )
    assert dump["image"] == gateway["image"]
    dump_script = "\n".join(dump["args"])
    assert (
        "/opt/hermes/.venv/bin/python "
        "/opt/uap-backup/backup_validate.py"
    ) in dump_script
    assert "--replace-mission /opt/data/missions-v1.sqlite3 \"$zip\"" in dump_script
    assert {
        "name": "backup-validator",
        "mountPath": "/opt/uap-backup/backup_validate.py",
        "subPath": "backup_validate.py",
        "readOnly": True,
    } in dump["volumeMounts"]
    assert next(
        volume for volume in pod_spec["volumes"]
        if volume["name"] == "backup-validator"
    ) == {
        "name": "backup-validator",
        "configMap": {
            "name": "hermes-mission-runtime",
            "defaultMode": 0o555,
        },
    }
    runtime_config = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-mission-runtime.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert runtime_config["data"]["backup_validate.py"] == (
        VALIDATOR_PATH.read_text(encoding="utf-8")
    )
    restore_canary = (
        ROOT / "tests/ops/check-hermes-agent-restore.sh"
    ).read_text(encoding="utf-8")
    assert 'pvc="hermes-restore-canary-$suffix"' in restore_canary
    assert 'job="hermes-restore-canary-$suffix"' in restore_canary
    assert "claimName: $pvc" in restore_canary
    assert "missions-v1.sqlite3" in restore_canary
    assert "runAsUser: 0" in restore_canary
    assert 'jsonpath=\'{.status.failed}\'' in restore_canary
    assert "hermes-agent-restore-ok" in restore_canary

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        assert validator.validate_archive(_archive(root)) == []

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        archive = _archive(root, include_mission=False)
        mission = root / "missions-v1.sqlite3"
        with closing(sqlite3.connect(mission)) as connection:
            connection.execute(
                "INSERT INTO mission_events(mission_id, sequence) VALUES (?, ?)",
                ("mission-canary", 1),
            )
            connection.commit()
        validator.replace_mission_snapshot(archive, mission)
        assert validator.validate_archive(archive) == []
        with zipfile.ZipFile(archive) as source:
            names = [
                entry
                for entry in source.namelist()
                if pathlib.PurePosixPath(entry).name == "missions-v1.sqlite3"
            ]
            assert names == ["missions-v1.sqlite3"]
            restored = root / "restored.sqlite3"
            restored.write_bytes(source.read(names[0]))
        with closing(sqlite3.connect(restored)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM mission_events"
            ).fetchone() == (1,)

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        _expect_failure(
            _archive(root, include_mission=False),
            "backup is missing root file missions-v1.sqlite3",
        )

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        _expect_failure(
            _archive(root, corrupt_mission=True),
            "missions-v1.sqlite3 is not a readable SQLite database",
        )

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        archive = _archive(root)
        mission = root / "wrong-schema.sqlite3"
        _sqlite(mission, "CREATE TABLE unrelated(id INTEGER)")
        replacement = root / "wrong-schema.zip"
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(
            replacement, "w"
        ) as output:
            for entry in source.infolist():
                if pathlib.PurePosixPath(entry.filename).name == (
                    "missions-v1.sqlite3"
                ):
                    output.write(mission, entry.filename)
                else:
                    output.writestr(entry, source.read(entry))
        _expect_failure(replacement, "is missing table mission_events")

    print("hermes-backup-ok")


if __name__ == "__main__":
    main()
