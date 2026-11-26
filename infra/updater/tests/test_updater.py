"""Tests for the updater (story E01-007), with stand-ins for GitHub, cosign, docker compose and the health check.

The rehearsal against real containers is infra/tests/rehearse-update.sh.
"""

import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import franca_updater as fu  # noqa: E402

NOW = datetime(2026, 12, 7, 2, 30, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
APP = f"ghcr.io/franca-language-learning/franca-app@{DIGEST}"
CADDY = f"ghcr.io/franca-language-learning/franca-caddy@sha256:{'b' * 64}"
OLD_APP = f"ghcr.io/franca-language-learning/franca-app@sha256:{'c' * 64}"


class FakeReleases(fu.GitHubReleases):
    def __init__(self, release: fu.Release | Exception) -> None:
        self.release = release

    def latest(self) -> fu.Release:
        if isinstance(self.release, Exception):
            raise self.release
        return self.release


class FakeVerifier:
    def __init__(self, refuse: str | None = None) -> None:
        self.refuse = refuse
        self.checked: list[tuple[str, str]] = []

    def verify(self, image: str, version: fu.Version) -> None:
        self.checked.append((image, version.tag))
        if image == self.refuse:
            raise fu.UpdateError(f"The signature check of {image} failed: no matching signatures")


class FakeCompose(fu.Compose):
    """Records the steps, and fails the step named in fail_on."""

    def __init__(self, log: list[str], fail_on: set[str] | None = None) -> None:
        self.log = log
        self.fail_on = fail_on or set()

    def _step(self, name: str) -> None:
        self.log.append(name)
        if name in self.fail_on:
            self.fail_on.discard(name)
            raise fu.UpdateError(f"{name} failed")

    def pull(self, image: str) -> None:
        self._step(f"pull {image.split('/')[-1][:12]}")

    def stop(self, *services: str) -> None:
        self._step("stop " + " ".join(services))

    def up(self, *services: str) -> None:
        self._step("up " + " ".join(services))


class FakeDatabase(fu.Database):
    def __init__(self, log: list[str], fail: bool = False) -> None:
        self.log = log
        self.fail = fail

    def snapshot(self, label: str) -> str:
        self.log.append(f"snapshot {label}")
        if self.fail:
            raise fu.UpdateError("The database step failed: disk full")
        return f"/data/snapshots/franca-{label}.db"

    def restore(self, snapshot: str) -> None:
        self.log.append(f"restore {snapshot}")


def make(
    tmp_path: Path,
    release: fu.Release | Exception,
    *,
    healthy: Sequence[str | None] = ("1.1.0",),
    refuse: str | None = None,
    fail_on: set[str] | None = None,
    snapshot_fails: bool = False,
) -> tuple[fu.Updater, list[str], FakeVerifier]:
    env = tmp_path / ".env"
    env.write_text(f"# Franca\nFRANCA_VERSION=1.0.0\nFRANCA_APP_IMAGE={OLD_APP}\nFRANCA_PORT=8080\n", encoding="utf-8")
    log: list[str] = []
    answers = list(healthy)
    compose = FakeCompose(log, fail_on)

    def probe() -> str | None:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    verifier = FakeVerifier(refuse)
    updater = fu.Updater(
        releases=FakeReleases(release),
        verifier=verifier,
        env=fu.EnvFile(env),
        compose=compose,
        database=FakeDatabase(log, snapshot_fails),
        probe=probe,
        status=fu.StatusFile(tmp_path / "status" / "updater.json"),
        health_timeout=0,
        sleep=lambda _seconds: None,
    )
    return updater, log, verifier


def status(tmp_path: Path) -> dict[str, str]:
    result: dict[str, str] = json.loads((tmp_path / "status" / "updater.json").read_text(encoding="utf-8"))
    return result


NEW = fu.Release(fu.Version(1, 1, 0), {"app": APP, "caddy": CADDY})


# --- versions and releases


def test_versions_compare_as_numbers() -> None:
    assert fu.Version.parse("v1.10.0") > fu.Version.parse("1.9.9")
    assert fu.Version.parse("v2.0.0").tag == "v2.0.0"
    with pytest.raises(fu.UpdateError):
        fu.Version.parse("1.0.0-dev")


def test_the_image_list_names_the_images_by_digest() -> None:
    assert fu.parse_images([APP, "", CADDY]) == {"app": APP, "caddy": CADDY}
    updater = f"ghcr.io/franca-language-learning/franca-updater@{DIGEST}"
    assert fu.parse_images([APP, CADDY, updater])["updater"] == updater
    tailscale = f"ghcr.io/franca-language-learning/franca-tailscale@{DIGEST}"
    assert fu.parse_images([APP, CADDY, tailscale])["tailscale"] == tailscale


@pytest.mark.parametrize(
    "lines",
    [
        [APP],  # no caddy image
        [APP, "ghcr.io/franca-language-learning/franca-caddy:latest"],  # a tag, not a digest
        [APP, f"ghcr.io/someone-else/franca-caddy@{DIGEST}"],  # another registry account
        [APP, CADDY, f"docker.io/library/alpine@{DIGEST}"],
    ],
)
def test_an_unexpected_image_list_is_refused(lines: list[str]) -> None:
    with pytest.raises(fu.UpdateError):
        fu.parse_images(lines)


def test_the_latest_release_is_read_from_github() -> None:
    base = "https://github.com/Franca-Language-Learning/Franca/releases/download/v1.1.0"
    pages = {
        "https://api.github.com/repos/Franca-Language-Learning/Franca/releases/latest": json.dumps(
            {
                "tag_name": "v1.1.0",
                "assets": [
                    {"name": "digest-app.txt", "browser_download_url": f"{base}/digest-app.txt"},
                    {"name": "digest-caddy.txt", "browser_download_url": f"{base}/digest-caddy.txt"},
                    {"name": "sbom-app.spdx.json", "browser_download_url": f"{base}/sbom-app.spdx.json"},
                ],
            }
        ),
        f"{base}/digest-app.txt": APP + "\n",
        f"{base}/digest-caddy.txt": CADDY + "\n",
    }
    release = fu.GitHubReleases(fetch=lambda url: pages[url].encode()).latest()
    assert release == NEW


def test_an_image_list_from_somewhere_else_is_refused() -> None:
    page = json.dumps(
        {"tag_name": "v1.1.0", "assets": [{"name": "digest-app.txt", "browser_download_url": "https://evil.example/digest-app.txt"}]}
    )
    with pytest.raises(fu.UpdateError, match="not on the repository's release page"):
        fu.GitHubReleases(fetch=lambda url: page.encode()).latest()


def test_a_github_that_does_not_answer_is_an_update_error() -> None:
    def fail(url: str) -> bytes:
        raise OSError("network unreachable")

    with pytest.raises(fu.UpdateError, match="could not be read"):
        fu.GitHubReleases(fetch=fail).latest()


# --- the signature check


def test_cosign_checks_the_release_workflow_identity_for_this_tag() -> None:
    commands: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "[]", "")

    fu.CosignVerifier(run=run).verify(APP, fu.Version(1, 1, 0))
    (command,) = commands
    assert command[:3] == ["cosign", "verify", APP]
    identity = command[command.index("--certificate-identity") + 1]
    assert identity == "https://github.com/Franca-Language-Learning/Franca/.github/workflows/release.yml@refs/tags/v1.1.0"
    assert command[command.index("--certificate-oidc-issuer") + 1] == "https://token.actions.githubusercontent.com"
    assert "--certificate-identity-regexp" not in command


def test_a_failed_cosign_check_is_an_update_error() -> None:
    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "Error: no matching signatures\n")

    with pytest.raises(fu.UpdateError, match="no matching signatures"):
        fu.CosignVerifier(run=run).verify(APP, fu.Version(1, 1, 0))


# --- the .env file


def test_the_env_file_keeps_other_lines_and_is_replaced_whole(tmp_path: Path) -> None:
    env = fu.EnvFile(tmp_path / ".env")
    (tmp_path / ".env").write_text("# comment\nFRANCA_PORT=8080\nFRANCA_VERSION=1.0.0\n", encoding="utf-8")
    env.write({"FRANCA_PORT": "8080", "FRANCA_VERSION": "1.1.0", "FRANCA_APP_IMAGE": APP})
    assert (tmp_path / ".env").read_text(encoding="utf-8") == f"# comment\nFRANCA_PORT=8080\nFRANCA_VERSION=1.1.0\nFRANCA_APP_IMAGE={APP}\n"
    assert not (tmp_path / ".env.new").exists()


# --- a run


def test_a_newer_signed_release_is_installed(tmp_path: Path) -> None:
    updater, log, verifier = make(tmp_path, NEW)

    assert updater.run_once(NOW) == "installed"

    assert [image for image, _tag in verifier.checked] == [APP, CADDY]
    assert log == [
        "pull franca-app@s",
        "pull franca-caddy",
        "stop app",
        "snapshot 20261207T023000Z-before-1.1.0",
        "up app caddy",
    ]
    env = fu.EnvFile(tmp_path / ".env").read()
    assert env == {"FRANCA_VERSION": "1.1.0", "FRANCA_APP_IMAGE": APP, "FRANCA_CADDY_IMAGE": CADDY, "FRANCA_PORT": "8080"}
    assert status(tmp_path)["result"] == "installed"
    assert status(tmp_path)["installed"] == "1.1.0"


def test_the_same_release_is_not_installed_again(tmp_path: Path) -> None:
    updater, log, verifier = make(tmp_path, fu.Release(fu.Version(1, 0, 0), {"app": APP, "caddy": CADDY}))
    assert updater.run_once(NOW) == "up-to-date"
    assert log == [] and verifier.checked == []


def test_an_older_release_is_not_installed(tmp_path: Path) -> None:
    updater, log, verifier = make(tmp_path, fu.Release(fu.Version(0, 9, 0), {"app": APP, "caddy": CADDY}))
    assert updater.run_once(NOW) == "up-to-date"
    assert log == [] and verifier.checked == []
    assert fu.EnvFile(tmp_path / ".env").read()["FRANCA_VERSION"] == "1.0.0"


def test_a_development_build_is_replaced_by_the_first_release(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    (tmp_path / ".env").write_text("FRANCA_VERSION=0.1.0-dev\n", encoding="utf-8")
    assert updater.run_once(NOW) == "installed"


def test_an_image_with_a_bad_signature_is_not_installed_and_nothing_is_stopped(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW, refuse=CADDY)

    assert updater.run_once(NOW) == "not-installed"

    assert log == []
    assert fu.EnvFile(tmp_path / ".env").read()["FRANCA_VERSION"] == "1.0.0"
    assert "signature" in status(tmp_path)["message"]


def test_a_failed_pull_installs_nothing(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW, fail_on={"pull franca-caddy"})
    assert updater.run_once(NOW) == "not-installed"
    assert "stop app" not in log


def test_when_github_cannot_be_reached_nothing_changes(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, fu.UpdateError("The latest release could not be read from GitHub: timed out"))
    assert updater.run_once(NOW) == "check-failed"
    assert log == []


def test_when_the_snapshot_fails_the_old_version_is_started_again(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW, healthy=("1.0.0",), snapshot_fails=True)

    assert updater.run_once(NOW) == "not-installed"

    assert log[-1] == "up app caddy"
    assert fu.EnvFile(tmp_path / ".env").read()["FRANCA_VERSION"] == "1.0.0"
    assert "disk full" in status(tmp_path)["message"]


def test_a_new_version_that_does_not_start_is_rolled_back_with_its_database(tmp_path: Path) -> None:
    # The new version never answers; after the rollback, the old version does.
    updater, log, _verifier = make(tmp_path, NEW, healthy=(None, "1.0.0"))

    assert updater.run_once(NOW) == "rolled-back"

    snapshot = "/data/snapshots/franca-20261207T023000Z-before-1.1.0.db"
    assert log[log.index("up app caddy") + 1 :] == ["stop app", f"restore {snapshot}", "up app caddy"]
    assert fu.EnvFile(tmp_path / ".env").read() == {"FRANCA_VERSION": "1.0.0", "FRANCA_APP_IMAGE": OLD_APP, "FRANCA_PORT": "8080"}
    assert status(tmp_path)["result"] == "rolled-back"
    assert "did not answer the health check" in status(tmp_path)["message"]


def test_a_version_reported_with_its_tag_counts_as_the_same_version(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW, healthy=("v1.1.0",))
    assert updater.run_once(NOW) == "installed"


def test_a_new_version_that_reports_the_wrong_version_is_rolled_back(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW, healthy=("1.0.0",))
    assert updater.run_once(NOW) == "rolled-back"


def test_a_failed_rollback_is_reported_as_such(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW, healthy=(None,))
    assert updater.run_once(NOW) == "rollback-failed"
    assert "failed too" in status(tmp_path)["message"]


# --- the database steps and the schedule


def test_the_database_steps_run_in_a_one_off_app_container(tmp_path: Path) -> None:
    commands: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    database = fu.Database(fu.Compose(tmp_path, run=run, project_name="franca"))
    snapshot = database.snapshot("20261207T023000Z-before-1.1.0")
    database.restore(snapshot)

    assert snapshot == "/data/snapshots/franca-20261207T023000Z-before-1.1.0.db"
    for command in commands:
        assert command[:6] == ["docker", "compose", "--project-directory", str(tmp_path), "--project-name", "franca"]
        assert command[6:12] == ["run", "--rm", "--no-deps", "--entrypoint", "python", "app"]


def test_the_snapshot_and_restore_scripts_work_on_a_real_database(tmp_path: Path) -> None:
    import sqlite3

    live = tmp_path / "franca.db"
    with sqlite3.connect(live) as connection:
        connection.execute("CREATE TABLE t (x)")
        connection.execute("INSERT INTO t VALUES (1)")
    snapshot = tmp_path / "snapshots" / "franca-1.db"
    exec(fu._with_arguments(fu.SNAPSHOT_SCRIPT.format(kept=fu.SNAPSHOTS_KEPT), str(live), str(snapshot)), {})  # noqa: S102
    with sqlite3.connect(live) as connection:
        connection.execute("INSERT INTO t VALUES (2)")
    exec(fu._with_arguments(fu.RESTORE_SCRIPT, str(snapshot), str(live)), {})  # noqa: S102
    with sqlite3.connect(live) as connection:
        assert connection.execute("SELECT x FROM t").fetchall() == [(1,)]


def test_old_snapshots_are_removed_and_the_last_five_kept(tmp_path: Path) -> None:
    live = tmp_path / "franca.db"
    live.touch()
    for n in range(7):
        target = tmp_path / "snapshots" / f"franca-2026120{n}T000000Z.db"
        exec(fu._with_arguments(fu.SNAPSHOT_SCRIPT.format(kept=fu.SNAPSHOTS_KEPT), str(live), str(target)), {})  # noqa: S102
    kept = sorted(p.name for p in (tmp_path / "snapshots").iterdir())
    assert kept == [f"franca-2026120{n}T000000Z.db" for n in range(2, 7)]


def test_the_next_run_is_at_the_time_of_day_given() -> None:
    assert fu.next_run(datetime(2026, 12, 7, 1, 0, tzinfo=UTC), "02:30") == datetime(2026, 12, 7, 2, 30, tzinfo=UTC)
    assert fu.next_run(datetime(2026, 12, 7, 2, 30, tzinfo=UTC), "02:30") == datetime(2026, 12, 8, 2, 30, tzinfo=UTC)


# --- after the security review


class BrokenEnv(fu.EnvFile):
    """An .env file that cannot be written, as on a disk with the wrong owner."""

    def write(self, values: object) -> None:  # type: ignore[override]
        raise PermissionError("[Errno 13] Permission denied: '.env.new'")


def test_an_unexpected_error_after_the_app_is_stopped_still_leads_to_a_rollback(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW, healthy=("1.0.0",))
    updater.env = BrokenEnv(tmp_path / ".env")

    assert updater.run_once(NOW) == "rolled-back"

    assert log[-1] == "up app caddy"
    assert "Permission denied" in status(tmp_path)["message"]


def test_a_command_that_hangs_leads_to_a_rollback(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW, healthy=("1.0.0",))

    class HangingCompose(FakeCompose):
        def up(self, *services: str) -> None:
            if "hung once" not in self.log:
                self.log.append("hung once")
                raise subprocess.TimeoutExpired(["docker", "compose", "up"], 900)
            super().up(*services)

    updater.compose = HangingCompose(log)
    assert updater.run_once(NOW) == "rolled-back"
    assert log[-1] == "up app caddy"


def test_a_release_older_than_the_newest_ever_installed_is_refused_even_if_env_says_otherwise(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, NEW)
    updater.high_water = fu.HighWaterMark(tmp_path / "status" / "newest-installed")
    updater.high_water.raise_to(fu.Version(1, 2, 0))

    assert updater.run_once(NOW) == "up-to-date"
    assert log == []


def test_installing_raises_the_newest_ever_installed(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    updater.high_water = fu.HighWaterMark(tmp_path / "status" / "newest-installed")
    assert updater.run_once(NOW) == "installed"
    assert updater.high_water.read() == fu.Version(1, 1, 0)


def test_a_quoted_version_in_env_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text('FRANCA_VERSION="1.1.0"\n', encoding="utf-8")
    assert fu.EnvFile(tmp_path / ".env").read() == {"FRANCA_VERSION": "1.1.0"}


def test_a_development_build_that_is_rolled_back_to_is_recognised(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW, healthy=(None, "0.1.0-dev"))
    (tmp_path / ".env").write_text("FRANCA_VERSION=0.1.0-dev\n", encoding="utf-8")
    assert updater.run_once(NOW) == "rolled-back"


@pytest.mark.parametrize("problem", ["placeholder", "no compose.yaml", "no .env"])
def test_a_wrong_bundle_folder_is_reported_and_nothing_is_done(tmp_path: Path, problem: str) -> None:
    updater, log, verifier = make(tmp_path, NEW)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    updater.bundle = Path(fu.PLACEHOLDER_BUNDLE_DIR) if problem == "placeholder" else tmp_path
    if problem == "no compose.yaml":
        (tmp_path / "compose.yaml").unlink()
    if problem == "no .env":
        (tmp_path / ".env").unlink()

    assert updater.run_once(NOW) == "misconfigured"
    assert log == [] and verifier.checked == []


def test_a_right_bundle_folder_passes_the_check(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    updater.bundle = tmp_path
    assert updater.run_once(NOW) == "installed"


@pytest.mark.parametrize(("given", "used"), [("03:15", "03:15"), ("3:15", "02:30"), ("24:00", "02:30"), ("soon", "02:30")])
def test_an_update_time_that_cannot_be_read_is_replaced_by_the_default(given: str, used: str) -> None:
    assert fu.update_time(given) == used


def test_a_failed_restore_copy_leaves_the_database_as_it_was(tmp_path: Path) -> None:
    import sqlite3

    live = tmp_path / "franca.db"
    with sqlite3.connect(live) as connection:
        connection.execute("CREATE TABLE t (x)")
    missing_snapshot = tmp_path / "snapshots" / "not-there.db"
    with pytest.raises(FileNotFoundError):
        exec(fu._with_arguments(fu.RESTORE_SCRIPT, str(missing_snapshot), str(live)), {})  # noqa: S102
    with sqlite3.connect(live) as connection:
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == [("t",)]
