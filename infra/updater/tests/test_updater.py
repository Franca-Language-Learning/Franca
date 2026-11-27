"""Tests for the updater (story E01-007), with stand-ins for GitHub, cosign, docker compose and the health check.

The rehearsal against real containers is infra/tests/rehearse-update.sh.
"""

import http.client
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from email.message import Message
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

    def up(self, *services: str, wait: int | None = None) -> None:
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


TAILSCALE = f"ghcr.io/franca-language-learning/franca-tailscale@sha256:{'d' * 64}"
OLD_TAILSCALE = f"ghcr.io/franca-language-learning/franca-tailscale@sha256:{'e' * 64}"
WITH_TAILSCALE = fu.Release(fu.Version(1, 1, 0), {"app": APP, "caddy": CADDY, "tailscale": TAILSCALE})


def with_tailnet(tmp_path: Path, profiles: str = "updates,backups,tailnet") -> None:
    env = tmp_path / ".env"
    env.write_text(
        env.read_text(encoding="utf-8") + f"COMPOSE_PROFILES={profiles}\nFRANCA_TAILSCALE_IMAGE={OLD_TAILSCALE}\n", encoding="utf-8"
    )


def test_a_new_tailscale_image_is_started_after_the_app_is_healthy(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, WITH_TAILSCALE)
    with_tailnet(tmp_path)

    assert updater.run_once(NOW) == "installed"

    assert log[-2:] == ["up app caddy", "up tailscale"]
    assert fu.EnvFile(tmp_path / ".env").read()["FRANCA_TAILSCALE_IMAGE"] == TAILSCALE


def test_tailscale_is_not_started_when_the_private_network_is_switched_off(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, WITH_TAILSCALE)
    with_tailnet(tmp_path, profiles="updates,backups")

    assert updater.run_once(NOW) == "installed"

    assert "up tailscale" not in log


def test_an_unchanged_tailscale_image_is_not_restarted(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, fu.Release(fu.Version(1, 1, 0), {"app": APP, "caddy": CADDY, "tailscale": OLD_TAILSCALE}))
    with_tailnet(tmp_path)

    assert updater.run_once(NOW) == "installed"

    assert "up tailscale" not in log


def test_a_tailscale_image_that_does_not_start_is_put_back_and_the_app_update_kept(tmp_path: Path) -> None:
    updater, log, _verifier = make(tmp_path, WITH_TAILSCALE, fail_on={"up tailscale"})
    with_tailnet(tmp_path)

    assert updater.run_once(NOW) == "installed"

    assert log[-3:] == ["up app caddy", "up tailscale", "up tailscale"]
    env = fu.EnvFile(tmp_path / ".env").read()
    assert env["FRANCA_TAILSCALE_IMAGE"] == OLD_TAILSCALE
    assert env["FRANCA_APP_IMAGE"] == APP
    assert "tailscale" in status(tmp_path)["message"]


STATUS = f"ghcr.io/franca-language-learning/franca-status@sha256:{'f' * 64}"


def test_a_new_status_image_is_started_after_the_app_when_the_monitoring_is_on(tmp_path: Path) -> None:
    release = fu.Release(fu.Version(1, 1, 0), {"app": APP, "caddy": CADDY, "tailscale": TAILSCALE, "status": STATUS})
    updater, log, _verifier = make(tmp_path, release)
    with_tailnet(tmp_path, profiles="updates,backups,tailnet,monitoring")

    assert updater.run_once(NOW) == "installed"

    assert log[-3:] == ["up app caddy", "up tailscale", "up status"]
    assert fu.EnvFile(tmp_path / ".env").read()["FRANCA_STATUS_IMAGE"] == STATUS


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


def test_tailscale_and_status_are_started_with_a_wait_for_their_health_check(tmp_path: Path) -> None:
    commands: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    updater, _log, _verifier = make(tmp_path, fu.Release(fu.Version(1, 1, 0), {"app": APP, "caddy": CADDY, "status": STATUS}))
    with_tailnet(tmp_path, profiles="monitoring")
    real = fu.Compose(tmp_path, run=run)
    updater.compose = real

    updater._start_new_images(fu.EnvFile(tmp_path / ".env").read(), {"FRANCA_STATUS_IMAGE": STATUS})

    assert commands[-1][-4:] == ["--wait", "--wait-timeout", "120", "status"]


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


# --- reports to health monitoring (story E01-010)


class FakeMonitor(fu.Monitor):
    def __init__(self) -> None:
        self.reports: list[tuple[str, bool, str]] = []

    def report(self, key: str, success: bool, message: str) -> None:
        self.reports.append((key, success, message))


@pytest.mark.parametrize(
    ("release", "fail_on", "expected"),
    [
        (NEW, None, True),  # installed
        (fu.Release(fu.Version(1, 0, 0), {"app": APP, "caddy": CADDY}), None, True),  # up to date
        (NEW, {"up app caddy"}, False),  # rolled back
    ],
)
def test_each_run_is_reported_to_the_health_monitoring(
    tmp_path: Path, release: fu.Release, fail_on: set[str] | None, expected: bool
) -> None:
    updater, _log, _verifier = make(tmp_path, release, fail_on=fail_on)
    monitor = FakeMonitor()
    updater.monitor = monitor

    updater.run_once(NOW)

    assert len(monitor.reports) == 1
    key, success, message = monitor.reports[0]
    assert (key, success) == ("nightly_update", expected)
    assert message == status(tmp_path)["message"]


def test_the_state_is_reported_again_later_so_a_restart_of_the_monitoring_loses_nothing(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.run_once(NOW)

    updater.report_state(NOW + timedelta(hours=5))

    assert [(key, success) for key, success, _message in monitor.reports] == [("nightly_update", True)] * 2


def test_no_successful_run_for_26_hours_is_reported_as_a_failure(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.run_once(NOW)

    updater.report_state(NOW + timedelta(hours=27))

    key, success, message = monitor.reports[-1]
    assert (key, success) == ("nightly_update", False)
    assert "2026-12-07" in message


def test_a_failed_run_stays_a_failure_until_a_run_succeeds(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.run_once(NOW)
    updater.releases = FakeReleases(fu.UpdateError("GitHub did not answer"))
    updater.run_once(NOW + timedelta(days=1))

    updater.report_state(NOW + timedelta(days=1, hours=1))

    key, success, message = monitor.reports[-1]
    assert (key, success) == ("nightly_update", False)
    assert "GitHub did not answer" in message


def test_before_the_first_run_the_state_is_reported_as_good(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor

    updater.report_state(NOW)

    assert monitor.reports == [("nightly_update", True, "No update has run yet")]


def test_a_report_is_a_post_with_the_token_and_the_reason(tmp_path: Path) -> None:
    token = tmp_path / "status_push_token"
    token.write_text("t" * 40 + "\n", encoding="utf-8")
    sent: list[urllib.request.Request] = []
    monitor = fu.Monitor("http://status:8080/", token, send=sent.append)

    monitor.report("nightly_update", False, "Starting app failed & more")

    request = sent[0]
    assert request.get_method() == "POST"
    assert request.full_url == (
        "http://status:8080/api/v1/endpoints/nightly_update/external?success=false&error=Starting+app+failed+%26+more"
    )
    assert request.get_header("Authorization") == "Bearer " + "t" * 40


def test_monitoring_that_cannot_be_reached_does_not_stop_the_updater(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    token = tmp_path / "status_push_token"
    token.write_text("t" * 40, encoding="utf-8")

    def unreachable(_request: urllib.request.Request) -> None:
        raise OSError("connection refused")

    fu.Monitor("http://status:8080", token, send=unreachable).report("nightly_update", True, "Installed")

    assert "connection refused" in capsys.readouterr().out


def test_without_a_push_token_nothing_is_reported(tmp_path: Path) -> None:
    token = tmp_path / "status_push_token"
    token.write_text("", encoding="utf-8")
    sent: list[urllib.request.Request] = []

    fu.Monitor("http://status:8080", token, send=sent.append).report("nightly_update", True, "Installed")

    assert sent == []


# --- reading from GitHub


class FakeResponse:
    def __init__(self, body: bytes, length: int | None = None) -> None:
        self.body = body
        self.headers = Message()
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def test_a_body_up_to_the_limit_is_read_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"x" * 2_000_000
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse(body))
    assert fu.http_fetch("https://example.org/cosign", limit=2_000_000) == body


def test_a_body_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse(b"x" * 1_000_001))
    with pytest.raises(fu.UpdateError, match="larger than"):
        fu.http_fetch("https://example.org/release.json")


# --- the socket proxy (stories E01-007 and E01-010)


def test_the_docker_api_is_checked_at_the_proxys_ping_address(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def answer(url: str, timeout: float) -> FakeResponse:
        asked.append(url)
        return FakeResponse(b"OK")

    monkeypatch.setattr(urllib.request, "urlopen", answer)

    assert fu.docker_api_probe("tcp://socket-proxy:2375")() is None
    assert asked == ["http://socket-proxy:2375/_ping"]


def test_a_proxy_that_does_not_answer_gives_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, timeout: float) -> FakeResponse:
        raise OSError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    problem = fu.docker_api_probe("tcp://socket-proxy:2375")()

    assert problem is not None
    assert "Connection refused" in problem


def test_a_proxy_that_answers_something_else_is_a_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse(b"<html>Forbidden</html>"))

    assert fu.docker_api_probe("tcp://socket-proxy:2375")() is not None


@pytest.mark.parametrize(("problem", "success"), [(None, True), ("Connection refused", False)])
def test_the_state_of_the_docker_api_is_reported(tmp_path: Path, problem: str | None, success: bool) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.docker_api = lambda: problem

    updater.report_docker_api()

    assert len(monitor.reports) == 1
    key, reported, message = monitor.reports[0]
    assert (key, reported) == ("franca_socket-proxy", success)
    assert message
    if problem:
        assert problem in message


def test_without_a_docker_api_probe_nothing_is_reported(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor

    updater.report_docker_api()

    assert monitor.reports == []


def test_the_service_checks_the_proxy_each_minute_reports_its_state_each_hour_and_updates_at_night(tmp_path: Path) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.docker_api = lambda: None
    service = fu.Service(updater, "02:30", wake=NOW)

    for minute in range(61):
        service.tick(NOW - timedelta(hours=1) + timedelta(minutes=minute))
    keys = [key for key, _success, _message in monitor.reports]

    assert keys.count("franca_socket-proxy") == 61
    # The first tick reports the state; the run at 02:30 reports it after the update.
    assert keys.count("nightly_update") == 2
    assert status(tmp_path)["result"] == "installed"
    assert service.wake == NOW + timedelta(days=1)


@pytest.mark.parametrize(("wake_in", "sleep"), [(timedelta(hours=5), 60.0), (timedelta(seconds=30), 30.0), (-timedelta(minutes=1), 1.0)])
def test_the_service_sleeps_a_minute_at_most_and_wakes_for_the_update(tmp_path: Path, wake_in: timedelta, sleep: float) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    service = fu.Service(updater, "02:30", wake=NOW + wake_in)

    assert service.seconds_to_sleep(NOW) == sleep


def test_a_garbled_answer_from_the_proxy_is_a_problem_and_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def garbled(url: str, timeout: float) -> FakeResponse:
        raise http.client.BadStatusLine("garbage")

    monkeypatch.setattr(urllib.request, "urlopen", garbled)

    problem = fu.docker_api_probe("tcp://socket-proxy:2375")()

    assert problem is not None
    assert "garbage" in problem


def test_an_error_in_the_proxy_check_does_not_stop_the_nightly_update(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor

    def broken() -> str | None:
        raise http.client.BadStatusLine("garbage")

    updater.docker_api = broken
    service = fu.Service(updater, "02:30", wake=NOW)

    service.tick(NOW)

    assert status(tmp_path)["result"] == "installed"
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert {"result": "error", "step": "socket proxy check"} == {k: v for k, v in printed[0].items() if k != "message"}


def test_an_error_in_the_nightly_update_does_not_stop_the_proxy_check_at_the_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updater, _log, _verifier = make(tmp_path, NEW)
    monitor = FakeMonitor()
    updater.monitor = monitor
    updater.docker_api = lambda: None

    def broken(_self: fu.Updater, now: datetime) -> str:
        raise RuntimeError("the status volume is full")

    monkeypatch.setattr(fu.Updater, "run_once", broken)
    service = fu.Service(updater, "02:30", wake=NOW)

    service.tick(NOW)
    service.tick(NOW + timedelta(minutes=1))

    assert [key for key, _success, _message in monitor.reports].count("franca_socket-proxy") == 2
    assert service.wake == NOW + timedelta(days=1)


# --- the app on the restored copy, for the backup's monthly restore test (story E01-008)

SERVER_SOURCE = Path(__file__).resolve().parents[3] / "server" / "src"


def restore_check(tmp_path: Path) -> tuple[fu.Updater, list[Sequence[str]], Path]:
    folder = tmp_path / "restore-test"
    folder.mkdir()
    commands: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    updater, _log, _verifier = make(tmp_path, NEW)
    updater.compose = fu.Compose(tmp_path, run=run, project_name="franca")
    updater.restore_test_dir = folder
    return updater, commands, folder


def test_without_a_request_no_container_is_started(tmp_path: Path) -> None:
    updater, commands, _folder = restore_check(tmp_path)

    updater.check_restored_copy()

    assert commands == []


def test_a_request_starts_the_app_on_the_restored_copy_in_a_one_off_container_once(tmp_path: Path) -> None:
    updater, commands, folder = restore_check(tmp_path)
    (folder / "request.json").write_text(json.dumps({"id": "2026-12-07T03:30:00+00:00-ab12"}), encoding="utf-8")

    updater.check_restored_copy()
    updater.check_restored_copy()

    assert len(commands) == 1
    command = list(commands[0])
    assert command[:6] == ["docker", "compose", "--project-directory", str(tmp_path), "--project-name", "franca"]
    assert command[6:12] == ["run", "--rm", "--no-deps", "--entrypoint", "python", "restore-check"]
    assert command[12] == "-c"


def test_a_request_that_has_its_answer_is_not_started_again(tmp_path: Path) -> None:
    updater, commands, folder = restore_check(tmp_path)
    (folder / "request.json").write_text(json.dumps({"id": "one"}), encoding="utf-8")
    (folder / "answer.json").write_text(json.dumps({"id": "one", "passed": True}), encoding="utf-8")

    updater.check_restored_copy()

    assert commands == []


def test_a_one_off_container_that_cannot_start_is_printed_and_the_updater_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    updater, _commands, folder = restore_check(tmp_path)
    updater.compose = fu.Compose(tmp_path, run=lambda command: subprocess.CompletedProcess(command, 1, "", "no such image\n"))
    (folder / "request.json").write_text(json.dumps({"id": "one"}), encoding="utf-8")

    updater.check_restored_copy()

    assert "restore-check-not-run" in capsys.readouterr().out


def test_the_service_looks_for_a_request_each_minute(tmp_path: Path) -> None:
    updater, commands, folder = restore_check(tmp_path)
    service = fu.Service(updater, "02:30", wake=NOW + timedelta(hours=5))
    service.tick(NOW)
    (folder / "request.json").write_text(json.dumps({"id": "one"}), encoding="utf-8")

    service.tick(NOW + timedelta(minutes=1))

    assert len(commands) == 1


def run_check_script(folder: Path, port: int) -> dict[str, object]:
    """Runs the script of the one-off container on this computer, with the server's code, as the container would."""
    script = fu.restore_check_script(str(folder), port)
    environment = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "PYTHONPATH": str(SERVER_SOURCE),
        "FRANCA_ENVIRONMENT": "development",
    }
    subprocess.run([sys.executable, "-c", script], env=environment, timeout=120, check=True, capture_output=True)
    answer: dict[str, object] = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
    return answer


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def test_the_script_starts_the_app_on_a_restored_copy_and_reads_its_health_answer(tmp_path: Path) -> None:
    folder = tmp_path / "restore-test"
    folder.mkdir()
    environment = {"PYTHONPATH": str(SERVER_SOURCE), "FRANCA_DATABASE_PATH": str(folder / "franca.db"), "PATH": "/usr/bin:/bin"}
    subprocess.run([sys.executable, "-m", "franca.platform.migrate"], env=environment, check=True, capture_output=True)
    (folder / "request.json").write_text(json.dumps({"id": "one"}), encoding="utf-8")

    answer = run_check_script(folder, free_port())

    assert answer["id"] == "one"
    assert answer["passed"] is True, answer
    assert answer["version"] == "0.1.0-dev"


def test_the_script_reports_a_copy_the_app_cannot_start_on(tmp_path: Path) -> None:
    folder = tmp_path / "restore-test"
    folder.mkdir()
    (folder / "franca.db").write_bytes(b"not a database, but long enough to be read as a file " * 100)
    (folder / "request.json").write_text(json.dumps({"id": "two"}), encoding="utf-8")

    answer = run_check_script(folder, free_port())

    assert answer["id"] == "two"
    assert answer["passed"] is False
    assert answer["message"]


class FlakyOpener:
    """Stands in for urlopen: raises the given errors in turn, then answers with the body."""

    def __init__(self, errors: list[Exception], body: bytes = b"ok", short_answers: int = 0) -> None:
        self.errors = errors
        self.body = body
        self.short_answers = short_answers
        self.calls = 0

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        if self.short_answers:
            self.short_answers -= 1
            return FakeResponse(self.body[: len(self.body) // 2], length=len(self.body))
        return FakeResponse(self.body, length=len(self.body))


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        urllib.error.URLError(TimeoutError("timed out")),
        ConnectionResetError("reset"),
        urllib.error.HTTPError("https://example.org/cosign", 503, "Service Unavailable", Message(), None),
    ],
)
def test_a_download_that_times_out_or_meets_a_server_error_is_tried_again(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    opener = FlakyOpener([error])
    pauses: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    assert fu.http_fetch("https://example.org/cosign", pause=pauses.append) == b"ok"
    assert opener.calls == 2
    assert pauses == [fu.RETRY_PAUSES[0]]


def test_a_download_is_given_up_after_the_last_try(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FlakyOpener([TimeoutError("timed out") for _ in range(len(fu.RETRY_PAUSES) + 1)])
    pauses: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    with pytest.raises(TimeoutError):
        fu.http_fetch("https://example.org/cosign", pause=pauses.append)
    assert opener.calls == len(fu.RETRY_PAUSES) + 1
    assert pauses == list(fu.RETRY_PAUSES)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://example.org/cosign", 404, "Not Found", Message(), None),
        urllib.error.HTTPError("https://example.org/cosign", 499, "Client Closed Request", Message(), None),
        urllib.error.URLError("unknown url type"),
        urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")),
    ],
)
def test_a_client_error_or_a_bad_certificate_is_not_tried_again(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    opener = FlakyOpener([error])
    pauses: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    with pytest.raises(urllib.error.URLError):
        fu.http_fetch("https://example.org/cosign", pause=pauses.append)
    assert opener.calls == 1
    assert pauses == []


def test_an_answer_cut_short_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FlakyOpener([], body=b"0123456789", short_answers=1)
    pauses: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    assert fu.http_fetch("https://example.org/cosign", pause=pauses.append) == b"0123456789"
    assert opener.calls == 2
    assert pauses == [fu.RETRY_PAUSES[0]]


def test_a_body_over_the_limit_is_not_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FlakyOpener([], body=b"x" * 11)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    with pytest.raises(fu.UpdateError, match="larger than"):
        fu.http_fetch("https://example.org/release.json", limit=10, pause=lambda _seconds: None)
    assert opener.calls == 1
