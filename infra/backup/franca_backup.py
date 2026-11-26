"""Franca's backup (story E01-008): a nightly encrypted copy of the database, and a monthly test that the copy can be
restored.

Each night (or as soon as the PC is on again after a night it was off):
1. A copy of the database is taken with SQLite's backup function, which includes changes still in the write-ahead
   log, and the copy is checked with PRAGMA integrity_check.
2. The copy is added to a restic repository. restic encrypts it with the password in the backup_password secret.
   Until an off-site store is chosen (before M3), the repository is on a second disk in the PC (disk J:).
3. Old copies are thinned out: one a day for 14 days, one a week for 8 weeks and one a month for 12 months are kept.

Once a month, after the backup, the latest copy is restored into a scratch folder, its database is checked, and
restic reads back all of the repository's data. The live database is not touched by this test. (The test runs in the
backup container, which has the data volume mounted for the nightly copy; the scratch folder is in its cache volume.)

The results are written to backup.json and restore-test.json in the status folder, for the owner and for the health
monitoring (story E01-010). On a new installation, the start of the wait for the app's database is written to
backup-waiting.json.

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
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATABASE = "franca.db"
KEEP = {"--keep-daily": "14", "--keep-weekly": "8", "--keep-monthly": "12"}
RESTORE_TEST_EVERY = timedelta(days=30)
HOST = "franca"
DEFAULT_BACKUP_TIME = "03:30"
# The installer puts this file on the backup disk. Without it the disk counts as missing, so a backup is never made
# into an empty folder on another disk (as happens on a server when the disk is not mounted).
DISK_MARKER = ".franca-backup-disk"
# restic's exit code when there is no repository at the given place.
NO_REPOSITORY = 10
HEALTHY_FOR = timedelta(hours=48)


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
        """Makes the repository if there is none. A repository that is there but cannot be opened (a wrong password,
        a damaged file) is reported and left alone."""
        found = self._restic("cat", "config")
        if found.returncode == NO_REPOSITORY:
            self._check(self._restic("init"), "init")
        elif found.returncode != 0:
            self._check(found, "opening the repository")

    def back_up(self, folder: Path) -> str:
        """Backs up the files in folder and returns the new snapshot's id."""
        output = self._check(self._restic("backup", "--json", "--host", HOST, "--tag", "nightly", str(folder)), "backup")
        for line in output.splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("message_type") == "summary" and message.get("snapshot_id"):
                return str(message["snapshot_id"])
        raise BackupError("restic backup did not report a snapshot")

    def thin_out(self) -> None:
        arguments = ["forget", "--host", HOST, "--prune"]
        for flag, value in KEEP.items():
            arguments += [flag, value]
        self._check(self._restic(*arguments), "forget")

    def restore_latest(self, target: Path) -> None:
        self._check(self._restic("restore", "latest", "--host", HOST, "--target", str(target)), "restore")

    def check_data(self) -> None:
        """Reads back all of the repository's data. With one small database this takes seconds."""
        self._check(self._restic("check", "--read-data"), "check")


def copy_database(source: Path, target: Path) -> None:
    """A consistent copy with SQLite's backup function, then checked."""
    if not source.is_file():
        raise BackupError(f"There is no database at {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    # Opened for writing, because a database in WAL mode needs its shared-memory file, also to be read.
    with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(target)) as copy:
        live.backup(copy)
    check_database(target)


def keep_current(live: Path, kept: Path) -> None:
    """Keeps the database that is being replaced, with the changes still in its write-ahead log. A database that is too
    damaged to copy is kept as it is: the main file and its log files, under the new name."""
    try:
        with closing(sqlite3.connect(live)) as current, closing(sqlite3.connect(kept)) as copy:
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
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
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


def database_in_use(path: Path) -> bool:
    """True when another program has the database open. Changing the journal mode succeeds only for the one
    connection to a database, so it is tried, and the mode is put back."""
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path, timeout=1, isolation_level=None)) as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            changed = connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            if changed != "delete":
                return True
            connection.execute(f"PRAGMA journal_mode = {mode}")
    except sqlite3.OperationalError:
        return True
    return False


def health_check(url: str) -> Callable[[], bool]:
    def answers() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a fixed address inside the bundle
                return bool(response.status == 200)
        except OSError:
            return False

    return answers


# --- reports to health monitoring (story E01-010)

# The status files whose results are reported, with the key of their external endpoint in Gatus, the result that
# counts as a success, the field with the time of the last success and a name for messages. A restore by the owner
# (restore.json) is not reported.
MONITORED = {
    "backup.json": ("nightly_backup", "backed-up", "lastSucceededAt", "backup"),
    "restore-test.json": ("nightly_restore-test", "restore-test-passed", "lastPassedAt", "restore test"),
}
# How old the last success may be before the state is a failure: a day and two hours for the nightly backup, and two
# days more than the month between restore tests.
STALE_AFTER = {"backup.json": timedelta(hours=26), "restore-test.json": RESTORE_TEST_EVERY + timedelta(days=2)}
# The status file of the wait for the first database on a new installation, and how long the wait may last.
WAITING = "backup-waiting.json"
WAIT_FOR_DATABASE = timedelta(hours=24)


def _post(request: urllib.request.Request) -> None:
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310 - a fixed address inside the bundle
        pass


@dataclass(slots=True)
class Monitor:
    """Reports the result of each run to an external endpoint in Gatus (the status container). An alert is sent when a
    run fails or no report arrives within its heartbeat interval. This is a copy of the updater's Monitor, because the
    two images share no code."""

    url: str
    token_file: Path
    send: Callable[[urllib.request.Request], object] = field(default=_post)

    def report(self, key: str, success: bool, message: str) -> None:
        """Sends one result. Nothing is sent while there is no push token, which means monitoring is switched off. A
        report that cannot be sent is printed instead, and the run's result is not changed."""
        try:
            token = self.token_file.read_text(encoding="utf-8").strip() if self.token_file.is_file() else ""
            if not token:
                return
            fields = {"success": "true"} if success else {"success": "false", "error": message[:500]}
            request = urllib.request.Request(  # noqa: S310 - a fixed address inside the bundle
                f"{self.url.rstrip('/')}/api/v1/endpoints/{key}/external?{urllib.parse.urlencode(fields)}",
                method="POST",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.send(request)
        except Exception as error:  # noqa: BLE001 - the backup goes on when a report cannot be sent
            print(json.dumps({"result": "report-not-sent", "message": str(error)}), flush=True)


@dataclass(slots=True)
class Backup:
    data: Path  # the app's data volume
    work: Path  # a folder for the copy and for restore tests, outside the data volume
    status: StatusFiles
    restic: Restic
    app_answers: Callable[[], bool] = field(default=lambda: False)
    backups: Path = Path("/backups")
    monitor: Monitor | None = None

    def back_up(self, now: datetime) -> str:
        staging = self.work / "staging"
        last_success = self.status.read("backup.json").get("lastSucceededAt", "")
        try:
            if not (self.backups / DISK_MARKER).is_file():
                raise BackupError(
                    f"The backup disk is not there: {self.backups} has no {DISK_MARKER} file. Check that disk J: is connected."
                )
            if not last_success and not (self.data / DATABASE).exists():
                return self._wait_for_database(now)
            copy_database(self.data / DATABASE, staging / DATABASE)
            self.restic.ensure_repository()
            snapshot = self.restic.back_up(staging)
            self.restic.thin_out()
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            return self._report("backup.json", "backup-failed", now, lastSucceededAt=last_success, message=str(error))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
        stamp = now.astimezone(UTC).isoformat(timespec="seconds")
        return self._report("backup.json", "backed-up", now, snapshot=snapshot, lastSucceededAt=stamp, message="The database was backed up")

    def _wait_for_database(self, now: datetime) -> str:
        """On a new installation, the backup container can start before there is a database. Until a backup has
        succeeded, a missing database is taken to mean "not yet", and the next try is ten minutes later. After a day
        it is a failure, because the data volume is then probably not the app's."""
        since = self.status.read(WAITING).get("waitingSince", "")
        try:
            started = datetime.fromisoformat(since)
        except ValueError:
            return self._report(WAITING, "waiting-for-database", now, key="waitingSince", message="There is no database yet")
        if now - started > WAIT_FOR_DATABASE:
            raise BackupError(f"There is still no database at {self.data / DATABASE} a day after installation. Check the data volume.")
        print(json.dumps({"result": "waiting-for-database", "message": "There is no database yet"}), flush=True)
        return "waiting-for-database"

    def backup_due(self, now: datetime, at: str) -> bool:
        """Due when there has been no backup since the last daily time, so a night when the PC was off is made up
        when it is on again."""
        last = self.status.read("backup.json").get("lastSucceededAt")
        if not last:
            return True
        try:
            last_time = datetime.fromisoformat(last)
        except ValueError:
            return True
        return last_time < next_run(now, at) - timedelta(days=1)

    def healthy(self, now: datetime) -> bool:
        """For the container's health check: healthy until the first backup is tried, then while the last successful
        backup is less than two days old."""
        status = self.status.read("backup.json")
        if not status:
            return True
        try:
            return now - datetime.fromisoformat(status.get("lastSucceededAt", "")) < HEALTHY_FOR
        except ValueError:
            return False

    def restore_test_due(self, now: datetime) -> bool:
        """Due a month after the last test that passed; after a failed test, the next night."""
        last = self.status.read("restore-test.json").get("lastPassedAt")
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
            self.restic.check_data()
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            last_passed = self.status.read("restore-test.json").get("lastPassedAt", "")
            return self._report(
                "restore-test.json", "restore-test-failed", now, key="testedAt", lastPassedAt=last_passed, message=str(error)
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        stamp = now.astimezone(UTC).isoformat(timespec="seconds")
        return self._report(
            "restore-test.json",
            "restore-test-passed",
            now,
            key="testedAt",
            lastPassedAt=stamp,
            schema=schema,
            message="The latest backup was restored and checked",
        )

    def restore_latest(self, now: datetime) -> str:
        """Puts the latest backup in place of the live database. The app has to be stopped first."""
        live = self.data / DATABASE
        if self.app_answers() or database_in_use(live):
            return self._report(
                "restore.json", "refused", now, message="The app is running or has the database open. Stop it first, then restore."
            )
        incoming_folder = self.work / "restore"
        shutil.rmtree(incoming_folder, ignore_errors=True)
        incoming = live.with_name(DATABASE + ".restore")
        try:
            self.restic.restore_latest(incoming_folder)
            restored = next(incoming_folder.rglob(DATABASE), None)
            if restored is None:
                raise BackupError("The latest backup has no database in it")
            check_database(restored)
            shutil.copyfile(restored, incoming)
            with open(incoming, "rb") as copied:
                os.fsync(copied.fileno())
            if live.exists():
                keep_current(live, self.data / f"franca-before-restore-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}.db")
            # The old log files go first: SQLite would otherwise apply them to the restored database.
            for extra in (live.with_name(DATABASE + "-wal"), live.with_name(DATABASE + "-shm")):
                extra.unlink(missing_ok=True)
            os.replace(incoming, live)
            folder = os.open(self.data, os.O_RDONLY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
        except (BackupError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
            incoming.unlink(missing_ok=True)
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

    def report_state(self, now: datetime) -> None:
        """Reports the state of the backup and of the restore test to health monitoring. A state is good while the last
        run succeeded and the last success is recent enough (STALE_AFTER). The state is reported after each run and every
        hour. Gatus forgets the time of the last report when the status container restarts, so without these reports a
        missed run would not be noticed."""
        if self.monitor is None:
            return
        for name, (key, success, stamp, what) in MONITORED.items():
            state = self.status.read(name)
            if not state:
                self.monitor.report(key, True, f"No {what} has run yet")
                continue
            if state.get("result") != success:
                self.monitor.report(key, False, state.get("message", f"The last {what} failed"))
                continue
            last = state.get(stamp, "")
            try:
                stale = now - datetime.fromisoformat(last) > STALE_AFTER[name]
            except ValueError:
                stale = True
            self.monitor.report(key, not stale, f"No successful {what} since {last or 'the start'}" if stale else state.get("message", ""))


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
        backups=Path(environ.get("FRANCA_BACKUP_DIR_IN_CONTAINER", "/backups")),
        monitor=Monitor(environ["FRANCA_STATUS_URL"], Path("/run/secrets/status_push_token")) if environ.get("FRANCA_STATUS_URL") else None,
    )


def main(argv: Sequence[str] = sys.argv[1:]) -> int:
    backup = from_environment(os.environ)
    command = argv[0] if argv else "serve"
    now = datetime.now(UTC)
    if command == "backup":
        result = backup.back_up(now)
        backup.report_state(now)
        return 0 if result == "backed-up" else 1
    if command == "restore-test":
        result = backup.restore_test(now)
        backup.report_state(now)
        return 0 if result == "restore-test-passed" else 1
    if command == "restore-latest":
        return 0 if backup.restore_latest(now) == "restored" else 1
    if command == "health":
        return 0 if backup.healthy(now) else 1
    if command != "serve":
        print("Use: franca_backup.py [serve | backup | restore-test | restore-latest | health]", file=sys.stderr)
        return 2
    at = backup_time(os.environ.get("FRANCA_BACKUP_AT_UTC", DEFAULT_BACKUP_TIME))
    # The service looks every ten minutes whether a backup is due, so a night when the PC was off or asleep is made
    # up when it is on again. After a failed backup, the next try is an hour later.
    # The state is reported to health monitoring after each run and every hour (see Backup.report_state).
    retry_after = datetime.min.replace(tzinfo=UTC)
    report_after = datetime.min.replace(tzinfo=UTC)
    while True:
        try:
            now = datetime.now(UTC)
            ran = False
            if now >= retry_after and backup.backup_due(now, at):
                ran = True
                if backup.back_up(now) == "backed-up":
                    if backup.restore_test_due(now):
                        backup.restore_test(now)
                else:
                    retry_after = now + timedelta(hours=1)
            if ran or now >= report_after:
                backup.report_state(now)
                report_after = now + timedelta(hours=1)
        except Exception as error:  # noqa: BLE001 - the service keeps running and tries again
            print(json.dumps({"result": "error", "message": repr(error)}), flush=True)
        time.sleep(600)


if __name__ == "__main__":
    sys.exit(main())
