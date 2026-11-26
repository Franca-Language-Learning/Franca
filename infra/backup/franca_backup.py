"""Franca's backup (story E01-008): a nightly encrypted copy of the database, and a monthly test that the copy can be
restored.

Each night:
1. A copy of the database is taken with SQLite's backup function, which includes changes still in the write-ahead
   log, and the copy is checked with PRAGMA integrity_check.
2. The copy is added to a restic repository. restic encrypts it with the password in the backup_password secret.
   Until an off-site store is chosen (before M3), the repository is on a second disk in the PC (disk J:).
3. Old copies are thinned out: one a day for 14 days, one a week for 8 weeks and one a month for 12 months are kept.

Once a month, after the backup, the latest copy is restored into a scratch folder, its database is checked, and
restic checks part of the repository's data. The live database is not touched by this test.

The results are written to backup.json and restore-test.json in the status folder, for the owner and for the health
monitoring (story E01-010).

For a real restore, see docs/restoring-a-backup.md: with the app stopped, `restore-latest` puts the latest copy in
place and keeps the current database beside it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATABASE = "franca.db"
KEEP = {"--keep-daily": "14", "--keep-weekly": "8", "--keep-monthly": "12"}
RESTORE_TEST_EVERY = timedelta(days=30)
HOST = "franca"
DEFAULT_BACKUP_TIME = "03:30"


class BackupError(Exception):
    """A step failed. The message says which, in words for the status file."""


Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=3600, check=False)


@dataclass(slots=True)
class Restic:
    """The restic command. The repository and its password are given in RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE."""

    run: Run = run_command

    def _restic(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run(["restic", *arguments])

    def _check(self, result: subprocess.CompletedProcess[str], what: str) -> str:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            raise BackupError(f"restic {what} failed: {detail[0][:300]}")
        return result.stdout

    def ensure_repository(self) -> None:
        if self._restic("cat", "config").returncode != 0:
            self._check(self._restic("init"), "init")

    def back_up(self, folder: Path) -> str:
        """Backs up the files in folder and returns the new snapshot's id."""
        output = self._check(self._restic("backup", "--json", "--host", HOST, "--tag", "nightly", str(folder)), "backup")
        for line in output.splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("message_type") == "summary":
                return str(message.get("snapshot_id", ""))
        return ""

    def thin_out(self) -> None:
        arguments = ["forget", "--host", HOST, "--prune"]
        for flag, value in KEEP.items():
            arguments += [flag, value]
        self._check(self._restic(*arguments), "forget")

    def restore_latest(self, target: Path) -> None:
        self._check(self._restic("restore", "latest", "--host", HOST, "--target", str(target)), "restore")

    def check_some_data(self) -> None:
        self._check(self._restic("check", "--read-data-subset", "5%"), "check")


def copy_database(source: Path, target: Path) -> None:
    """A consistent copy with SQLite's backup function, then checked."""
    if not source.is_file():
        raise BackupError(f"There is no database at {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    # Opened for writing, because a database in WAL mode needs its shared-memory file, also to be read.
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)
    check_database(target)


def keep_current(live: Path, kept: Path) -> None:
    """Keeps the database that is being replaced, with the changes still in its write-ahead log. A database that is too
    damaged to copy is kept as it is: the main file and its log files, under the new name."""
    try:
        with sqlite3.connect(live) as current, sqlite3.connect(kept) as copy:
            current.backup(copy)
    except sqlite3.Error:
        kept.unlink(missing_ok=True)
        for suffix in ("", "-wal", "-shm"):
            source = live.with_name(live.name + suffix)
            if source.exists():
                shutil.copyfile(source, kept.with_name(kept.name + suffix))


def check_database(path: Path) -> str:
    """Checks a database file and returns its schema version (the Alembic revision)."""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError(f"The database copy is damaged: {result}")
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"The database copy cannot be read: {error}") from error
    if not version:
        raise BackupError("The database copy has no schema version")
    return str(version[0])


@dataclass(slots=True)
class StatusFiles:
    folder: Path

    def write(self, name: str, **status: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self.folder / (name + ".new")
        temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.folder / name)

    def read(self, name: str) -> dict[str, str]:
        try:
            loaded: dict[str, str] = json.loads((self.folder / name).read_text(encoding="utf-8"))
            return loaded
        except OSError, ValueError:
            return {}


def health_check(url: str) -> Callable[[], bool]:
    def answers() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a fixed address inside the bundle
                return bool(response.status == 200)
        except OSError:
            return False

    return answers


@dataclass(slots=True)
class Backup:
    data: Path  # the app's data volume
    work: Path  # a folder for the copy and for restore tests, outside the data volume
    status: StatusFiles
    restic: Restic
    app_answers: Callable[[], bool] = field(default=lambda: False)

    def back_up(self, now: datetime) -> str:
        staging = self.work / "staging"
        try:
            copy_database(self.data / DATABASE, staging / DATABASE)
            self.restic.ensure_repository()
            snapshot = self.restic.back_up(staging)
            self.restic.thin_out()
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            return self._report("backup.json", "backup-failed", now, message=str(error))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
        return self._report("backup.json", "backed-up", now, snapshot=snapshot, message="The database was backed up")

    def restore_test_due(self, now: datetime) -> bool:
        last = self.status.read("restore-test.json").get("testedAt")
        if not last:
            return True
        try:
            return now - datetime.fromisoformat(last) >= RESTORE_TEST_EVERY
        except ValueError:
            return True

    def restore_test(self, now: datetime) -> str:
        scratch = self.work / "restore-test"
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            self.restic.restore_latest(scratch)
            restored = next(scratch.rglob(DATABASE), None)
            if restored is None:
                raise BackupError("The latest backup has no database in it")
            schema = check_database(restored)
            self.restic.check_some_data()
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            return self._report("restore-test.json", "restore-test-failed", now, key="testedAt", message=str(error))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return self._report(
            "restore-test.json",
            "restore-test-passed",
            now,
            key="testedAt",
            schema=schema,
            message="The latest backup was restored and checked",
        )

    def restore_latest(self, now: datetime) -> str:
        """Puts the latest backup in place of the live database. The app has to be stopped first."""
        if self.app_answers():
            return self._report("restore.json", "refused", now, message="The app is running. Stop it first, then restore.")
        incoming_folder = self.work / "restore"
        shutil.rmtree(incoming_folder, ignore_errors=True)
        live = self.data / DATABASE
        try:
            self.restic.restore_latest(incoming_folder)
            restored = next(incoming_folder.rglob(DATABASE), None)
            if restored is None:
                raise BackupError("The latest backup has no database in it")
            check_database(restored)
            incoming = live.with_name(DATABASE + ".restore")
            shutil.copyfile(restored, incoming)
            with open(incoming, "rb") as copied:
                os.fsync(copied.fileno())
            if live.exists():
                keep_current(live, self.data / f"franca-before-restore-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}.db")
            os.replace(incoming, live)
            for extra in (live.with_name(DATABASE + "-wal"), live.with_name(DATABASE + "-shm")):
                extra.unlink(missing_ok=True)
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            return self._report("restore.json", "restore-failed", now, message=str(error))
        finally:
            shutil.rmtree(incoming_folder, ignore_errors=True)
        return self._report("restore.json", "restored", now, message="The latest backup was put in place; the previous database was kept")

    def _report(self, name: str, result: str, now: datetime, key: str = "at", **details: str) -> str:
        line = {"result": result, key: now.astimezone(UTC).isoformat(timespec="seconds"), **details}
        print(json.dumps(line), flush=True)
        try:
            self.status.write(name, **line)
        except OSError as error:
            print(json.dumps({"result": "status-not-written", "message": str(error)}), flush=True)
        return result


# --- the service


def backup_time(text: str) -> str:
    if re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text.strip()):
        return text.strip()
    print(
        json.dumps({"result": "warning", "message": f"FRANCA_BACKUP_AT_UTC={text!r} is not HH:MM; using {DEFAULT_BACKUP_TIME}"}), flush=True
    )
    return DEFAULT_BACKUP_TIME


def next_run(now: datetime, at: str) -> datetime:
    """The next time of day `at` (HH:MM, UTC) after now."""
    hour, minute = (int(part) for part in at.split(":"))
    candidate = now.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def from_environment(environ: dict[str, str] | os._Environ[str]) -> Backup:
    return Backup(
        data=Path(environ.get("FRANCA_DATA_DIR", "/data")),
        work=Path(environ.get("FRANCA_BACKUP_WORK_DIR", "/cache/work")),
        status=StatusFiles(Path(environ.get("FRANCA_BACKUP_STATUS_DIR", "/status"))),
        restic=Restic(),
        app_answers=health_check(environ.get("FRANCA_HEALTH_URL", "http://app:8000/api/v1/health")),
    )


def main(argv: Sequence[str] = sys.argv[1:]) -> int:
    backup = from_environment(os.environ)
    command = argv[0] if argv else "serve"
    now = datetime.now(UTC)
    if command == "backup":
        return 0 if backup.back_up(now) == "backed-up" else 1
    if command == "restore-test":
        return 0 if backup.restore_test(now) == "restore-test-passed" else 1
    if command == "restore-latest":
        return 0 if backup.restore_latest(now) == "restored" else 1
    if command != "serve":
        print("Use: franca_backup.py [serve | backup | restore-test | restore-latest]", file=sys.stderr)
        return 2
    at = backup_time(os.environ.get("FRANCA_BACKUP_AT_UTC", DEFAULT_BACKUP_TIME))
    while True:
        wake = next_run(datetime.now(UTC), at)
        time.sleep(max(0.0, (wake - datetime.now(UTC)).total_seconds()))
        try:
            now = datetime.now(UTC)
            if backup.back_up(now) == "backed-up" and backup.restore_test_due(now):
                backup.restore_test(now)
        except Exception as error:  # noqa: BLE001 - the service keeps running and tries again the next night
            print(json.dumps({"result": "error", "message": repr(error)}), flush=True)


if __name__ == "__main__":
    sys.exit(main())
