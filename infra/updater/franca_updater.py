"""Franca's updater (story E01-007). A new release is installed each night, and the old release is put back if the new
one does not start.

Each run:
1. The latest release is read from GitHub: its version and the digests of its images.
2. A release that is not newer than the installed one is not installed.
3. The signature of each image is checked with cosign. The signature has to come from the release workflow of
   Franca's repository, for this version's tag, through GitHub's OpenID Connect issuer.
4. The images are pulled by digest.
5. The app is stopped and a copy of the database is taken (a snapshot).
6. The references to the new images are written to the bundle's .env file and the services are started. The app
   brings the database up to date (the migrations) when it starts.
7. The app has to answer the health check with the new version number within the time allowed.
8. If anything after step 5 fails, the app is stopped, the snapshot is put back, the old .env is written again and
   the old version is started.

The result is written to the status file whether the update worked or not, for the owner and for the health
monitoring (story E01-010). Between runs, the updater checks every minute that the Docker API answers through the
socket proxy, and reports the result to the health monitoring. It also looks every minute for a request from the
backup's monthly restore test, and starts the app on the restored copy in a one-off container for it (story E01-008).

The updater reaches Docker through a socket proxy (infra/compose.yaml). Calls about containers, images, networks and
volumes are let through. Exec, build, swarm, plugin, secret and system calls are blocked. The updater uses only the
Python standard library, the docker CLI with the compose plugin, and cosign.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

REPOSITORY = "Franca-Language-Learning/Franca"
RELEASE_WORKFLOW_IDENTITY = f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/tags/{{tag}}"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/franca-language-learning/franca-(?P<service>app|caddy|updater|backup|tailscale|status)@sha256:[0-9a-f]{64}$"
)
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
# The .env keys that name each image. A release has to have the app and caddy images; they are started at once. New
# updater and backup images are checked and written to .env too, and are used from the next start of the bundle. New
# tailscale and status images are started after the app is healthy (STARTED_AFTER_THE_APP).
IMAGE_KEYS = {
    "app": "FRANCA_APP_IMAGE",
    "caddy": "FRANCA_CADDY_IMAGE",
    "updater": "FRANCA_UPDATER_IMAGE",
    "backup": "FRANCA_BACKUP_IMAGE",
    "tailscale": "FRANCA_TAILSCALE_IMAGE",
    "status": "FRANCA_STATUS_IMAGE",
}
REQUIRED_IMAGES = frozenset({"app", "caddy"})
# The results that count as a successful run, and the key of the updater's external endpoint in the status container.
SUCCESSFUL_RESULTS = frozenset({"installed", "up-to-date"})
MONITOR_KEY = "nightly_update"
# The key of the socket proxy's external endpoint in the status container, and how often the proxy is checked.
SOCKET_PROXY_KEY = "franca_socket-proxy"
CHECK_EVERY = 60  # seconds
REPORT_EVERY = timedelta(hours=1)
# The services whose new images are started straight after the app is healthy, each with the Compose profile that has
# to be on: the private network (story E01-009), which faces the tailnet, and health monitoring (story E01-010).
STARTED_AFTER_THE_APP = {"tailscale": "tailnet", "status": "monitoring"}
STARTED_AFTER_THE_APP_WAIT = 120  # seconds for such a service to become healthy
# Without a successful run for this long, the state reported to health monitoring is a failure.
STALE_AFTER = timedelta(hours=26)
VERSION_KEY = "FRANCA_VERSION"
SNAPSHOTS_KEPT = 5
PLACEHOLDER_BUNDLE_DIR = "/franca-bundle-not-set"


class UpdateError(Exception):
    """A step failed. The message says which, in words for the status file."""


# --- versions


@dataclass(frozen=True, order=True, slots=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        found = VERSION_PATTERN.match(text.strip())
        if not found:
            raise UpdateError(f"{text!r} is not a release version such as v1.2.3")
        return cls(*(int(part) for part in found.groups()))

    @property
    def tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


# --- releases


@dataclass(frozen=True, slots=True)
class Release:
    version: Version
    images: Mapping[str, str]  # service -> image@sha256:digest


def parse_images(lines: Sequence[str]) -> dict[str, str]:
    """The image list of a release (the digest-*.txt assets): one image@digest per line, for app and caddy."""
    images: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        found = IMAGE_PATTERN.match(line)
        if not found:
            raise UpdateError(f"The release names an unexpected image: {line[:120]}")
        images[found["service"]] = line
    missing = REQUIRED_IMAGES - set(images)
    if missing:
        raise UpdateError(f"The release has no image for {', '.join(sorted(missing))}")
    return images


Fetch = Callable[[str], bytes]


# The pauses, in seconds, before the second and third try of a download. A try is repeated when the connection times out
# or is lost, or when the server answers with a 5xx error. A wrong address, a refusal (4xx) or a certificate that does
# not check out is not tried again.
RETRY_PAUSES = (5.0, 20.0)


def _worth_trying_again(error: OSError) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    if isinstance(error, urllib.error.URLError):
        return isinstance(error.reason, OSError) and not isinstance(error.reason, ssl.SSLCertVerificationError)
    return isinstance(error, (TimeoutError, ConnectionError))


def http_fetch(
    url: str,
    limit: int = 1_000_000,
    accept: str = "application/vnd.github+json",
    pause: Callable[[float], None] = time.sleep,
) -> bytes:
    """The body at an https address. UpdateError is raised for a body larger than the limit. The body is not cut short.
    When the connection times out or is lost, or the server answers with a 5xx error, the download is tried again after
    each pause in RETRY_PAUSES. A body shorter than its Content-Length counts as a lost connection."""
    if not url.startswith("https://"):
        raise UpdateError(f"Only https addresses are read: {url[:120]}")
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "franca-updater"})  # noqa: S310
    for seconds in (*RETRY_PAUSES, None):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the URLs are https and fixed
                body: bytes = response.read(limit + 1)
                expected = response.headers.get("Content-Length")
                if expected is not None and expected.isdigit() and len(body) < min(int(expected), limit + 1):
                    raise ConnectionResetError(f"The connection closed before the whole answer from {url[:120]} had arrived.")
            break
        except OSError as error:
            if seconds is None or not _worth_trying_again(error):
                raise
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            pause(seconds)
    if len(body) > limit:
        raise UpdateError(f"The answer from {url[:120]} is larger than {limit} bytes.")
    return body


@dataclass(slots=True)
class GitHubReleases:
    fetch: Fetch = http_fetch
    repository: str = REPOSITORY

    def latest(self) -> Release:
        try:
            release = json.loads(self.fetch(f"https://api.github.com/repos/{self.repository}/releases/latest"))
            version = Version.parse(str(release["tag_name"]))
            lines: list[str] = []
            for asset in release.get("assets", []):
                if re.fullmatch(r"digest-[a-z]+\.txt", str(asset.get("name", ""))):
                    url = str(asset["browser_download_url"])
                    if not url.startswith(f"https://github.com/{self.repository}/releases/download/"):
                        raise UpdateError(f"An image list is not on the repository's release page: {url[:120]}")
                    lines.extend(self.fetch(url).decode("utf-8").splitlines())
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UpdateError(f"The latest release could not be read from GitHub: {error}") from error
        return Release(version, parse_images(lines))


# --- running commands


Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=900, check=False)  # noqa: S603


def _check(result: subprocess.CompletedProcess[str], what: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        raise UpdateError(f"{what} failed: {detail[0][:300]}")
    return result.stdout


@dataclass(slots=True)
class CosignVerifier:
    """Checks that an image was signed by Franca's release workflow for this version's tag."""

    run: Run = run_command

    def verify(self, image: str, version: Version) -> None:
        _check(
            self.run(
                [
                    "cosign",
                    "verify",
                    image,
                    "--certificate-identity",
                    RELEASE_WORKFLOW_IDENTITY.format(tag=version.tag),
                    "--certificate-oidc-issuer",
                    OIDC_ISSUER,
                    "--output",
                    "json",
                ]
            ),
            f"The signature check of {image}",
        )


class Verifier(Protocol):
    def verify(self, image: str, version: Version) -> None: ...


# --- the bundle: .env, compose and the database


@dataclass(slots=True)
class EnvFile:
    """The bundle's .env file, which names the version and the images that compose starts."""

    path: Path

    def read(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        return values

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""

    def put_back(self, text: str) -> None:
        """Writes the file as it was, word for word, for a rollback."""
        self._replace(text)

    def _replace(self, text: str) -> None:
        temporary = self.path.with_name(self.path.name + ".new")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.path)

    def write(self, values: Mapping[str, str]) -> None:
        """Writes all values, keeping other lines and comments, through a temporary file so a crash leaves the old file."""
        remaining = dict(values)
        lines: list[str] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
                if key in remaining:
                    lines.append(f"{key}={remaining.pop(key)}")
                elif key is None or key not in values:
                    lines.append(line)
        lines.extend(f"{key}={value}" for key, value in remaining.items())
        self._replace("\n".join(lines) + "\n")


@dataclass(slots=True)
class Compose:
    """docker compose for the bundle in project_dir."""

    project_dir: Path
    run: Run = run_command
    project_name: str | None = None

    def _compose(self, *arguments: str) -> list[str]:
        command = ["docker", "compose", "--project-directory", str(self.project_dir)]
        if self.project_name:
            command += ["--project-name", self.project_name]
        return command + list(arguments)

    def pull(self, image: str) -> None:
        _check(self.run(["docker", "pull", "--quiet", image]), f"Pulling {image}")

    def stop(self, *services: str) -> None:
        _check(self.run(self._compose("stop", *services)), "Stopping " + ", ".join(services))

    def up(self, *services: str, wait: int | None = None) -> None:
        """Starts the services. With wait, Compose waits up to that many seconds until they are healthy."""
        waiting = ["--wait", "--wait-timeout", str(wait)] if wait else []
        _check(self.run(self._compose("up", "--detach", "--no-build", "--no-deps", *waiting, *services)), "Starting " + ", ".join(services))

    def run_in_app(self, script: str) -> None:
        """Runs Python in a one-off container of the app image, with the database volume, while the app is stopped."""
        _check(self.run(self._compose("run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script)), "The database step")

    def run_restore_check(self, script: str) -> None:
        """Runs Python in a one-off container of the app image on the restored copy in the restore-test volume, with no
        network (the restore-check service)."""
        command = self._compose("run", "--rm", "--no-deps", "--entrypoint", "python", "restore-check", "-c", script)
        _check(self.run(command), "Starting the app on the restored copy")


# Run in a one-off app container while the app is stopped. The snapshot needs twice the database's size free, so a full
# disk is found before anything changes; a snapshot left half written is removed.
SNAPSHOT_SCRIPT = """
import pathlib, shutil, sqlite3, sys
source, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
needed = 2 * sum(p.stat().st_size for p in source.parent.glob(source.name + '*'))
if shutil.disk_usage(target.parent).free < needed:
    sys.exit(f'Not enough free disk space for a snapshot: {{needed}} bytes needed')
try:
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)
except BaseException:
    target.unlink(missing_ok=True)
    raise
snapshots = sorted(target.parent.glob('franca-*.db'))
for old in snapshots[:-{kept}]:
    old.unlink()
"""

# The snapshot is copied beside the database and then put in its place in one step, so a crash or a full disk during
# the copy leaves the database as it was.
RESTORE_SCRIPT = """
import os, pathlib, shutil, sys
snapshot, live = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
incoming = live.with_name(live.name + '.restore')
shutil.copyfile(snapshot, incoming)
with open(incoming, 'rb') as copied:
    os.fsync(copied.fileno())
os.replace(incoming, live)
for extra in (live.with_name(live.name + '-wal'), live.with_name(live.name + '-shm')):
    extra.unlink(missing_ok=True)
"""


@dataclass(slots=True)
class Database:
    """Snapshots of the app's SQLite database, taken and put back through the app image while the app is stopped."""

    compose: Compose
    live_path: str = "/data/franca.db"
    snapshot_dir: str = "/data/snapshots"

    def snapshot(self, label: str) -> str:
        target = f"{self.snapshot_dir}/franca-{label}.db"
        self.compose.run_in_app(_with_arguments(SNAPSHOT_SCRIPT.format(kept=SNAPSHOTS_KEPT), self.live_path, target))
        return target

    def restore(self, snapshot: str) -> None:
        self.compose.run_in_app(_with_arguments(RESTORE_SCRIPT, snapshot, self.live_path))


def _with_arguments(script: str, *arguments: str) -> str:
    return f"import sys; sys.argv = {['-c', *arguments]!r}\n{script}"


# Run in the restore-check container, for the backup's monthly restore test. The migrations are run on the restored
# copy, the app is started on the container's loopback address and its health check is called, as the app's own
# container does at start. The answer is written beside the copy, with the id of the backup's request, whatever
# happens; an app that does not stop is killed first.
RESTORE_CHECK_SCRIPT = """
import json, os, pathlib, secrets, subprocess, sys, tempfile, time, urllib.request
folder, port = pathlib.Path(sys.argv[1]), int(sys.argv[2])
answer = {'id': None, 'passed': False}
server = None
try:
    answer['id'] = json.loads((folder / 'request.json').read_text(encoding='utf-8'))['id']
    os.environ['FRANCA_DATABASE_PATH'] = str(folder / 'franca.db')
    # The app needs a session secret to start. A throwaway one is used, so the real one is not given to this container.
    secret_file = pathlib.Path(tempfile.gettempdir()) / 'session_secret'
    secret_file.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    os.environ['FRANCA_SESSION_SECRET_FILE'] = str(secret_file)
    if not (folder / 'franca.db').is_file():
        raise RuntimeError('There is no restored copy of the database')
    migrated = subprocess.run([sys.executable, '-m', 'franca.platform.migrate'], capture_output=True, text=True, timeout=300)
    if migrated.returncode != 0:
        lines = (migrated.stderr or migrated.stdout).strip().splitlines() or ['no output']
        raise RuntimeError('The migrations failed on the restored copy: ' + lines[-1][:300])
    serve = f"import uvicorn; from franca.api import create_app; uvicorn.run(create_app, factory=True, host='127.0.0.1', port={port})"
    server = subprocess.Popen([sys.executable, '-c', serve], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while True:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=5) as response:
                health = json.loads(response.read(10000))
            break
        except OSError:
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('The app did not answer /api/v1/health on the restored copy') from None
            time.sleep(1)
    if health.get('status') != 'ok':
        raise RuntimeError(f'The health check on the restored copy answered {health}')
    answer.update(passed=True, version=str(health.get('version', '')), message='The app started on the restored copy')
except Exception as error:
    answer['message'] = str(error)[:500]
finally:
    if server is not None:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    written = folder / 'answer.json.new'
    written.write_text(json.dumps(answer), encoding='utf-8')
    os.replace(written, folder / 'answer.json')
"""


def restore_check_script(folder: str = "/data", port: int = 8000) -> str:
    """The script for the restore-check container, for the copy in folder, with the app on the given port."""
    return _with_arguments(RESTORE_CHECK_SCRIPT, folder, str(port))


# --- health


Probe = Callable[[], str | None]


def health_probe(url: str) -> Probe:
    """Returns the version that the health endpoint reports, or None when it does not answer."""

    def probe() -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a fixed address inside the bundle
                answer = json.loads(response.read(10_000))
                return str(answer.get("version")) if answer.get("status") == "ok" else None
        except (OSError, ValueError):
            return None

    return probe


def _same_version(answer: str | None, version: str) -> bool:
    """The release images report their tag (v1.2.3); .env and the status file use 1.2.3."""
    return answer is not None and answer.removeprefix("v") == version.removeprefix("v")


def wait_for_version(probe: Probe, version: str, timeout: float, sleep: Callable[[float], None] = time.sleep) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if _same_version(probe(), version):
            return
        if time.monotonic() >= deadline:
            raise UpdateError(f"Version {version} did not answer the health check within {int(timeout)} seconds")
        sleep(2)


DockerApiProbe = Callable[[], str | None]


def docker_api_probe(docker_host: str) -> DockerApiProbe:
    """Returns a check of the Docker API through the socket proxy at docker_host (tcp://host:port, as in DOCKER_HOST).
    The check returns None when the proxy answers /_ping with OK, which it does only when it can reach Docker, and
    otherwise the reason."""
    url = "http://" + docker_host.removeprefix("tcp://").rstrip("/") + "/_ping"

    def probe() -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a fixed address inside the bundle
                answer = response.read(100)
        except (OSError, http.client.HTTPException, ValueError) as error:
            return f"The socket proxy does not answer as expected: {error!r}"
        if answer.strip() != b"OK":
            return f"The socket proxy gave an unexpected answer to /_ping: {answer[:60]!r}"
        return None

    return probe


# --- status


@dataclass(slots=True)
class StatusFile:
    path: Path

    def write(self, **status: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".new")
        temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def read(self) -> dict[str, str]:
        """The last status written, or an empty dict when there is none or it cannot be read."""
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(name): str(value) for name, value in loaded.items()} if isinstance(loaded, dict) else {}


@dataclass(slots=True)
class HighWaterMark:
    """The newest version ever installed. It only goes up, so a damaged or edited .env cannot make an older release
    look newer than the installed one."""

    path: Path

    def read(self) -> Version | None:
        try:
            return Version.parse(self.path.read_text(encoding="utf-8"))
        except (OSError, UpdateError):
            return None

    def raise_to(self, version: Version) -> None:
        current = self.read()
        if current is None or version > current:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".new")
            temporary.write_text(f"{version}\n", encoding="utf-8")
            os.replace(temporary, self.path)


def check_bundle(folder: Path) -> None:
    """The updater works on the bundle folder. A missing or wrong folder is found here, before anything changes."""
    if str(folder) == PLACEHOLDER_BUNDLE_DIR or not (folder / "compose.yaml").is_file() or not (folder / ".env").is_file():
        raise UpdateError(f"The bundle folder {folder} has no compose.yaml and .env; FRANCA_BUNDLE_DIR in .env names the wrong folder")
    if not os.access(folder, os.W_OK):
        raise UpdateError(f"The updater cannot write to the bundle folder {folder}")


# --- reports to health monitoring (story E01-010)


def _post(request: urllib.request.Request) -> None:
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310 - a fixed address inside the bundle
        pass


@dataclass(slots=True)
class Monitor:
    """Reports the result of each run to an external endpoint in Gatus (the status container). An alert is sent when a
    run fails or no report arrives within 25 hours."""

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
            query = urllib.parse.urlencode(fields)
            request = urllib.request.Request(  # noqa: S310 - a fixed address inside the bundle
                f"{self.url.rstrip('/')}/api/v1/endpoints/{key}/external?{query}",
                method="POST",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.send(request)
        except Exception as error:  # noqa: BLE001 - the updater goes on when a report cannot be sent
            print(json.dumps({"result": "report-not-sent", "message": str(error)}), flush=True)


# --- one run


@dataclass(slots=True)
class Updater:
    releases: GitHubReleases
    verifier: Verifier
    env: EnvFile
    compose: Compose
    database: Database
    probe: Probe
    status: StatusFile
    high_water: HighWaterMark | None = None
    bundle: Path | None = None
    health_timeout: float = 180
    sleep: Callable[[float], None] = field(default=time.sleep)
    monitor: Monitor | None = None
    docker_api: DockerApiProbe | None = None
    # The folder shared with the backup for the app check in its monthly restore test, and the last request tried.
    restore_test_dir: Path | None = None
    restore_check_tried: str | None = None

    def run_once(self, now: datetime) -> str:
        """Checks for a release and installs it, then reports the state to health monitoring. Returns the result, which
        is also written to the status file."""
        result = self._run(now)
        self.report_state(now)
        return result

    def _run(self, now: datetime) -> str:
        """Checks for a release and installs it. Returns the result, which is also written to the status file.

        Every error after the app is stopped leads to the old version being started again, whatever kind of error it
        is, so the app is not left stopped."""
        checked = now.astimezone(UTC).isoformat(timespec="seconds")
        try:
            if self.bundle is not None:
                check_bundle(self.bundle)
            old_text = self.env.text()
            old = self.env.read()
        except (UpdateError, OSError) as error:
            return self._report("misconfigured", checked, "unknown", None, str(error))
        old_version = old.get(VERSION_KEY, "")
        # A development build (such as 0.1.0-dev) counts as older than any release.
        installed = Version.parse(old_version) if VERSION_PATTERN.match(old_version) else Version(0, 0, 0)
        newest_ever = max(installed, (self.high_water.read() if self.high_water else None) or installed)
        try:
            release = self.releases.latest()
        except Exception as error:  # noqa: BLE001 - any failure to read the release changes nothing
            return self._report("check-failed", checked, old_version, None, str(error))
        if release.version <= newest_ever:
            return self._report("up-to-date", checked, old_version, release.version, "No newer release")
        try:
            for image in release.images.values():
                self.verifier.verify(image, release.version)
            for image in release.images.values():
                self.compose.pull(image)
        except Exception as error:  # noqa: BLE001 - nothing has been stopped yet
            return self._report("not-installed", checked, old_version, release.version, str(error))

        try:
            self.compose.stop("app")
            snapshot = self.database.snapshot(f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-before-{release.version}")
        except Exception as error:  # noqa: BLE001 - see the docstring
            return self._restart_unchanged(checked, old_version, release.version, str(error))
        try:
            new = dict(old) | {VERSION_KEY: str(release.version)} | {IMAGE_KEYS[s]: image for s, image in release.images.items()}
            self.env.write(new)
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, str(release.version), self.health_timeout, self.sleep)
        except Exception as error:  # noqa: BLE001 - see the docstring
            return self._roll_back(checked, old_version, release.version, old_text, snapshot, str(error))
        if self.high_water is not None:
            self.high_water.raise_to(release.version)
        message = f"Installed {release.version}; snapshot {snapshot}" + self._start_new_images(old, new)
        return self._report("installed", checked, str(release.version), release.version, message)

    def _start_new_images(self, old: dict[str, str], new: dict[str, str]) -> str:
        """Start the new tailscale and status images once the app is healthy, for the profiles that are on.

        The tailscale container faces the tailnet, so its update is not left for the next start of the bundle. If a
        new image does not start, the old one is put back and started. Returns notes for the status message, or an
        empty string."""
        profiles = {profile.strip() for profile in old.get("COMPOSE_PROFILES", "").split(",")}
        notes = ""
        for service, profile in STARTED_AFTER_THE_APP.items():
            key = IMAGE_KEYS[service]
            if profile in profiles and old.get(key) != new.get(key):
                notes += self._start_new_image(service, key, old, new)
        return notes

    def _start_new_image(self, service: str, key: str, old: dict[str, str], new: dict[str, str]) -> str:
        try:
            self.compose.up(service, wait=STARTED_AFTER_THE_APP_WAIT)
        except Exception as error:  # noqa: BLE001 - the app update is kept and the old image is put back
            current = self.env.read()
            put_back = {name: value for name, value in current.items() if name != key} | ({key: old[key]} if key in old else {})
            try:
                self.env.write(put_back)
                self.compose.up(service, wait=STARTED_AFTER_THE_APP_WAIT)
            except Exception as again:  # noqa: BLE001 - reported for the owner
                return f". The new {service} image did not start ({error}), and starting the old one failed too: {again}"
            return f". The new {service} image did not start ({error}), so the old one was started again"
        return ""

    def _restart_unchanged(self, checked: str, old_version: str, failed: Version, reason: str) -> str:
        """Nothing was changed yet; the installed version is started again."""
        try:
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, old_version, self.health_timeout, self.sleep)
        except Exception as error:  # noqa: BLE001 - reported for the owner
            return self._report(
                "rollback-failed", checked, old_version, failed, f"{reason}. Starting {old_version} again failed too: {error}"
            )
        return self._report("not-installed", checked, old_version, failed, reason)

    def _roll_back(self, checked: str, old_version: str, failed: Version, old_text: str, snapshot: str, reason: str) -> str:
        try:
            self.compose.stop("app")
            self.env.put_back(old_text)
            self.database.restore(snapshot)
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, old_version, self.health_timeout, self.sleep)
        except Exception as error:  # noqa: BLE001 - reported for the owner
            return self._report(
                "rollback-failed", checked, old_version, failed, f"{reason}. Going back to {old_version} failed too: {error}"
            )
        return self._report("rolled-back", checked, old_version, failed, f"{reason}. Version {old_version} and its database were put back")

    def _report(self, result: str, checked: str, installed: str, latest: Version | None, message: str) -> str:
        last_success = checked if result in SUCCESSFUL_RESULTS else self.status.read().get("lastSucceededAt", "")
        line = {"result": result, "checkedAt": checked, "installed": installed, "latest": str(latest or ""), "message": message}
        line["lastSucceededAt"] = last_success
        print(json.dumps(line), flush=True)
        try:
            self.status.write(**line)
        except OSError as error:
            print(json.dumps({"result": "status-not-written", "message": str(error)}), flush=True)
        return result

    def report_state(self, now: datetime) -> None:
        """Reports the updater's state to health monitoring: good while the last run succeeded and the last success is
        less than 26 hours old. It is reported after each run and every hour. Gatus forgets the time of the last report
        when the status container restarts, so without these reports a missed run would not be noticed."""
        if self.monitor is None:
            return
        state = self.status.read()
        if not state:
            self.monitor.report(MONITOR_KEY, True, "No update has run yet")
            return
        if state.get("result") not in SUCCESSFUL_RESULTS:
            self.monitor.report(MONITOR_KEY, False, state.get("message", "The last update failed"))
            return
        last_success = state.get("lastSucceededAt", "")
        try:
            stale = now - datetime.fromisoformat(last_success) > STALE_AFTER
        except ValueError:
            stale = True
        message = f"No successful update since {last_success or 'the start'}" if stale else state.get("message", "")
        self.monitor.report(MONITOR_KEY, not stale, message)

    def report_docker_api(self) -> None:
        """Reports to health monitoring whether the Docker API answers through the socket proxy. The status container
        is not on the proxy's network, so it cannot check the proxy itself."""
        if self.monitor is None or self.docker_api is None:
            return
        problem = self.docker_api()
        self.monitor.report(SOCKET_PROXY_KEY, problem is None, problem or "The Docker API answers through the socket proxy")

    def check_restored_copy(self) -> None:
        """Starts the app on the backup's restored copy in a one-off container, when the backup has asked for it and
        there is no answer yet. Only an id in the form the backup makes is taken, and each request is tried once. When
        the container cannot be started, a failure answer with the reason is written for the backup."""
        if self.restore_test_dir is None:
            return
        request = _read_json(self.restore_test_dir / "request.json").get("id")
        if not isinstance(request, str) or not REQUEST_ID_PATTERN.fullmatch(request) or request == self.restore_check_tried:
            return
        if _read_json(self.restore_test_dir / "answer.json").get("id") == request:
            return
        self.restore_check_tried = request
        try:
            self.compose.run_restore_check(restore_check_script())
        except (UpdateError, subprocess.SubprocessError) as error:
            reason = f"it did not finish within {error.timeout:.0f} seconds" if isinstance(error, subprocess.TimeoutExpired) else str(error)
            print(json.dumps({"result": "restore-check-not-run", "message": reason}), flush=True)
            self._answer_failure(request, f"The updater could not run the restore-check container: {reason}")

    def _answer_failure(self, request: str, message: str) -> None:
        """Writes a failure answer for the backup. The updater writes in the folder through its group (infra/compose.yaml)."""
        assert self.restore_test_dir is not None  # noqa: S101 - checked by the caller
        answer = {"id": request, "passed": False, "message": message[:500]}
        try:
            written = self.restore_test_dir / "answer.json.new"
            written.write_text(json.dumps(answer), encoding="utf-8")
            os.replace(written, self.restore_test_dir / "answer.json")
        except OSError as error:
            print(json.dumps({"result": "restore-check-answer-not-written", "message": str(error)}), flush=True)


# The ids that the backup writes in its requests (franca_backup.Backup.check_app_on), and the most a request file may
# hold. Anything else in the shared folder is ignored.
REQUEST_ID_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00-[0-9a-f]{8}")
REQUEST_LIMIT = 1000  # bytes


def _read_json(path: Path, limit: int = REQUEST_LIMIT) -> dict[str, object]:
    """A JSON object from a file of up to `limit` bytes, or an empty dict when the file is missing, half written, too
    long or not an object."""
    try:
        with path.open("rb") as file:
            text = file.read(limit + 1)
        loaded = json.loads(text) if len(text) <= limit else None
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# --- the service


DEFAULT_UPDATE_TIME = "02:30"


def update_time(text: str) -> str:
    """The time of day for updates, HH:MM in UTC. A time that cannot be read is replaced by 02:30, with a message."""
    found = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text.strip())
    if found:
        return text.strip()
    print(
        json.dumps({"result": "warning", "message": f"FRANCA_UPDATE_AT_UTC={text!r} is not HH:MM; using {DEFAULT_UPDATE_TIME}"}), flush=True
    )
    return DEFAULT_UPDATE_TIME


def next_run(now: datetime, at: str) -> datetime:
    """The next time of day `at` (HH:MM, UTC) after now."""
    hour, minute = (int(part) for part in at.split(":"))
    candidate = now.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _step(name: str, action: Callable[[], object]) -> None:
    """Runs one part of the loop. An error is printed with the part's name, and the loop goes on."""
    try:
        action()
    except Exception as error:  # noqa: BLE001 - the other parts of the loop still run
        print(json.dumps({"result": "error", "step": name, "message": repr(error)}), flush=True)


@dataclass(slots=True)
class Service:
    """The updater's loop. tick is called every minute (CHECK_EVERY). Each time, the socket proxy is checked and a
    request from the backup's restore test is looked for. The update is run at the time of day `at`. The state is
    reported to health monitoring after each run and every hour (see Updater.report_state). Each part runs on its own:
    an error in one part is printed, and the other parts still run."""

    updater: Updater
    at: str
    wake: datetime
    report_after: datetime = datetime.min.replace(tzinfo=UTC)

    def tick(self, now: datetime) -> None:
        _step("socket proxy check", self.updater.report_docker_api)
        _step("restore check", self.updater.check_restored_copy)
        if now >= self.wake:
            self.wake = next_run(now, self.at)
            self.report_after = now + REPORT_EVERY
            _step("nightly update", lambda: self.updater.run_once(now))
        elif now >= self.report_after:
            self.report_after = now + REPORT_EVERY
            _step("state report", lambda: self.updater.report_state(now))

    def seconds_to_sleep(self, now: datetime) -> float:
        return max(1.0, min(float(CHECK_EVERY), (self.wake - now).total_seconds()))


def from_environment(environ: Mapping[str, str]) -> Updater:
    project = Path(environ.get("FRANCA_BUNDLE_DIR", "/bundle"))
    compose = Compose(project, project_name=environ.get("COMPOSE_PROJECT_NAME") or None)
    return Updater(
        releases=GitHubReleases(),
        verifier=CosignVerifier(),
        env=EnvFile(project / ".env"),
        compose=compose,
        database=Database(compose),
        probe=health_probe(environ.get("FRANCA_HEALTH_URL", "http://app:8000/api/v1/health")),
        status=StatusFile(Path(environ.get("FRANCA_UPDATER_STATUS", "/status/updater.json"))),
        high_water=HighWaterMark(Path(environ.get("FRANCA_UPDATER_HIGH_WATER", "/status/newest-installed"))),
        bundle=project,
        monitor=Monitor(environ["FRANCA_STATUS_URL"], Path("/run/secrets/status_push_token")) if environ.get("FRANCA_STATUS_URL") else None,
        docker_api=docker_api_probe(environ["DOCKER_HOST"]) if environ.get("DOCKER_HOST", "").startswith("tcp://") else None,
        restore_test_dir=Path(environ.get("FRANCA_RESTORE_TEST_DIR", "/restore-test")),
    )


def main(argv: Sequence[str] = sys.argv[1:], environ: Mapping[str, str] = os.environ) -> int:
    updater = from_environment(environ)
    if "--once" in argv:
        result = updater.run_once(datetime.now(UTC))
        return 0 if result in SUCCESSFUL_RESULTS else 1
    at = update_time(environ.get("FRANCA_UPDATE_AT_UTC", DEFAULT_UPDATE_TIME))
    service = Service(updater, at, wake=next_run(datetime.now(UTC), at))
    while True:
        try:
            service.tick(datetime.now(UTC))
        except Exception as error:  # noqa: BLE001 - the updater keeps running and tries again the next night
            print(json.dumps({"result": "error", "message": repr(error)}), flush=True)
        time.sleep(service.seconds_to_sleep(datetime.now(UTC)))


if __name__ == "__main__":
    sys.exit(main())
