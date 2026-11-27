"""Tests for the nightly backup and the monthly restore test (story E01-008), with a stand-in for restic and real
SQLite databases. The rehearsal with real containers is infra/tests/rehearse_backup.py."""

import json
import sqlite3
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import franca_backup as fb  # noqa: E402

NOW = datetime(2026, 12, 7, 3, 30, tzinfo=UTC)


def make_database(path: Path, rows: int = 1) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0002')")
        connection.execute("CREATE TABLE notes (text TEXT)")
        connection.executemany("INSERT INTO notes VALUES (?)", [(f"note {n}",) for n in range(rows)])


def count_notes(path: Path) -> int:
    """The number of rows in the notes table of a database file. The connection is closed afterwards."""
    with closing(sqlite3.connect(path)) as connection:
        found: int = connection.execute("SELECT count(*) FROM notes").fetchone()[0]
        return found


class FakeRestic:
    """Answers restic commands. A restore copies what the last backup saw."""

    def __init__(self, tmp_path: Path, fail_on: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on
        self.store = tmp_path / "fake-store"
        self.repository_exists = False
        self.missing_code = 10
        self.summary = True

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append(command)
        verb = command[1]
        if verb == self.fail_on:
            return subprocess.CompletedProcess(command, 1, "", f"Fatal: {verb} failed\n")
        if verb == "cat" and not self.repository_exists:
            return subprocess.CompletedProcess(command, self.missing_code, "", "Fatal: repository does not exist\n")
        if verb == "init":
            self.repository_exists = True
        if verb == "backup":
            source = Path(command[-1])
            self.store.mkdir(exist_ok=True)
            for file in source.iterdir():
                (self.store / file.name).write_bytes(file.read_bytes())
            summary = json.dumps({"message_type": "summary", "snapshot_id": "abc123"}) if self.summary else ""
            return subprocess.CompletedProcess(command, 0, summary + "\n", "")
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
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / fb.DISK_MARKER).write_text("Franca backups\n", encoding="utf-8")
    backup = fb.Backup(
        data=tmp_path / "data",
        work=tmp_path / "cache",
        status=fb.StatusFiles(tmp_path / "status"),
        restic=fb.Restic(run=restic),
        app_answers=lambda: healthy,
        backups=tmp_path / "backups",
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
    assert count_notes(restic.store / "franca.db") == 1
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

    assert count_notes(restic.store / "franca.db") == 2
    live.close()


def test_a_failed_restic_backup_is_reported(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path, fail_on="backup")
    assert backup.back_up(NOW) == "backup-failed"
    assert "backup failed" in status(tmp_path, "backup.json")["message"]


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
    ("last_passed", "now", "due"),
    [
        (None, NOW, True),
        ("2026-11-30T03:30:00+00:00", NOW, False),
        ("2026-11-01T03:30:00+00:00", NOW, True),
        ("2026-11-06T03:30:00+00:00", NOW, True),
        ("2026-11-07T03:31:00+00:00", NOW, False),
    ],
)
def test_the_restore_test_is_due_once_a_month(tmp_path: Path, last_passed: str | None, now: datetime, due: bool) -> None:
    backup, _restic = make(tmp_path)
    if last_passed:
        backup.status.write("restore-test.json", result="restore-test-passed", testedAt=last_passed, lastPassedAt=last_passed)
    assert backup.restore_test_due(now) is due


def test_after_a_failed_restore_test_it_is_tried_again_the_next_night(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    backup.restore_test(NOW)
    (restic.store / "franca.db").write_bytes(b"not a database")
    later = NOW.replace(year=2027, month=1, day=8)
    assert backup.restore_test(later) == "restore-test-failed"
    assert backup.restore_test_due(later.replace(day=9)) is True


# --- restoring for real


def test_restoring_the_latest_backup_puts_it_in_place_and_keeps_the_current_database(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    with closing(sqlite3.connect(tmp_path / "data" / "franca.db")) as live, live:
        live.execute("DELETE FROM notes")

    assert backup.restore_latest(NOW) == "restored"

    assert count_notes(tmp_path / "data" / "franca.db") == 1
    kept = list((tmp_path / "data").glob("franca-before-restore-*.db"))
    assert len(kept) == 1
    assert count_notes(kept[0]) == 0


def test_restoring_is_refused_while_the_app_is_running(tmp_path: Path) -> None:
    backup, restic = make(tmp_path, healthy=True)
    backup.back_up(NOW)
    assert backup.restore_latest(NOW) == "refused"
    assert "restore" not in verbs(restic)


def test_a_damaged_backup_is_not_put_in_place(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    (restic.store / "franca.db").write_bytes(b"not a database")

    assert backup.restore_latest(NOW) == "restore-failed"
    with closing(sqlite3.connect(tmp_path / "data" / "franca.db")) as live:
        assert live.execute("SELECT text FROM notes").fetchall() == [("note 0",)]
        assert live.execute("PRAGMA journal_mode").fetchone() == ("wal",)


# --- the schedule


def test_the_next_run_is_at_the_time_of_day_given() -> None:
    assert fb.next_run(datetime(2026, 12, 7, 3, 0, tzinfo=UTC), "03:30") == datetime(2026, 12, 7, 3, 30, tzinfo=UTC)
    assert fb.next_run(datetime(2026, 12, 7, 3, 30, tzinfo=UTC), "03:30") == datetime(2026, 12, 8, 3, 30, tzinfo=UTC)


# --- after the security review


def test_without_the_marker_file_the_backup_disk_counts_as_missing(tmp_path: Path) -> None:
    # On a PC or server where disk J: is not there, the folder can be empty: no repository is made in it.
    backup, restic = make(tmp_path)
    (tmp_path / "backups" / fb.DISK_MARKER).unlink()

    assert backup.back_up(NOW) == "backup-failed"

    assert "init" not in verbs(restic)
    assert "backup disk" in status(tmp_path, "backup.json")["message"]


def test_a_repository_that_cannot_be_opened_is_not_replaced_by_a_new_one(tmp_path: Path) -> None:
    # For example a wrong password: restic exits with 12, not 10.
    backup, restic = make(tmp_path)
    restic.missing_code = 12

    assert backup.back_up(NOW) == "backup-failed"
    assert "init" not in verbs(restic)


def test_a_backup_without_a_snapshot_id_is_a_failure(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    restic.summary = False
    assert backup.back_up(NOW) == "backup-failed"


def test_the_last_successful_backup_is_kept_after_a_failure(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path, fail_on=None)
    backup.back_up(NOW)
    backup.restic = fb.Restic(run=FakeRestic(tmp_path, fail_on="backup"))
    backup.back_up(NOW.replace(day=8))
    assert status(tmp_path, "backup.json")["lastSucceededAt"] == "2026-12-07T03:30:00+00:00"


@pytest.mark.parametrize(
    ("last", "now", "due"),
    [
        (None, datetime(2026, 12, 7, 10, 0, tzinfo=UTC), True),  # never backed up: at once
        ("2026-12-07T03:30:00+00:00", datetime(2026, 12, 7, 10, 0, tzinfo=UTC), False),
        ("2026-12-06T03:30:00+00:00", datetime(2026, 12, 7, 3, 0, tzinfo=UTC), False),  # not yet 03:30
        ("2026-12-06T03:30:00+00:00", datetime(2026, 12, 7, 3, 31, tzinfo=UTC), True),
        ("2026-12-04T03:30:00+00:00", datetime(2026, 12, 7, 1, 0, tzinfo=UTC), True),  # the PC was off: catch up
    ],
)
def test_a_missed_backup_is_made_up_when_the_pc_is_on_again(tmp_path: Path, last: str | None, now: datetime, due: bool) -> None:
    backup, _restic = make(tmp_path)
    if last:
        backup.status.write("backup.json", result="backed-up", at=last, lastSucceededAt=last)
    assert backup.backup_due(now, "03:30") is due


def test_restoring_is_refused_while_another_program_has_the_database_open(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    holder = sqlite3.connect(tmp_path / "data" / "franca.db")
    holder.execute("BEGIN")
    holder.execute("SELECT count(*) FROM notes").fetchone()

    assert backup.restore_latest(NOW) == "refused"

    holder.rollback()
    holder.close()
    assert "restore" not in verbs(restic)


def test_a_restore_that_fails_leaves_no_half_copied_file(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    restic.store.joinpath("franca.db").write_bytes(b"not a database")
    backup.restore_latest(NOW)
    assert not (tmp_path / "data" / "franca.db.restore").exists()


def test_the_monthly_check_reads_all_of_the_repositorys_data(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    backup.restore_test(NOW)
    assert restic.commands[-1] == ["restic", "check", "--read-data"]


def test_the_health_check_follows_the_last_successful_backup(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    assert backup.healthy(NOW) is True  # no backup tried yet
    backup.back_up(NOW)
    assert backup.healthy(NOW.replace(day=8)) is True
    assert backup.healthy(NOW.replace(day=10)) is False


# --- reports to health monitoring (story E01-010)


class FakeMonitor(fb.Monitor):
    def __init__(self) -> None:
        self.reports: list[tuple[str, bool, str]] = []

    def report(self, key: str, success: bool, message: str) -> None:
        self.reports.append((key, success, message))


def states(monitor: FakeMonitor) -> list[tuple[str, bool]]:
    return [(key, success) for key, success, _message in monitor.reports]


def test_before_the_first_backup_both_states_are_good(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    monitor = FakeMonitor()
    backup.monitor = monitor

    backup.report_state(NOW)

    assert states(monitor) == [("nightly_backup", True), ("nightly_restore-test", True)]


def test_a_failed_backup_is_reported_until_one_succeeds(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    monitor = FakeMonitor()
    backup.monitor = monitor
    restic.fail_on = "backup"
    backup.back_up(NOW)
    backup.report_state(NOW)
    restic.fail_on = None
    backup.back_up(NOW + timedelta(hours=1))
    backup.report_state(NOW + timedelta(hours=1))

    assert states(monitor)[0::2] == [("nightly_backup", False), ("nightly_backup", True)]
    assert "backup failed" in monitor.reports[0][2]


def test_no_successful_backup_for_26_hours_is_a_failure(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    monitor = FakeMonitor()
    backup.monitor = monitor
    backup.back_up(NOW)

    backup.report_state(NOW + timedelta(hours=27))

    key, success, message = monitor.reports[0]
    assert (key, success) == ("nightly_backup", False)
    assert "2026-12-07" in message


def test_a_restore_test_older_than_32_days_is_a_failure(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    backup.restore_test(NOW)
    monitor = FakeMonitor()
    backup.monitor = monitor
    later = NOW + timedelta(days=33)
    backup.back_up(later)

    backup.report_state(later)

    assert states(monitor) == [("nightly_backup", True), ("nightly_restore-test", False)]


def test_a_failed_restore_test_is_a_failure(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    backup.back_up(NOW)
    restic.fail_on = "restore"
    backup.restore_test(NOW)
    monitor = FakeMonitor()
    backup.monitor = monitor

    backup.report_state(NOW)

    assert states(monitor) == [("nightly_backup", True), ("nightly_restore-test", False)]


def test_a_report_is_a_post_with_the_token(tmp_path: Path) -> None:
    token = tmp_path / "status_push_token"
    token.write_text("t" * 40, encoding="utf-8")
    sent: list[urllib.request.Request] = []

    fb.Monitor("http://status:8080", token, send=sent.append).report("nightly_backup", True, "The database was backed up")

    assert sent[0].get_method() == "POST"
    assert sent[0].full_url == "http://status:8080/api/v1/endpoints/nightly_backup/external?success=true"
    assert sent[0].get_header("Authorization") == "Bearer " + "t" * 40


# --- a new installation


def test_before_the_app_has_made_its_database_the_first_backup_waits(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()

    result = backup.back_up(NOW)

    assert result == "waiting-for-database"
    assert restic.commands == []
    assert not (tmp_path / "status" / "backup.json").exists()
    assert backup.healthy(NOW)


def test_the_wait_for_the_database_keeps_the_time_it_started(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()

    backup.back_up(NOW)
    backup.back_up(NOW + timedelta(hours=3))

    assert backup.status.read("backup-waiting.json")["waitingSince"] == NOW.astimezone(UTC).isoformat(timespec="seconds")


def test_no_database_a_day_after_installation_is_a_failure(tmp_path: Path) -> None:
    backup, restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    backup.back_up(NOW)

    result = backup.back_up(NOW + timedelta(hours=25))

    assert result == "backup-failed"
    assert "data volume" in backup.status.read("backup.json")["message"]
    assert restic.commands == []
    assert not backup.healthy(NOW + timedelta(hours=25))


def test_the_wait_lasts_a_day(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    backup.back_up(NOW)

    assert backup.back_up(NOW + timedelta(hours=23)) == "waiting-for-database"
    assert backup.healthy(NOW + timedelta(hours=23))
    assert backup.back_up(NOW + timedelta(hours=24, minutes=1)) == "backup-failed"


def test_the_wait_ends_when_the_database_is_there(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    backup.back_up(NOW)
    make_database(tmp_path / "data" / "franca.db")

    assert backup.back_up(NOW + timedelta(hours=1)) == "backed-up"


def test_a_wait_start_without_a_time_zone_starts_the_wait_again(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    backup.status.write("backup-waiting.json", waitingSince="2026-12-01T00:00:00")

    assert backup.back_up(NOW) == "waiting-for-database"
    assert backup.status.read("backup-waiting.json")["waitingSince"] == NOW.astimezone(UTC).isoformat(timespec="seconds")


def test_a_missing_backup_disk_is_a_failure_while_waiting_for_the_database(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    (tmp_path / "data" / "franca.db").unlink()
    (backup.backups / fb.DISK_MARKER).unlink()

    assert backup.back_up(NOW) == "backup-failed"


def test_a_database_that_goes_missing_after_a_backup_is_a_failure(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.back_up(NOW)
    (tmp_path / "data" / "franca.db").unlink()

    assert backup.back_up(NOW) == "backup-failed"


@pytest.mark.parametrize("text", ["[]", '"backed-up"', "null", "{not json"])
def test_a_status_file_that_is_not_a_json_object_counts_as_no_status(tmp_path: Path, text: str) -> None:
    status = fb.StatusFiles(tmp_path)
    (tmp_path / "backup.json").write_text(text, encoding="utf-8")

    assert status.read("backup.json") == {}


def test_the_health_check_reads_a_damaged_status_file_as_no_backup_yet(tmp_path: Path) -> None:
    backup, _restic = make(tmp_path)
    backup.status.folder.mkdir(parents=True, exist_ok=True)
    (backup.status.folder / "backup.json").write_text('"backed-up"', encoding="utf-8")

    assert backup.healthy(NOW)
