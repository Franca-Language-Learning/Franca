"""Tests for tools/update_pester_hash.py (story E01-004).

Renovate updates Pester's version in tools/programs.txt but cannot read a hash from the PowerShell Gallery. The
script downloads the new .nupkg file, compares its SHA-512 with the hash that the gallery publishes, and writes the
SHA-256 on Pester's line.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_pester_hash", ROOT / "tools" / "update_pester_hash.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["update_pester_hash"] = module
    spec.loader.exec_module(module)
    return module


uph = load_tool()

PACKAGE = b"PK\x03\x04 a made-up Pester package"
OLD_HASH = "0" * 64
GALLERY = "https://www.powershellgallery.com/api/v2"


def programs_file(tmp_path: Path, version: str = "5.8.0") -> Path:
    path = tmp_path / "programs.txt"
    path.write_text(
        "# comment\n"
        "platform           Linux     x86_64\n"
        f"grype              v0.122.1  {'1' * 64}  https://github.com/anchore/grype/releases/download/{{tag}}/grype_{{version}}_linux_amd64.tar.gz\n"
        f"Pester             {version}     {OLD_HASH}  {GALLERY}/package/Pester/{{tag}}\n",
        encoding="utf-8",
    )
    return path


def metadata(package: bytes, algorithm: str = "SHA512") -> bytes:
    published = base64.b64encode(hashlib.sha512(package).digest()).decode()
    return (
        f"<entry><m:properties><d:Version>5.8.0</d:Version><d:PackageHash>{published}</d:PackageHash>"
        f"<d:PackageHashAlgorithm>{algorithm}</d:PackageHashAlgorithm></m:properties></entry>"
    ).encode()


class Gallery:
    """A stand-in for the PowerShell Gallery: the package and its metadata, by address."""

    def __init__(self, package: bytes = PACKAGE, published_for: bytes = PACKAGE, algorithm: str = "SHA512") -> None:
        self.files = {
            f"{GALLERY}/package/Pester/5.8.0": package,
            f"{GALLERY}/Packages(Id='Pester',Version='5.8.0')": metadata(published_for, algorithm),
        }
        self.addresses: list[str] = []

    def __call__(self, address: str) -> bytes:
        self.addresses.append(address)
        return self.files[address]


def test_the_sha256_is_written_when_the_gallery_hash_matches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = programs_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert uph.main(["--programs", str(path)], fetch=Gallery()) == 0
    after = path.read_text(encoding="utf-8")
    assert after == before.replace(OLD_HASH, hashlib.sha256(PACKAGE).hexdigest())
    assert "matches" in capsys.readouterr().out


def test_nothing_is_written_when_the_hashes_differ(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = programs_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    code = uph.main(["--programs", str(path)], fetch=Gallery(package=b"PK\x03\x04 another file"))
    assert code == uph.EXIT_HASHES_DIFFER
    assert path.read_text(encoding="utf-8") == before
    message = capsys.readouterr().err
    assert "do not merge" in message
    assert "issue" in message


def test_a_gallery_hash_that_is_not_sha512_is_refused(tmp_path: Path) -> None:
    path = programs_file(tmp_path)
    assert uph.main(["--programs", str(path)], fetch=Gallery(algorithm="SHA256")) == 1


def test_metadata_without_a_hash_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = programs_file(tmp_path)
    gallery = Gallery()
    gallery.files[f"{GALLERY}/Packages(Id='Pester',Version='5.8.0')"] = b"<entry></entry>"
    assert uph.main(["--programs", str(path)], fetch=gallery) == 1
    assert "no package hash" in capsys.readouterr().err


def test_the_version_is_read_from_the_pester_line(tmp_path: Path) -> None:
    gallery = Gallery()
    uph.main(["--programs", str(programs_file(tmp_path))], fetch=gallery)
    assert gallery.addresses == [f"{GALLERY}/package/Pester/5.8.0", f"{GALLERY}/Packages(Id='Pester',Version='5.8.0')"]


def test_this_repository_has_a_pester_line_that_the_script_reads() -> None:
    assert uph.pester_line(uph.PROGRAMS.read_text(encoding="utf-8")) is not None
