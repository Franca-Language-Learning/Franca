"""The Linux part of Franca's installer (story E01-011). It runs as root inside the Franca WSL distribution, started by
Install-Franca.ps1 on Windows, and can be run again: secrets that were made before are kept.

The steps:
1. Docker Engine and its compose plugin are installed from Docker's own package source, if they are not there yet.
2. cosign is downloaded and checked against its published checksum.
3. The latest release is read from GitHub, and the signature of each image is checked with cosign, as the updater
   does each night (franca_updater.py, which is installed beside this file).
4. The secrets are written: the answers from the owner, and a backup password, an ntfy topic, a push token and a
   session secret, which are made here. The backup password and the topic are shown once.
5. compose.yaml and .env are written to the bundle folder, and the disk marker to the backup folder.
6. The tailscale container is started first. When it has joined the tailnet, the PC's Tailscale name is read and
   written to .env, the auth key file is emptied, and the rest of the bundle is started.
7. A test alert is sent to the ntfy topic.

The answers come as JSON on standard input, so that no secret appears in a command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import franca_updater as fu

BUNDLE_DIR = Path("/opt/franca")
COSIGN = Path("/usr/local/bin/cosign")
COSIGN_URL = "https://github.com/sigstore/cosign/releases/download/v3.1.4/cosign-linux-amd64"
COSIGN_SHA256 = "424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa"
# Docker's signing key for its Debian packages, checked by fingerprint before it is trusted.
DOCKER_KEY_URL = "https://download.docker.com/linux/debian/gpg"
DOCKER_KEY_FINGERPRINT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
PROFILES = "updates,backups,tailnet,monitoring"
BACKUP_UID = 10001  # the app's user, which the backup container runs as
DISK_MARKER = ".franca-backup-disk"
NTFY_URL = "https://ntfy.sh"
# The same patterns as the status container's start script (infra/status/entrypoint.sh).
TOPIC_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}")

Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Fetch = Callable[[str], bytes]


class InstallError(Exception):
    """A step that failed, with a message for the owner."""


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=1800, check=False)  # noqa: S603


def _check(result: subprocess.CompletedProcess[str], what: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        raise InstallError(f"{what} failed: {detail[0][:300]}")
    return result.stdout


# --- the answers


@dataclass(frozen=True, slots=True)
class Answers:
    """The owner's answers. The secret ones are left out of repr, so they do not reach a log by mistake."""

    owner_email: str
    google_client_id: str
    google_client_secret: str = field(repr=False)
    tailscale_authkey: str = field(repr=False)
    backup_dir: Path
    tailscale_hostname: str = "franca"

    @classmethod
    def from_json(cls, text: str) -> Answers:
        try:
            given = json.loads(text)
            made = cls(
                owner_email=str(given["owner_email"]).strip(),
                google_client_id=str(given["google_client_id"]).strip(),
                google_client_secret=str(given["google_client_secret"]).strip(),
                tailscale_authkey=str(given["tailscale_authkey"]).strip(),
                backup_dir=Path(str(given["backup_dir"]).strip()),
                tailscale_hostname=str(given.get("tailscale_hostname", "franca")).strip(),
            )
        except (ValueError, KeyError, TypeError) as error:
            raise InstallError(f"The answers could not be read: {error}") from error
        made.check()
        return made

    def check(self) -> None:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.owner_email):
            raise InstallError("The e-mail address is not valid. Check it for typing errors.")
        if not re.fullmatch(r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", self.google_client_id):
            raise InstallError("The Google client ID has to end in .apps.googleusercontent.com.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", self.google_client_secret):
            raise InstallError("The Google client secret has unexpected characters. Copy it again from the Google console.")
        # Headscale, a self-hosted control server that the rehearsal uses, gives keys that start with hskey-auth-.
        if not re.fullmatch(r"(?:tskey|hskey)-auth-[A-Za-z0-9_-]{4,200}", self.tailscale_authkey):
            raise InstallError("The Tailscale auth key has to start with tskey-auth-.")
        if not self.backup_dir.is_absolute():
            raise InstallError("The backup folder has to be a full path, such as /mnt/j/franca-backups.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.tailscale_hostname):
            raise InstallError("The Tailscale machine name can have lowercase letters, digits and hyphens only.")


# --- secrets


def _random_text(length: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _write_private(path: Path, value: str) -> None:
    """Writes a secret file. Only root can open the folder. The file is readable by all users, because Docker gives it to containers
    with the file's own permissions and each container reads it as its own user."""
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(value, encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, path)


def write_secrets(folder: Path, answers: Answers) -> dict[str, str]:
    """Writes the secret files. The generated ones are kept when they exist. Returns the generated values that the
    owner has to keep (the backup password and the ntfy topic), when they were made in this run."""
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    _write_private(folder / "google_client_secret", answers.google_client_secret)
    _write_private(folder / "tailscale_authkey", answers.tailscale_authkey)
    generated: dict[str, Callable[[], str]] = {
        "session_secret": lambda: secrets.token_urlsafe(48),
        "backup_password": lambda: secrets.token_urlsafe(32),
        "ntfy_topic": lambda: "franca-" + _random_text(20),
        "status_push_token": lambda: secrets.token_urlsafe(48),
    }
    shown: dict[str, str] = {}
    for name, make in generated.items():
        path = folder / name
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            continue
        value = make()
        _write_private(path, value)
        if name in {"backup_password", "ntfy_topic"}:
            shown[name] = value
    return shown


# --- the bundle's files


def write_env(bundle: Path, release: fu.Release, answers: Answers, tailscale_name: str | None) -> None:
    values = {
        "COMPOSE_PROJECT_NAME": "franca",
        "COMPOSE_PROFILES": PROFILES,
        fu.VERSION_KEY: str(release.version),
        "FRANCA_BUNDLE_DIR": str(bundle),
        "FRANCA_SECRETS_DIR": str(bundle / "secrets"),
        "FRANCA_BACKUP_DIR": str(answers.backup_dir),
        "FRANCA_OWNER_EMAIL": answers.owner_email,
        "FRANCA_GOOGLE_CLIENT_ID": answers.google_client_id,
    } | {fu.IMAGE_KEYS[service]: image for service, image in release.images.items()}
    if tailscale_name:
        values |= {"FRANCA_TAILSCALE_NAME": tailscale_name, "FRANCA_PUBLIC_URL": f"https://{tailscale_name}"}
    fu.EnvFile(bundle / ".env").write(values)


def prepare_backup_folder(folder: Path, chown: Callable[[Path, int, int], None] = os.chown) -> None:
    """Makes the backup folder on the backup disk, owned by the backup container's user, with the disk marker that
    is checked before each backup."""
    if not folder.parent.is_dir():
        raise InstallError(f"The backup disk was not found ({folder.parent} does not exist). Check that the disk is connected.")
    folder.mkdir(exist_ok=True)
    marker = folder / DISK_MARKER
    if not marker.exists():
        marker.write_text("Franca backups. Leave this file here: without it, no backup is made on this disk.\n", encoding="utf-8")
    chown(folder, BACKUP_UID, BACKUP_UID)
    chown(marker, BACKUP_UID, BACKUP_UID)


# --- programs


def install_cosign(target: Path, fetch: Fetch = fu.http_fetch, sha256: str = COSIGN_SHA256) -> None:
    """Downloads cosign and keeps it only when its checksum is the published one."""
    data = fetch(COSIGN_URL)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise InstallError("The downloaded cosign does not have the published checksum, so it was not installed.")
    temporary = target.with_name(target.name + ".new")
    temporary.write_bytes(data)
    temporary.chmod(0o755)
    os.replace(temporary, target)


def ensure_docker(run: Run = run_command) -> None:
    """Installs Docker Engine and the compose plugin from Docker's package source, unless they work already."""
    if run(["docker", "compose", "version"]).returncode == 0:
        return
    _check(run(["apt-get", "update"]), "Reading the package lists")
    _check(run(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg"]), "Installing curl and gnupg")
    keyring = "/etc/apt/keyrings/docker.asc"
    _check(run(["install", "-m", "0755", "-d", "/etc/apt/keyrings"]), "Making the keyring folder")
    _check(run(["curl", "-fsSL", DOCKER_KEY_URL, "-o", keyring]), "Downloading Docker's signing key")
    shown = _check(run(["gpg", "--show-keys", "--with-colons", keyring]), "Reading Docker's signing key")
    fingerprints = {line.split(":")[9] for line in shown.splitlines() if line.startswith("fpr:")}
    if DOCKER_KEY_FINGERPRINT not in fingerprints:
        Path(keyring).unlink(missing_ok=True)
        raise InstallError("Docker's signing key does not have the expected fingerprint, so Docker was not installed.")
    codename = _check(run(["sh", "-c", ". /etc/os-release && echo $VERSION_CODENAME"]), "Reading the Debian version").strip()
    source = f"deb [arch=amd64 signed-by={keyring}] https://download.docker.com/linux/debian {codename} stable\n"
    Path("/etc/apt/sources.list.d/docker.list").write_text(source, encoding="utf-8")
    _check(run(["apt-get", "update"]), "Reading Docker's package list")
    _check(
        run(["apt-get", "install", "-y", "docker-ce", "docker-ce-cli", "containerd.io", "docker-compose-plugin"]),
        "Installing Docker Engine",
    )
    _check(run(["systemctl", "enable", "--now", "docker"]), "Starting Docker")


def verified_release(releases: fu.GitHubReleases, verifier: fu.Verifier) -> fu.Release:
    release = releases.latest()
    for image in release.images.values():
        verifier.verify(image, release.version)
    return release


# --- starting the bundle


def _compose(bundle: Path, *arguments: str) -> list[str]:
    return ["docker", "compose", "--project-directory", str(bundle), *arguments]


def tailscale_name(bundle: Path, run: Run) -> str:
    status = json.loads(
        _check(run(_compose(bundle, "exec", "-T", "tailscale", "tailscale", "status", "--json")), "Reading the Tailscale status")
    )
    name = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not name:
        raise InstallError(
            "The PC has no Tailscale name. Check that MagicDNS is on in the Tailscale admin console (docs/private-network.md)."
        )
    return name


def start_bundle(bundle: Path, release: fu.Release, answers: Answers, run: Run = run_command) -> str:
    """Starts tailscale, writes the PC's Tailscale name, empties the used auth key and starts the rest. Returns the
    Tailscale name."""
    # A release names its images by digest, and they are downloaded. In the rehearsal the images are on the PC already.
    for image in release.images.values():
        if "@sha256:" in image:
            _check(run(["docker", "pull", "--quiet", image]), f"Downloading {image.split('/')[-1][:40]}")
    _check(run(_compose(bundle, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180", "tailscale")), "Joining the tailnet")
    name = tailscale_name(bundle, run)
    write_env(bundle, release, answers, tailscale_name=name)
    _write_private(bundle / "secrets" / "tailscale_authkey", "")
    _check(run(_compose(bundle, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "300")), "Starting Franca")
    return name


def _post(url: str, body: bytes) -> None:
    request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 - a fixed https address
    with urllib.request.urlopen(request, timeout=30):  # noqa: S310 - a fixed https address
        pass


def send_test_alert(topic: str, post: Callable[[str, bytes], None] = _post, url: str = NTFY_URL) -> None:
    post(f"{url}/{topic}", b"Franca test alert. Alerts from Franca will arrive here.")


# --- the whole installation


def install(
    answers: Answers,
    bundle: Path,
    release: fu.Release,
    compose_file: Path,
    run: Run = run_command,
    post: Callable[[str, bytes], None] = _post,
    ntfy_url: str = NTFY_URL,
) -> dict[str, str]:
    """Writes the bundle and starts it. Returns what the owner is shown at the end."""
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(compose_file, bundle / "compose.yaml")
    shown = write_secrets(bundle / "secrets", answers)
    prepare_backup_folder(answers.backup_dir)
    write_env(bundle, release, answers, tailscale_name=None)
    # The updater (user 10003) writes .env when it installs a release.
    os.chown(bundle, 10003, 10003)
    os.chown(bundle / ".env", 10003, 10003)
    name = start_bundle(bundle, release, answers, run)
    topic = (bundle / "secrets" / "ntfy_topic").read_text(encoding="utf-8")
    send_test_alert(topic, post, ntfy_url)
    return {"address": f"https://{name}", **shown}


def release_from_file(path: Path) -> fu.Release:
    """A release named in a local file, for the rehearsal: {"version": "1.0.0", "images": {"app": "...", ...}}."""
    given = json.loads(path.read_text(encoding="utf-8"))
    images: Mapping[str, str] = given["images"]
    return fu.Release(fu.Version.parse(given["version"]), dict(images))


def main(argv: Sequence[str] = sys.argv[1:]) -> int:
    parser = argparse.ArgumentParser(
        description="Installs Franca inside the Franca WSL distribution. Answers come as JSON on standard input."
    )
    parser.add_argument("--bundle-dir", type=Path, default=BUNDLE_DIR)
    parser.add_argument("--compose-file", type=Path, default=Path(__file__).with_name("compose.yaml"))
    parser.add_argument("--release-file", type=Path, help="for the rehearsal: local images, with no download and no signature check")
    parser.add_argument("--skip-docker", action="store_true", help="for the rehearsal: Docker is there already")
    parser.add_argument("--ntfy-url", default=NTFY_URL, help="for the rehearsal: a stand-in for ntfy.sh")
    options = parser.parse_args(argv)
    try:
        answers = Answers.from_json(sys.stdin.read())
        if not options.skip_docker:
            ensure_docker()
        if options.release_file:
            release = release_from_file(options.release_file)
        else:
            install_cosign(COSIGN)
            release = verified_release(fu.GitHubReleases(), fu.CosignVerifier())
        shown = install(answers, options.bundle_dir, release, options.compose_file, ntfy_url=options.ntfy_url)
    except (InstallError, fu.UpdateError, OSError) as error:
        print(f"The installation stopped: {error}", file=sys.stderr)
        return 1
    print(json.dumps(shown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
