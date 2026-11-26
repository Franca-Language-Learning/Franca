"""Franca's updater (story E01-007): it installs a new release each night and goes back to the old one if the new one
does not start.

Each run:
1. The latest release is read from GitHub: its version and the digests of its images.
2. A release that is not newer than the installed one is not installed.
3. The signature of each image is checked with cosign. The signature has to come from the release workflow of
   Franca's repository, for this version's tag, through GitHub's OpenID Connect issuer.
4. The images are pulled by digest.
5. The app is stopped and a copy of the database is taken (a snapshot).
6. The new images are written to the bundle's .env file and the services are started. The app brings the database
   up to date (the migrations) when it starts.
7. The health check has to answer with the new version within the time allowed.
8. If anything after step 5 fails, the app is stopped, the snapshot is put back, the old .env is written again and
   the old version is started. The result is written to the status file in each case, for the owner and for the
   health monitoring (story E01-010).

The updater reaches Docker through a socket proxy that allows containers, images, networks and volumes but not
exec, build or swarm calls (infra/compose.yaml). It uses only the Python standard library, the docker CLI with the
compose plugin, and cosign.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

REPOSITORY = "Franca-Language-Learning/Franca"
RELEASE_WORKFLOW_IDENTITY = f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/tags/{{tag}}"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
IMAGE_PATTERN = re.compile(r"^ghcr\.io/franca-language-learning/franca-(?P<service>app|caddy|updater)@sha256:[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
# The .env keys that name each image. A release has to have the app and caddy images; they are started at once. A new
# updater image is checked and written to .env too, and is used from the next start of the bundle.
IMAGE_KEYS = {"app": "FRANCA_APP_IMAGE", "caddy": "FRANCA_CADDY_IMAGE", "updater": "FRANCA_UPDATER_IMAGE"}
REQUIRED_IMAGES = frozenset({"app", "caddy"})
VERSION_KEY = "FRANCA_VERSION"
SNAPSHOTS_KEPT = 5


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


def http_fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise UpdateError(f"Only https addresses are read: {url[:120]}")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "franca-updater"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the URLs are https and fixed
        body: bytes = response.read(1_000_000)
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
                    values[key.strip()] = value.strip()
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

    def up(self, *services: str) -> None:
        _check(self.run(self._compose("up", "--detach", "--no-build", "--no-deps", *services)), "Starting " + ", ".join(services))

    def run_in_app(self, script: str) -> None:
        """Runs Python in a one-off container of the app image, with the database volume, while the app is stopped."""
        _check(self.run(self._compose("run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script)), "The database step")


SNAPSHOT_SCRIPT = """
import pathlib, sqlite3, sys
source, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
    live.backup(copy)
snapshots = sorted(target.parent.glob('franca-*.db'))
for old in snapshots[:-{kept}]:
    old.unlink()
"""

RESTORE_SCRIPT = """
import pathlib, shutil, sys
snapshot, live = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for extra in (live.with_name(live.name + '-wal'), live.with_name(live.name + '-shm')):
    extra.unlink(missing_ok=True)
shutil.copyfile(snapshot, live)
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


# --- health


Probe = Callable[[], str | None]


def health_probe(url: str) -> Probe:
    """Returns the version that the health endpoint reports, or None when it does not answer."""

    def probe() -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a fixed address inside the bundle
                answer = json.loads(response.read(10_000))
                return str(answer.get("version")) if answer.get("status") == "ok" else None
        except OSError, ValueError:
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


# --- status


@dataclass(slots=True)
class StatusFile:
    path: Path

    def write(self, **status: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".new")
        temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


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
    health_timeout: float = 180
    sleep: Callable[[float], None] = field(default=time.sleep)

    def run_once(self, now: datetime) -> str:
        """Checks for a release and installs it. Returns the result, which is also written to the status file."""
        checked = now.astimezone(UTC).isoformat(timespec="seconds")
        old_text = self.env.text()
        old = self.env.read()
        # A development build (such as 0.1.0-dev) counts as older than any release.
        installed = Version.parse(old[VERSION_KEY]) if VERSION_PATTERN.match(old.get(VERSION_KEY, "")) else Version(0, 0, 0)
        try:
            release = self.releases.latest()
        except UpdateError as error:
            return self._report("check-failed", checked, installed, None, str(error))
        if release.version <= installed:
            return self._report("up-to-date", checked, installed, release.version, "No newer release")
        try:
            for image in release.images.values():
                self.verifier.verify(image, release.version)
            for image in release.images.values():
                self.compose.pull(image)
        except UpdateError as error:
            return self._report("not-installed", checked, installed, release.version, str(error))

        try:
            self.compose.stop("app")
            snapshot = self.database.snapshot(f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-before-{release.version}")
        except UpdateError as error:
            return self._restart_unchanged(checked, installed, release.version, str(error))
        try:
            new = dict(old) | {VERSION_KEY: str(release.version)} | {IMAGE_KEYS[s]: image for s, image in release.images.items()}
            self.env.write(new)
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, str(release.version), self.health_timeout, self.sleep)
        except UpdateError as error:
            return self._roll_back(checked, installed, release.version, old_text, snapshot, str(error))
        return self._report("installed", checked, release.version, release.version, f"Installed {release.version}; snapshot {snapshot}")

    def _restart_unchanged(self, checked: str, installed: Version, failed: Version, reason: str) -> str:
        """Nothing was changed yet; the installed version is started again."""
        try:
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, str(installed), self.health_timeout, self.sleep)
        except UpdateError as error:
            return self._report("rollback-failed", checked, installed, failed, f"{reason}. Starting {installed} again failed too: {error}")
        return self._report("not-installed", checked, installed, failed, reason)

    def _roll_back(self, checked: str, installed: Version, failed: Version, old_text: str, snapshot: str, reason: str) -> str:
        try:
            self.compose.stop("app")
            self.env.put_back(old_text)
            self.database.restore(snapshot)
            self.compose.up("app", "caddy")
            wait_for_version(self.probe, str(installed), self.health_timeout, self.sleep)
        except UpdateError as error:
            return self._report("rollback-failed", checked, installed, failed, f"{reason}. Going back to {installed} failed too: {error}")
        return self._report("rolled-back", checked, installed, failed, f"{reason}. Version {installed} and its database were put back")

    def _report(self, result: str, checked: str, installed: Version, latest: Version | None, message: str) -> str:
        self.status.write(result=result, checkedAt=checked, installed=str(installed), latest=str(latest or ""), message=message)
        print(json.dumps({"result": result, "installed": str(installed), "latest": str(latest or ""), "message": message}), flush=True)
        return result


# --- the service


def next_run(now: datetime, at: str) -> datetime:
    """The next time of day `at` (HH:MM, UTC) after now."""
    hour, minute = (int(part) for part in at.split(":"))
    candidate = now.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


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
    )


def main(argv: Sequence[str] = sys.argv[1:], environ: Mapping[str, str] = os.environ) -> int:
    updater = from_environment(environ)
    if "--once" in argv:
        result = updater.run_once(datetime.now(UTC))
        return 0 if result in {"installed", "up-to-date"} else 1
    at = environ.get("FRANCA_UPDATE_AT_UTC", "02:30")
    while True:
        wake = next_run(datetime.now(UTC), at)
        time.sleep(max(0.0, (wake - datetime.now(UTC)).total_seconds()))
        updater.run_once(datetime.now(UTC))


if __name__ == "__main__":
    sys.exit(main())
