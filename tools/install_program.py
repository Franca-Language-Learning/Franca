"""Downloads a program listed in tools/programs.txt and checks it against its SHA-256 (E01-004, E01-013).

The programs that the pipeline and scripts/check run, such as gitleaks, Grype and the PowerShell modules that check
the Windows installer, are downloaded from their release pages. A release file can be replaced after it is
published, so each program is pinned by the SHA-256 of the file in tools/programs.txt, and a download with another
hash is not kept (.github/renovate.json, docs/package-updates.md).

  python3 -I tools/install_program.py gitleaks     download gitleaks if needed, and print the path of the program
  python3 -I tools/install_program.py Pester       download Pester if needed, and print the path of its folder

From a .tar.gz download, the file with the program's name is taken out. A zip download, such as a PowerShell
module's .nupkg file, is unpacked into a folder with the program's name. The kind of download is read from its
first bytes, because an address such as the PowerShell Gallery's has no file extension.

The checked download is kept in ~/.cache/franca/programs (or $XDG_CACHE_HOME/franca/programs), so the program can
be used again without a network. The program is unpacked from the checked download on each run. The .tar.gz files
are for the platform on the platform line of tools/programs.txt, and on another platform nothing is downloaded.
Only the Python standard library is needed.

A download that fails with a connection error, a timeout, HTTP 429 or HTTP 5xx is tried up to three times, with waits
of 5 and 15 seconds. HTTP 403 for an address on the PowerShell Gallery, before or after redirects, is tried again in the
same way, because the gallery has refused a request once and accepted it on the next run. Before a new try, a line with
the address, the reason and the number of the try is written to standard error. Other HTTP errors fail at once, and a
download with another hash is not tried again.

Exit codes: 0 when the program is ready, 3 when the download has another hash, 4 when this computer is not on the
platform of the file, and 1 for other problems, such as no network.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import platform
import re
import shutil
import ssl
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from typing import IO

PROGRAMS = Path(__file__).resolve().parent / "programs.txt"
DOWNLOAD_TIMEOUT_SECONDS = 120
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
LINE = re.compile(r"^(?P<name>\w[\w.-]*)\s+(?P<tag>[\w.-]+)\s+(?P<sha256>[0-9a-f]{64})\s+(?P<address>https://\S+)$")
PLATFORM_LINE = re.compile(r"^platform\s+(?P<system>\S+)\s+(?P<machine>\S+)$")
EXIT_HASH_MISMATCH = 3
EXIT_OTHER_PLATFORM = 4
GZIP_START = b"\x1f\x8b"
ZIP_START = b"PK\x03\x04"
# A failed download is tried again after each of these waits, so it is tried up to three times.
RETRY_WAITS_SECONDS = (5, 15)
POWERSHELL_GALLERY_HOSTS = {"www.powershellgallery.com", "cdn.powershellgallery.com"}

Fetch = Callable[[str], bytes]


class InstallError(Exception):
    """A program could not be read from programs.txt, downloaded, checked or unpacked."""


class HashMismatch(InstallError):
    """The download does not have the SHA-256 in programs.txt."""


class UnsupportedPlatform(InstallError):
    """The program's file is for another platform than this computer's."""


@dataclass(frozen=True)
class Program:
    """A line of programs.txt. In the address, {tag} is the release tag and {version} is the tag without a leading v.

    platform is the (system, machine) pair that the file is made for, as given by platform.system() and
    platform.machine(), or None when the file works on any platform.
    """

    name: str
    tag: str
    sha256: str
    address: str
    platform: tuple[str, str] | None = None

    @property
    def url(self) -> str:
        return self.address.replace("{tag}", self.tag).replace("{version}", self.tag.removeprefix("v"))

    @property
    def file_name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


def read_programs(path: Path) -> dict[str, Program]:
    """The programs in the file, by name. Blank lines and lines starting with # are left out.

    The platform line applies to the programs that are downloaded as .tar.gz files.
    """
    found = []
    file_platform = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if platform_match := PLATFORM_LINE.match(line.strip()):
            file_platform = (platform_match["system"], platform_match["machine"])
            continue
        match = LINE.match(line.strip())
        if not match:
            raise InstallError(f"{path.name} line {number} is not: name, version, SHA-256 and https address")
        found.append(match)
    programs = {}
    for match in found:
        needs = file_platform if match["address"].endswith(".tar.gz") else None
        programs[match["name"]] = Program(match["name"], match["tag"], match["sha256"], match["address"], needs)
    return programs


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another https address."""

    def redirect_request(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> urllib.request.Request | None:
        if not newurl.startswith("https://"):
            raise InstallError(f"{req.full_url} was redirected to an address that is not https: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HttpsOnlyRedirects)


class TemporaryFailure(InstallError):
    """A download failed for a reason that may be gone on the next try, such as a timeout or a server error."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url} could not be downloaded: {reason}")
        self.reason = reason


def _failure(url: str, error: BaseException) -> InstallError:
    """The error to raise for a failed download: a TemporaryFailure when the download is worth trying again.

    A 403 is retried when the address asked for or the address that answered is on the PowerShell Gallery, because the
    gallery can redirect a package download to storage on another host.
    """
    if isinstance(error, urllib.error.HTTPError):
        # The error holds the open response, which is closed here so that it is not left open during the next try.
        error.close()
        hosts = {urllib.parse.urlsplit(address).hostname for address in (url, error.geturl() or url)}
        if error.code == 429 or 500 <= error.code < 600 or (error.code == 403 and hosts & POWERSHELL_GALLERY_HOSTS):
            return TemporaryFailure(url, f"HTTP {error.code}")
        return InstallError(f"{url} could not be downloaded: HTTP {error.code}")
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, ssl.SSLCertVerificationError):
        return InstallError(f"{url} could not be downloaded: {cause}")
    if isinstance(cause, TimeoutError):
        return TemporaryFailure(url, "timeout")
    return TemporaryFailure(url, f"connection error ({cause})")


def _download_once(url: str) -> bytes:
    try:
        with OPENER.open(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            data: bytes = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise _failure(url, error) from error
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise InstallError(f"{url} is larger than {MAX_DOWNLOAD_BYTES} bytes")
    return data


def download(url: str, sleep: Callable[[float], None] = time.sleep) -> bytes:
    """The file at the address, up to MAX_DOWNLOAD_BYTES. Redirects are followed to https addresses only.

    A download that fails with a connection error, a timeout, HTTP 429, HTTP 5xx, or HTTP 403 for an address on the
    PowerShell Gallery before or after redirects, is tried again after the waits in RETRY_WAITS_SECONDS, with a line on
    standard error before a new try. Other failures are raised at once.
    """
    attempts = len(RETRY_WAITS_SECONDS) + 1
    for attempt, wait in enumerate(RETRY_WAITS_SECONDS, start=2):
        try:
            return _download_once(url)
        except TemporaryFailure as failure:
            print(
                f"install_program: {url} failed ({failure.reason}), trying again in {wait} seconds (attempt {attempt} of {attempts})",
                file=sys.stderr,
            )
            sleep(wait)
    return _download_once(url)


def _has_hash(path: Path, sha256: str) -> bool:
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256


def _write(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Writes the file under a new temporary name in the same folder, then renames it, so no half file is left."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _unpack_program(archive: Path, name: str, target: Path) -> None:
    """Copies the file called name out of a .tar.gz archive. Only that file is read from the archive."""
    with tarfile.open(archive, mode="r:gz") as files:
        member = next((m for m in files.getmembers() if m.isfile() and Path(m.name).name == name), None)
        content = files.extractfile(member) if member else None
        if content is None:
            raise InstallError(f"{archive.name} has no file named {name}")
        _write(target, content.read(), mode=0o755)


def _unpack_folder(archive: Path, target: Path) -> None:
    """Unpacks a zip file into the target folder. A file whose path would end up outside the folder is refused."""
    temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}."))
    try:
        with zipfile.ZipFile(archive) as files:
            for member in files.infolist():
                path = Path(member.filename)
                if path.is_absolute() or member.filename.startswith(("/", "\\")) or ".." in path.parts:
                    raise InstallError(f"{archive.name} has a file outside its folder: {member.filename}")
                if member.is_dir():
                    continue
                destination = temporary / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(files.read(member))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def current_platform() -> tuple[str, str]:
    return platform.system(), platform.machine()


def install(program: Program, cache: Path, fetch: Fetch = download, this_platform: tuple[str, str] | None = None) -> Path:
    """The path of the program (or the module's folder). It is downloaded into the cache unless a checked copy is there
    already, and it is unpacked from the checked copy on each run, so a program that was changed in the cache is not run."""
    this_platform = this_platform or current_platform()
    if program.platform and program.platform != this_platform:
        system, machine = program.platform
        raise UnsupportedPlatform(
            f"{program.name} is downloaded for {system} on {machine}, and this computer is {' on '.join(this_platform)}"
        )
    folder = cache / f"{program.name}-{program.tag}"
    archive = folder / program.file_name
    target = folder / program.name
    if not _has_hash(archive, program.sha256):
        data = fetch(program.url)
        actual = hashlib.sha256(data).hexdigest()
        if actual != program.sha256:
            raise HashMismatch(
                f"{program.name} {program.tag}: the download has the SHA-256 {actual}, and tools/programs.txt has {program.sha256},"
                " so it was not kept"
            )
        folder.mkdir(parents=True, exist_ok=True)
        _write(archive, data)
    _remove(target)
    with archive.open("rb") as file:
        start = file.read(4)
    if start.startswith(GZIP_START):
        _unpack_program(archive, program.name, target)
    elif start.startswith(ZIP_START):
        _unpack_folder(archive, target)
    else:
        raise InstallError(f"{program.file_name} is neither a .tar.gz file nor a zip file")
    return target


def default_cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "franca" / "programs"


def main(argv: list[str] | None = None, fetch: Fetch = download, this_platform: tuple[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="the name of the program in tools/programs.txt")
    parser.add_argument("--programs", type=Path, default=PROGRAMS, help=argparse.SUPPRESS)
    parser.add_argument("--cache", type=Path, default=None, help="the folder for downloads (default: ~/.cache/franca/programs)")
    args = parser.parse_args(argv)
    try:
        programs = read_programs(args.programs)
        if args.name not in programs:
            raise InstallError(f"{args.name} is not in {args.programs.name}")
        path = install(programs[args.name], args.cache or default_cache(), fetch, this_platform)
    except InstallError as error:
        print(f"install_program: {error}", file=sys.stderr)
        if isinstance(error, HashMismatch):
            return EXIT_HASH_MISMATCH
        if isinstance(error, UnsupportedPlatform):
            return EXIT_OTHER_PLATFORM
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
