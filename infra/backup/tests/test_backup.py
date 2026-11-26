"""Tests for the nightly backup and the monthly restore test (story E01-008), with a stand-in for restic and real
SQLite databases. The rehearsal with real containers is infra/tests/rehearse_backup.py."""

import json
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import franca_backup as fb  # noqa: E402

NOW = datetime(2026, 12, 7, 3, 30, tzinfo=UTC)


def make_database(path: Path, rows: int = 1) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0002')")
        connection.execute("CREATE TABLE notes (text TEXT)")
        connection.executemany("INSERT INTO notes VALUES (?)", [(f"note {n}",) for n in range(rows)])


class FakeRestic:
    """Answers restic commands. A restore copies what the last backup saw."""

    def __init__(self, tmp_path: Path, fail_on: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on
        self.store = tmp_path / "fake-store"
        self.repository_exists = False

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append(command)
        verb = command[1]
        if verb == self.fail_on:
            return subprocess.CompletedProcess(command, 1, "", f"Fatal: {verb} failed\n")
        if verb == "cat" and not self.repository_exists:
            return subprocess.CompletedProcess(command, 10, "", "Fatal: repository does not exist\n")
        if verb == "init":
            self.repository_exists = True
        if verb == "backup":
            source = Path(command[-1])
            self.store.mkdir(exist_ok=True)
            for file in source.iterdir():
                (self.store / file.name).write_bytes(file.read_bytes())
            return subprocess.CompletedProcess(command, 0, json.dumps({"message_type": "summary", "snapshot_id": "abc123"}) + "\n", "")
        if verb == "restore":
            target = Path(command[command.index("--target") + 1])
            restored = target / "staging"
            restored.mkdir(parents=True, exist_ok=True)
            for file in self.store.iterdir():
                (restored / file.name).write_bytes(file.read_bytes())
        return subprocess.CompletedProcess(command, 0, "", "")


def make(tmp_path: Path, fail_on: str | None = None, healthy: bool = False) -> tuple[fb.Backup, FakeRestic]:
    (tmp_path / "data").mkdir()
    make_database(tmp_path / "data" / "franca.db")
    restic = FakeRestic(tmp_path, fail_on)
    backup = fb.Backup(
        data=tmp_path / "data",
        work=tmp_path / "cache",
        status=fb.StatusFiles(tmp_path / "status"),
        restic=fb.Restic(run=restic),
        app_answers=lambda: healthy,
    )
    return backup, restic


def status(tmp_path: Path, name: str) -> dict[str, str]:
    result: dict[str, str] = json.loads((tmp_path / "status" / name).read_text(encoding="utf-8"))
    return result


def verbs(restic: FakeRestic) -> list[str]:
    return [command[1] for command in restic.commands]


# --- the nightly backup


def test_the_first_backup_makes_the_repository_then_backs_up_a_checked_copy(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)

    assert backup.back_up(NOW) == "backed-up"

    assert verbs(restic) == ["cat", "init", "backup", "forget"]
    assert sqlite3.connect(restic.store / "franca.db").execute("SELECT count(*) FROM notes").fetchone() == (1,)
    assert status(tmp_path, "backup.json")["result"] == "backed-up"
    assert status(tmp_path, "backup.json")["snapshot"] == "abc123"


def test_a_later_backup_uses_the_existing_repository(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    restic.repository_exists = True
    backup.back_up(NOW)
    assert verbs(restic) == ["cat", "backup", "forget"]


def test_old_backups_are_thinned_out(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    forget = restic.commands[-1]
    for flag, value in (("--keep-daily", "14"), ("--keep-weekly", "8"), ("--keep-monthly", "12")):
        assert forget[forget.index(flag) + 1] == value
    assert "--prune" in forget


def test_the_copy_is_taken_with_sqlites_backup_so_recent_changes_in_the_wal_are_included(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    live = sqlite3.connect(tmp_path / "data" / "franca.db")
    live.execute("INSERT INTO notes VALUES ('only in the WAL')")
    live.commit()  # the connection stays open, so the change has not been written back to the main file yet

    backup.back_up(NOW)

    copied = sqlite3.connect(restic.store / "franca.db").execute("SELECT count(*) FROM notes").fetchone()
    assert copied == (2,)
    live.close()


def test_a_failed_restic_backup_is_reported(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path, fail_on="backup")
    assert backup.back_up(NOW) == "backup-failed"
    assert "backup failed" in status(tmp_path, "backup.json")["message"]


def test_a_missing_database_is_reported(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    assert backup.back_up(NOW) == "backup-failed"


def test_the_staging_copy_is_removed_afterwards(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    assert not any((tmp_path / "cache" / "staging").glob("*"))


# --- the restore test


def test_the_restore_test_restores_the_latest_backup_and_checks_it(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)

    assert backup.restore_test(NOW) == "restore-test-passed"

    assert verbs(restic)[-2:] == ["restore", "check"]
    report = status(tmp_path, "restore-test.json")
    assert report["result"] == "restore-test-passed"
    assert report["schema"] == "0002"
    assert not (tmp_path / "cache" / "restore-test").exists()


def test_a_damaged_backup_fails_the_restore_test(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    (restic.store / "franca.db").write_bytes(b"not a database")

    assert backup.restore_test(NOW) == "restore-test-failed"
    assert "not a database" in status(tmp_path, "restore-test.json")["message"] or status(tmp_path, "restore-test.json")["message"]


def test_the_restore_test_does_not_touch_the_live_database(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    before = (tmp_path / "data" / "franca.db").read_bytes()
    backup.restore_test(NOW)
    assert (tmp_path / "data" / "franca.db").read_bytes() == before


@pytest.mark.parametrize(
    ("last", "now", "due"),
    [
        (None, NOW, True),
        ("2026-11-30T03:30:00+00:00", NOW, False),
        ("2026-11-01T03:30:00+00:00", NOW, True),
        ("2026-11-06T03:30:00+00:00", NOW, True),
        ("2026-11-07T03:31:00+00:00", NOW, False),
    ],
)
def test_the_restore_test_is_due_once_a_month(tmp_path: Path, last: str | None, now: datetime, due: bool) -> None:
    backup, _restic = make(tmp_path)
    if last:
        backup.status.write("restore-test.json", result="restore-test-passed", testedAt=last)
    assert backup.restore_test_due(now) is due


# --- restoring for real


def test_restoring_the_latest_backup_puts_it_in_place_and_keeps_the_current_database(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    with sqlite3.connect(tmp_path / "data" / "franca.db") as live:
        live.execute("DELETE FROM notes")

    assert backup.restore_latest(NOW) == "restored"

    restored = sqlite3.connect(tmp_path / "data" / "franca.db").execute("SELECT count(*) FROM notes").fetchone()
    assert restored == (1,)
    kept = list((tmp_path / "data").glob("franca-before-restore-*.db"))
    assert len(kept) == 1
    assert sqlite3.connect(kept[0]).execute("SELECT count(*) FROM notes").fetchone() == (0,)


def test_restoring_is_refused_while_the_app_is_running(tmp_path: Path) -> None:
    backup, restic = make(tmp_path, healthy=True)
    backup.back_up(NOW)
    assert backup.restore_latest(NOW) == "refused"
    assert "restore" not in verbs(restic)


def test_a_damaged_backup_is_not_put_in_place(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    (restic.store / "franca.db").write_bytes(b"not a database")
    before = (tmp_path / "data" / "franca.db").read_bytes()

    assert backup.restore_latest(NOW) == "restore-failed"
    assert (tmp_path / "data" / "franca.db").read_bytes() == before


# --- the schedule


def test_the_next_run_is_at_the_time_of_day_given() -> None:
    assert fb.next_run(datetime(2026, 12, 7, 3, 0, tzinfo=UTC), "03:30") == datetime(2026, 12, 7, 3, 30, tzinfo=UTC)
    assert fb.next_run(datetime(2026, 12, 7, 3, 30, tzinfo=UTC), "03:30") == datetime(2026, 12, 8, 3, 30, tzinfo=UTC)
