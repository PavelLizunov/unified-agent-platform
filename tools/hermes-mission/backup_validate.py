#!/usr/bin/env python3
"""Fail closed when a Hermes backup omits or corrupts authoritative state."""

from __future__ import annotations

import argparse
import os
import posixpath
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path


REQUIRED_FILES = ("state.db", "auth.json", "missions-v1.sqlite3")


class BackupValidationError(ValueError):
    """The archive is not a usable Hermes recovery point."""


def _entry_by_basename(names: list[str], basename: str) -> str:
    matches = [name for name in names if posixpath.basename(name) == basename]
    if len(matches) != 1:
        raise BackupValidationError(
            f"backup must contain exactly one {basename}; found {len(matches)}"
        )
    return matches[0]


def _check_sqlite_path(path: Path, *, required_table: str | None = None) -> None:
    try:
        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        ) as connection:
            result = [row[0] for row in connection.execute("PRAGMA quick_check")]
            if result != ["ok"]:
                raise BackupValidationError(
                    f"{path.name} quick_check failed: {result[:3]}"
                )
            if required_table is not None:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (required_table,),
                ).fetchone()
                if table is None:
                    raise BackupValidationError(
                        f"{path.name} is missing table {required_table}"
                    )
    except sqlite3.DatabaseError as error:
        raise BackupValidationError(
            f"{path.name} is not a readable SQLite database"
        ) from error


def _check_sqlite(
    archive: zipfile.ZipFile,
    entry: str,
    *,
    required_table: str | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="hermes-backup-check-") as temporary:
        snapshot = Path(temporary) / posixpath.basename(entry)
        with archive.open(entry) as source, snapshot.open("wb") as target:
            shutil.copyfileobj(source, target)
        _check_sqlite_path(snapshot, required_table=required_table)


def replace_mission_snapshot(archive_path: Path, mission_path: Path) -> None:
    """Replace the raw `.sqlite3` ZIP entry with a transactionally safe snapshot."""
    if not mission_path.is_file():
        raise BackupValidationError(f"MissionStore not found: {mission_path}")
    archive_path = archive_path.resolve()
    with tempfile.TemporaryDirectory(
        prefix="hermes-mission-snapshot-", dir=archive_path.parent
    ) as temporary:
        temporary_root = Path(temporary)
        snapshot = temporary_root / "missions-v1.sqlite3"
        rewritten = temporary_root / archive_path.name
        try:
            with closing(
                sqlite3.connect(
                    f"{mission_path.resolve().as_uri()}?mode=ro", uri=True
                )
            ) as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            _check_sqlite_path(snapshot, required_table="mission_events")
        except sqlite3.DatabaseError as error:
            raise BackupValidationError(
                "could not create a consistent MissionStore snapshot"
            ) from error

        try:
            with zipfile.ZipFile(archive_path) as source_archive, zipfile.ZipFile(
                rewritten, "w", zipfile.ZIP_DEFLATED, compresslevel=6
            ) as target_archive:
                mission_entries = [
                    entry
                    for entry in source_archive.infolist()
                    if posixpath.basename(entry.filename) == "missions-v1.sqlite3"
                ]
                arcname = (
                    mission_entries[0].filename
                    if mission_entries
                    else "missions-v1.sqlite3"
                )
                for entry in source_archive.infolist():
                    if posixpath.basename(entry.filename) == "missions-v1.sqlite3":
                        continue
                    with source_archive.open(entry) as source, target_archive.open(
                        entry, "w"
                    ) as target:
                        shutil.copyfileobj(source, target)
                target_archive.write(snapshot, arcname)
            os.replace(rewritten, archive_path)
        except (OSError, zipfile.BadZipFile) as error:
            raise BackupValidationError(
                "could not replace the MissionStore entry in the backup"
            ) from error


def validate_archive(path: Path) -> list[str]:
    """Validate critical files and return non-fatal completeness warnings."""
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_entry = archive.testzip()
            if corrupt_entry is not None:
                raise BackupValidationError(
                    f"backup zip contains a corrupt entry: {corrupt_entry}"
                )
            names = archive.namelist()
            entries = {
                basename: _entry_by_basename(names, basename)
                for basename in REQUIRED_FILES
            }
            _check_sqlite(archive, entries["state.db"])
            _check_sqlite(
                archive,
                entries["missions-v1.sqlite3"],
                required_table="mission_events",
            )
            basenames = {posixpath.basename(name) for name in names}
            warnings = []
            if ".env" not in basenames:
                warnings.append(".env")
            if not any(
                name.endswith(".sqlite") and "/.codex/" in f"/{name}"
                for name in names
            ):
                warnings.append(".codex/*.sqlite")
            return warnings
    except (OSError, zipfile.BadZipFile) as error:
        raise BackupValidationError("backup is not a readable zip archive") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-mission",
        type=Path,
        metavar="MISSIONS_DB",
        help="replace the archive entry with a sqlite3.backup() snapshot",
    )
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        if args.replace_mission is not None:
            replace_mission_snapshot(args.archive, args.replace_mission)
        warnings = validate_archive(args.archive)
    except BackupValidationError as error:
        raise SystemExit(f"FATAL: {error}") from error
    if warnings:
        print(f"WARNING: backup missing regeneratable files: {', '.join(warnings)}")
    print("hermes-backup-manifest-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
