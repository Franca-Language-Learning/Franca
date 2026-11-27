"""Tests for the Linux part of the installer (story E01-011), with stand-ins for docker, GitHub and ntfy.

The rehearsal with real containers is infra/tests/rehearse_install.py.
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "installer" / "linux"))
sys.path.insert(0, str(ROOT / "infra" / "updater"))

import franca_install as fi  # noqa: E402
import franca_updater as fu  # noqa: E402

DIGEST = "sha256:" + "a" * 64
IMAGES = {
    service: f"ghcr.io/franca-language-learning/franca-{service}@{DIGEST}"
    for service in ("app", "caddy", "updater", "backup", "tailscale", "status")
}
RELEASE = fu.Release(fu.Version(1, 0, 0), IMAGES)


def answers(tmp_path: Path, **changes: str) -> fi.Answers:
    backups = tmp_path / "disk-j"
    backups.mkdir(exist_ok=True)
    values = {
        "owner_email": "owner@example.org",
        "google_client_id": "123-abc.apps.googleusercontent.com",
        "google_client_secret": "GOCSPX-secret-value",
        "tailscale_authkey": "tskey-auth-test",
        "backup_dir": str(backups / "franca-backups"),
    } | changes
    return fi.Answers.from_json(json.dumps(values))


# --- the answers


def test_answers_are_read_from_json(tmp_path: Path) -> None:
    given = answers(tmp_path)
    assert given.owner_email == "owner@example.org"
    assert given.backup_dir == tmp_path / "disk-j" / "franca-backups"
    assert given.tailscale_hostname == "franca"


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("owner_email", "not an address", "e-mail"),
        ("google_client_id", "123-abc", "Google client ID"),
        ("tailscale_authkey", "tskey-api-123", "Tailscale auth key"),
        ("backup_dir", "relative/folder", "backup folder"),
        ("google_client_secret", "line\nbreak", "Google client secret"),
    ],
)
def test_an_answer_that_cannot_be_right_is_refused_with_a_message(tmp_path: Path, field: str, value: str, named: str) -> None:
    with pytest.raises(fi.InstallError, match=named):
        answers(tmp_path, **{field: value})


def test_the_heartbeat_address_is_optional(tmp_path: Path) -> None:
    assert answers(tmp_path).healthchecks_ping_url == ""
    given = answers(tmp_path, healthchecks_ping_url=" https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b ")
    assert given.healthchecks_ping_url == "https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b"


@pytest.mark.parametrize(
    "value",
    [
        "http://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b",
        "https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b?x=1",
        "https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b/fail",
        "https://example.org/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b",
        "https://hc-ping.com.example.org/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b",
        "https://hc-ping.com/abc123",
        "hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b",
        "https://hc-ping.com/",
    ],
)
def test_a_heartbeat_address_that_cannot_be_right_is_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises(fi.InstallError, match="healthchecks.io"):
        answers(tmp_path, healthchecks_ping_url=value)


def test_the_heartbeat_address_is_written_as_a_secret_and_not_to_env(tmp_path: Path) -> None:
    url = "https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b"
    given = answers(tmp_path, healthchecks_ping_url=url)
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    fi.write_secrets(bundle / "secrets", given)
    fi.write_env(bundle, RELEASE, given, tailscale_name=None)

    assert (bundle / "secrets" / "healthchecks_ping_url").read_text(encoding="utf-8") == url
    assert oct((bundle / "secrets" / "healthchecks_ping_url").stat().st_mode & 0o777) == "0o644"
    assert url not in (bundle / ".env").read_text(encoding="utf-8")
    assert "0f5a7c2e" not in repr(given)


PING_URL = "https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b"


def test_without_a_heartbeat_address_on_a_first_installation_the_secret_file_is_empty(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"

    fi.write_secrets(folder, answers(tmp_path))

    assert (folder / "healthchecks_ping_url").read_text(encoding="utf-8") == ""


def test_an_empty_answer_in_a_later_run_keeps_the_saved_address(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"
    fi.write_secrets(folder, answers(tmp_path, healthchecks_ping_url=PING_URL))

    fi.write_secrets(folder, answers(tmp_path))

    assert (folder / "healthchecks_ping_url").read_text(encoding="utf-8") == PING_URL


@pytest.mark.parametrize("value", ["off", " OFF "])
def test_off_switches_the_heartbeat_off(tmp_path: Path, value: str) -> None:
    folder = tmp_path / "secrets"
    fi.write_secrets(folder, answers(tmp_path, healthchecks_ping_url=PING_URL))

    fi.write_secrets(folder, answers(tmp_path, healthchecks_ping_url=value))

    assert (folder / "healthchecks_ping_url").read_text(encoding="utf-8") == ""


def test_the_refusal_of_a_heartbeat_address_says_what_to_do_after_the_questions(tmp_path: Path) -> None:
    with pytest.raises(fi.InstallError) as refused:
        answers(tmp_path, healthchecks_ping_url="https://example.org/x")

    message = str(refused.value)
    assert "Run the installer again" in message
    assert "type off" in message
    assert "press Enter for no heartbeat" not in message


# --- a later run without a new Tailscale auth key


def test_the_tailscale_auth_key_may_be_empty(tmp_path: Path) -> None:
    assert answers(tmp_path, tailscale_authkey="").tailscale_authkey == ""


class Volumes:
    """Answers docker volume inspect: the volumes in `present` exist."""

    def __init__(self, present: set[str]) -> None:
        self.present = present
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        found = command[:3] == ["docker", "volume", "inspect"] and command[3] in self.present
        return subprocess.CompletedProcess(command, 0 if found else 1, "", "" if found else "no such volume\n")


def test_without_a_key_the_installer_needs_the_saved_tailscale_state(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    with pytest.raises(fi.InstallError, match="tskey-auth-"):
        fi.check_tailscale_key(answers(tmp_path, tailscale_authkey=""), bundle, run=Volumes(set()))


def test_without_a_key_the_saved_tailscale_state_of_this_project_is_used(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env").write_text("COMPOSE_PROJECT_NAME=franca-test\n", encoding="utf-8")
    volumes = Volumes({"franca-test_tailscale-state"})

    fi.check_tailscale_key(answers(tmp_path, tailscale_authkey=""), bundle, run=volumes)

    assert volumes.commands == [["docker", "volume", "inspect", "franca-test_tailscale-state"]]


def test_with_a_key_the_saved_state_is_not_looked_at(tmp_path: Path) -> None:
    volumes = Volumes(set())

    fi.check_tailscale_key(answers(tmp_path), tmp_path, run=volumes)

    assert volumes.commands == []


def test_the_answers_are_not_shown_in_their_text_form(tmp_path: Path) -> None:
    given = answers(tmp_path)
    assert "GOCSPX" not in repr(given)
    assert "tskey" not in repr(given)


# --- the secrets


def test_the_secrets_are_written_and_the_generated_ones_are_returned(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"

    shown = fi.write_secrets(folder, answers(tmp_path))

    assert set(shown) == {"backup_password", "ntfy_topic"}
    assert (folder / "google_client_secret").read_text() == "GOCSPX-secret-value"
    assert (folder / "tailscale_authkey").read_text() == "tskey-auth-test"
    assert len((folder / "backup_password").read_text()) >= 43  # 32 random bytes
    assert (folder / "ntfy_topic").read_text().startswith("franca-")
    assert len((folder / "status_push_token").read_text()) >= 43
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    assert all(oct(file.stat().st_mode & 0o777) == "0o644" for file in folder.iterdir())


def test_a_second_run_keeps_the_generated_secrets(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"
    fi.write_secrets(folder, answers(tmp_path))
    password = (folder / "backup_password").read_text()
    fi.mark_shown(folder)

    shown = fi.write_secrets(folder, answers(tmp_path, tailscale_authkey="tskey-auth-next"))

    assert shown == {}
    assert (folder / "backup_password").read_text() == password
    assert (folder / "tailscale_authkey").read_text() == "tskey-auth-next"


def test_the_password_is_shown_again_after_a_run_that_stopped_before_the_end(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"
    first = fi.write_secrets(folder, answers(tmp_path))
    # The first run stopped before the owner was shown the password, so mark_shown was not called.

    again = fi.write_secrets(folder, answers(tmp_path))

    assert again == first


def test_the_topic_fits_the_status_containers_pattern(tmp_path: Path) -> None:
    folder = tmp_path / "secrets"
    fi.write_secrets(folder, answers(tmp_path))
    topic = (folder / "ntfy_topic").read_text()
    token = (folder / "status_push_token").read_text()
    assert fi.TOPIC_PATTERN.fullmatch(topic)
    assert fi.TOKEN_PATTERN.fullmatch(token)


# --- the .env file


def test_the_env_file_names_the_release_and_the_settings(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None)

    env = fu.EnvFile(bundle / ".env").read()
    assert env["FRANCA_VERSION"] == "1.0.0"
    assert env["FRANCA_APP_IMAGE"] == IMAGES["app"]
    assert env["FRANCA_STATUS_IMAGE"] == IMAGES["status"]
    assert env["FRANCA_BUNDLE_DIR"] == str(bundle)
    assert env["FRANCA_SECRETS_DIR"] == str(bundle / "secrets")
    assert env["COMPOSE_PROFILES"] == "updates,backups,tailnet,monitoring"
    assert env["COMPOSE_PROJECT_NAME"] == "franca"
    assert env["FRANCA_OWNER_EMAIL"] == "owner@example.org"
    assert env["FRANCA_GOOGLE_CLIENT_ID"] == "123-abc.apps.googleusercontent.com"
    assert "FRANCA_TAILSCALE_NAME" not in env
    assert "GOCSPX" not in (bundle / ".env").read_text()


def test_the_env_file_names_the_group_that_can_open_dockers_socket(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    socket = tmp_path / "docker.sock"
    socket.touch()

    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None, docker_socket=socket)

    # The socket proxy runs as a user other than root, in this group (infra/compose.yaml).
    assert fu.EnvFile(bundle / ".env").read()["FRANCA_DOCKER_GID"] == str(socket.stat().st_gid)


class RootOwnedSocket:
    """Stands in for a socket that belongs to group 0, as when Docker was installed without a docker group."""

    def exists(self) -> bool:
        return True

    def stat(self) -> os.stat_result:
        return os.stat_result((0o140660, 0, 0, 1, 0, 0, 0, 0, 0, 0))


def test_a_socket_that_belongs_to_the_root_group_gives_group_0(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None, docker_socket=RootOwnedSocket())  # type: ignore[arg-type]

    assert fu.EnvFile(bundle / ".env").read()["FRANCA_DOCKER_GID"] == "0"


def test_without_dockers_socket_the_installer_stops_with_a_message(tmp_path: Path) -> None:
    with pytest.raises(fi.InstallError, match="Restart the PC and run the installer again"):
        fi.check_docker_socket(tmp_path / "missing.sock")


def test_with_dockers_socket_the_check_passes(tmp_path: Path) -> None:
    socket = tmp_path / "docker.sock"
    socket.touch()

    fi.check_docker_socket(socket)


def test_without_dockers_socket_no_group_is_written(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None, docker_socket=tmp_path / "missing.sock")

    assert "FRANCA_DOCKER_GID" not in fu.EnvFile(bundle / ".env").read()


def test_the_tailscale_name_gives_the_public_address(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name="franca.tail1234.ts.net")

    env = fu.EnvFile(bundle / ".env").read()
    assert env["FRANCA_TAILSCALE_NAME"] == "franca.tail1234.ts.net"
    assert env["FRANCA_PUBLIC_URL"] == "https://franca.tail1234.ts.net"


# --- the backup folder


def test_the_backup_folder_gets_the_disk_marker_and_belongs_to_the_backup_user(tmp_path: Path) -> None:
    (tmp_path / "disk-j").mkdir()
    folder = tmp_path / "disk-j" / "franca-backups"
    owners: list[tuple[Path, int, int]] = []

    fi.prepare_backup_folder(folder, chown=lambda path, uid, gid: owners.append((path, uid, gid)), owner_of=lambda _path: 10001)

    assert (folder / ".franca-backup-disk").is_file()
    assert (folder, 10001, 10001) in owners


def test_a_disk_that_does_not_keep_linux_owners_is_refused(tmp_path: Path) -> None:
    (tmp_path / "disk-j").mkdir()

    with pytest.raises(fi.InstallError, match="NTFS"):
        fi.prepare_backup_folder(tmp_path / "disk-j" / "franca-backups", chown=lambda *_: None, owner_of=lambda _path: 0)


def test_a_symlink_in_the_bundle_folder_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env").symlink_to(tmp_path / "elsewhere")

    with pytest.raises(fi.InstallError, match="link"):
        fi.check_no_links(bundle)


def test_a_release_without_all_its_images_is_refused() -> None:
    class Releases(fu.GitHubReleases):
        def latest(self) -> fu.Release:
            return fu.Release(fu.Version(1, 0, 0), {"app": IMAGES["app"], "caddy": IMAGES["caddy"]})

    class Verifier:
        def verify(self, image: str, version: fu.Version) -> None:
            pass

    with pytest.raises(fi.InstallError, match="status"):
        fi.verified_release(Releases(), Verifier())


def test_a_backup_folder_on_a_disk_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(fi.InstallError, match="disk"):
        fi.prepare_backup_folder(tmp_path / "no-disk" / "franca-backups", chown=lambda *_: None, owner_of=lambda _path: 10001)


# --- cosign


def test_cosign_is_kept_only_when_its_checksum_matches(tmp_path: Path) -> None:
    good = b"cosign binary"
    target = tmp_path / "cosign"

    fi.install_cosign(target, fetch=lambda _url: good, sha256=hashlib.sha256(good).hexdigest())

    assert target.read_bytes() == good
    assert os.access(target, os.X_OK)
    with pytest.raises(fi.InstallError, match="checksum"):
        fi.install_cosign(tmp_path / "other", fetch=lambda _url: b"something else", sha256=hashlib.sha256(good).hexdigest())
    assert not (tmp_path / "other").exists()


# --- starting the bundle


class FakeDocker:
    """Answers docker compose commands; the tailscale status names the node."""

    def __init__(self, dns_name: str = "franca.tail1234.ts.net.") -> None:
        self.commands: list[list[str]] = []
        self.dns_name = dns_name

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append(command)
        if "status" in command and "tailscale" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"Self": {"DNSName": self.dns_name}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_the_bundle_is_started_with_tailscale_first_and_its_name_is_written(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    fi.write_secrets(bundle / "secrets", answers(tmp_path))
    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None)
    docker = FakeDocker()

    name = fi.start_bundle(bundle, RELEASE, answers(tmp_path), run=docker)

    assert name == "franca.tail1234.ts.net"
    ups = [command for command in docker.commands if "up" in command]
    assert ups[0][-1] == "tailscale"
    assert "--wait" in ups[-1]
    assert fu.EnvFile(bundle / ".env").read()["FRANCA_PUBLIC_URL"] == "https://franca.tail1234.ts.net"
    # The key has been used to join, so it is not kept.
    assert (bundle / "secrets" / "tailscale_authkey").read_text() == ""


def test_the_key_is_emptied_even_when_the_start_fails(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    fi.write_secrets(bundle / "secrets", answers(tmp_path))
    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None)

    with pytest.raises(fi.InstallError):
        fi.start_bundle(bundle, RELEASE, answers(tmp_path), run=FakeDocker(dns_name=""))

    assert (bundle / "secrets" / "tailscale_authkey").read_text() == ""


class TailscaleFails(FakeDocker):
    """docker compose up for tailscale fails, as when the saved Tailscale state is no longer accepted."""

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "up" in command and "tailscale" in command:
            self.commands.append(list(command))
            return subprocess.CompletedProcess(list(command), 1, "", "container is unhealthy\n")
        return super().__call__(command)


def test_without_a_key_a_failed_join_says_to_make_a_new_key(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    given = answers(tmp_path, tailscale_authkey="")
    fi.write_secrets(bundle / "secrets", given)

    with pytest.raises(fi.InstallError, match="could not sign in to your tailnet with the saved Tailscale state") as refused:
        fi.start_bundle(bundle, RELEASE, given, run=TailscaleFails())

    assert "steps 5 to 8 of docs/private-network.md" in str(refused.value)


def test_with_a_key_a_failed_join_gives_the_reason(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    fi.write_secrets(bundle / "secrets", answers(tmp_path))

    with pytest.raises(fi.InstallError, match="Joining the tailnet failed: container is unhealthy"):
        fi.start_bundle(bundle, RELEASE, answers(tmp_path), run=TailscaleFails())


class Stop(Exception):
    """Ends install() in a test once the checks before any change have run."""


def test_the_installation_checks_dockers_socket_and_the_tailscale_key_before_anything_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(fi, "check_docker_socket", lambda *_args: called.append("docker socket"))

    def check_key(*_args: object) -> None:
        called.append("tailscale key")
        raise Stop

    monkeypatch.setattr(fi, "check_tailscale_key", check_key)
    bundle = tmp_path / "bundle"

    with pytest.raises(Stop):
        fi.install(answers(tmp_path), bundle, RELEASE, ROOT / "infra" / "compose.yaml", run=FakeDocker())

    assert called == ["docker socket", "tailscale key"]
    assert not (bundle / "secrets").exists()


def test_a_tailnet_without_https_names_is_reported(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    fi.write_secrets(bundle / "secrets", answers(tmp_path))
    fi.write_env(bundle, RELEASE, answers(tmp_path), tailscale_name=None)

    with pytest.raises(fi.InstallError, match="MagicDNS"):
        fi.start_bundle(bundle, RELEASE, answers(tmp_path), run=FakeDocker(dns_name=""))


# --- the test alert


def test_the_test_alert_goes_to_the_topic(tmp_path: Path) -> None:
    sent: list[tuple[str, bytes]] = []

    fi.send_test_alert("franca-abc123def456ghi7", post=lambda url, body: sent.append((url, body)))

    assert sent == [("https://ntfy.sh/franca-abc123def456ghi7", b"Franca test alert. Alerts from Franca will arrive here.")]


# --- the Python of the Franca system


@pytest.mark.parametrize("path", [ROOT / "installer" / "linux" / "franca_install.py", ROOT / "infra" / "updater" / "franca_updater.py"])
def test_the_files_run_with_debians_python(path: Path) -> None:
    # The Franca system is Debian 13, whose python3 is 3.13. The updater's image has 3.14, and the installer imports the
    # updater's code, so neither file may use syntax that is new in 3.14.
    ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 13))


def test_programs_are_downloaded_up_to_their_own_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, str]] = []
    monkeypatch.setattr(fi.fu, "http_fetch", lambda url, limit, accept: calls.append((url, limit, accept)) or b"")
    fi.download_program(fi.COSIGN_URL)
    assert calls == [(fi.COSIGN_URL, fi.PROGRAM_MAX_BYTES, "application/octet-stream")]
