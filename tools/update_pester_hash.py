"""Writes the SHA-256 of the new Pester package into tools/programs.txt, after checking it against the gallery (E01-004).

Renovate updates Pester's version in tools/programs.txt, but it cannot read a hash from the PowerShell Gallery, so the
hash on Pester's line is still the old one and the job "Server, contracts and tools" fails. This script is run in
the Renovate branch, in the weekly maintenance (docs/package-updates.md):

  python3 -I tools/update_pester_hash.py

The .nupkg file of the version on Pester's line is downloaded, and its SHA-512 is compared with the package hash that
the gallery publishes for that version. When the two are the same, the SHA-256 of the file is written on Pester's
line. When they differ, nothing is written and the exit code is 2: the update is not merged, and an issue is opened.

Only the Python standard library is needed. The download is made with tools/install_program.py.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE / "programs.txt"
GALLERY = "https://www.powershellgallery.com/api/v2"
PESTER_LINE = re.compile(r"^(?P<start>Pester\s+(?P<version>[\w.-]+)\s+)(?P<sha256>[0-9a-f]{64})(?P<end>\s+https://\S+)$", re.MULTILINE)
PACKAGE_HASH = re.compile(r"<d:PackageHash>(?P<hash>[A-Za-z0-9+/=]+)</d:PackageHash>")
HASH_ALGORITHM = re.compile(r"<d:PackageHashAlgorithm>(?P<algorithm>\w+)</d:PackageHashAlgorithm>")
EXIT_HASHES_DIFFER = 2

Fetch = Callable[[str], bytes]


class UpdateError(Exception):
    """The Pester line, the package or the gallery's metadata could not be read."""


def _load_install_program() -> ModuleType:
    """tools/install_program.py, loaded by path, because python3 -I does not put this folder on sys.path."""
    spec = importlib.util.spec_from_file_location("install_program", HERE / "install_program.py")
    if spec is None or spec.loader is None:
        raise UpdateError("tools/install_program.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("install_program", module)
    spec.loader.exec_module(module)
    return module


def download(url: str) -> bytes:
    """The file at the address, with the size limit and https-only redirects of tools/install_program.py."""
    install_program = _load_install_program()
    try:
        data: bytes = install_program.download(url)
    except install_program.InstallError as error:
        raise UpdateError(str(error)) from error
    return data


def pester_line(text: str) -> re.Match[str] | None:
    return PESTER_LINE.search(text)


def published_sha512(metadata: str) -> str:
    """The base64 SHA-512 that the gallery publishes for the package."""
    algorithm = HASH_ALGORITHM.search(metadata)
    package_hash = PACKAGE_HASH.search(metadata)
    if package_hash is None:
        raise UpdateError("the gallery's metadata has no package hash")
    if algorithm is None or algorithm["algorithm"].upper() != "SHA512":
        raise UpdateError("the gallery's package hash is not a SHA-512")
    return package_hash["hash"]


def main(argv: list[str] | None = None, fetch: Fetch = download) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--programs", type=Path, default=PROGRAMS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        text = args.programs.read_text(encoding="utf-8")
        line = pester_line(text)
        if line is None:
            raise UpdateError(f"{args.programs.name} has no Pester line with a version, a SHA-256 and an address")
        version = line["version"]
        package = fetch(f"{GALLERY}/package/Pester/{version}")
        metadata = fetch(f"{GALLERY}/Packages(Id='Pester',Version='{version}')").decode("utf-8", errors="replace")
        published = published_sha512(metadata)
    except UpdateError as error:
        print(f"update_pester_hash: {error}", file=sys.stderr)
        return 1
    downloaded = base64.b64encode(hashlib.sha512(package).digest()).decode()
    if downloaded != published:
        print(
            f"The hashes do not match. The Pester {version} package that was downloaded has the SHA-512 {downloaded}, and "
            f"the gallery publishes {published}. Nothing was written: do not merge the update, and open an issue.",
            file=sys.stderr,
        )
        return EXIT_HASHES_DIFFER
    sha256 = hashlib.sha256(package).hexdigest()
    args.programs.write_text(text[: line.start("sha256")] + sha256 + text[line.end("sha256") :], encoding="utf-8")
    print(f"The gallery's hash matches. The SHA-256 of Pester {version}, {sha256}, is written in {args.programs.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
