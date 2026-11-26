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
