"""Tests for tools/install_program.py and tools/programs.txt (stories E01-004 and E01-013).

The command-line programs that the pipeline and scripts/check download are pinned by the SHA-256 of the downloaded
file. A download with another hash is not kept, and Renovate updates the version and the hash together.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("install_program", ROOT / "tools" / "install_program.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["install_program"] = module
    spec.loader.exec_module(module)
    return module


ip = load_tool()


def tar_gz(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


ARCHIVE = tar_gz({"LICENSE": b"licence", "tool": b"#!/bin/sh\necho tool\n"})
ADDRESS = "https://github.com/example/tool/releases/download/{tag}/tool_{version}_linux_x64.tar.gz"


def programs_file(tmp_path: Path, sha256: str = hashlib.sha256(ARCHIVE).hexdigest(), tag: str = "v1.2.3") -> Path:
    path = tmp_path / "programs.txt"
    path.write_text(f"# A comment\n\ntool  {tag}  {sha256}  {ADDRESS}\n", encoding="utf-8")
    return path


class Downloads:
    """A stand-in for the download: it records the addresses and returns the archive."""

    def __init__(self, data: bytes = ARCHIVE) -> None:
        self.data = data
        self.addresses: list[str] = []

    def __call__(self, address: str) -> bytes:
        self.addresses.append(address)
        return self.data


# --- Reading programs.txt


def test_a_line_names_the_program_version_hash_and_address(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    assert (program.name, program.tag, program.sha256) == ("tool", "v1.2.3", hashlib.sha256(ARCHIVE).hexdigest())
    assert program.url == "https://github.com/example/tool/releases/download/v1.2.3/tool_1.2.3_linux_x64.tar.gz"


def test_a_tag_without_a_v_is_the_version(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path, tag="1.24.0")).values()
    assert program.url.endswith("/download/1.24.0/tool_1.24.0_linux_x64.tar.gz")


@pytest.mark.parametrize(
    "line",
    ["tool v1 abc https://example.org/a.tar.gz", f"tool v1 {'a' * 64}", f"tool v1 {'a' * 64} http://example.org/a.tar.gz"],
    ids=["short hash", "no address", "not https"],
)
def test_a_line_that_cannot_be_read_is_refused(tmp_path: Path, line: str) -> None:
    path = tmp_path / "programs.txt"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ip.InstallError, match="line 1"):
        ip.read_programs(path)


def test_a_program_that_is_not_listed_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = ip.main(["other", "--programs", str(programs_file(tmp_path)), "--cache", str(tmp_path / "cache")], fetch=Downloads())
    assert code == 1
    assert "other is not in programs.txt" in capsys.readouterr().err


# --- Installing


def test_the_program_is_unpacked_from_the_archive(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    path = ip.install(program, tmp_path / "cache", fetch=Downloads())
    assert path.name == "tool"
    assert path.read_bytes() == b"#!/bin/sh\necho tool\n"
    assert path.stat().st_mode & 0o111


def test_a_download_with_another_hash_is_not_kept(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path, sha256="0" * 64)).values()
    with pytest.raises(ip.InstallError, match="SHA-256"):
        ip.install(program, tmp_path / "cache", fetch=Downloads())
    assert [path for path in (tmp_path / "cache").rglob("*") if path.is_file()] == []


def test_a_kept_download_is_used_again_without_a_network(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    downloads = Downloads()
    ip.install(program, tmp_path / "cache", fetch=downloads)
    ip.install(program, tmp_path / "cache", fetch=downloads)
    assert len(downloads.addresses) == 1


def test_a_kept_download_that_was_changed_is_downloaded_again(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    downloads = Downloads()
    path = ip.install(program, tmp_path / "cache", fetch=downloads)
    archive = next(p for p in path.parent.iterdir() if p.name.endswith(".tar.gz"))
    archive.write_bytes(b"changed")
    path.write_bytes(b"changed")
    assert ip.install(program, tmp_path / "cache", fetch=downloads).read_bytes() == b"#!/bin/sh\necho tool\n"
    assert len(downloads.addresses) == 2


def test_an_archive_without_the_program_is_refused(tmp_path: Path) -> None:
    other = tar_gz({"README.md": b"no program here"})
    (program,) = ip.read_programs(programs_file(tmp_path, sha256=hashlib.sha256(other).hexdigest())).values()
    with pytest.raises(ip.InstallError, match="no file named tool"):
        ip.install(program, tmp_path / "cache", fetch=Downloads(other))


def test_the_command_prints_the_path_of_the_program(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = ip.main(["tool", "--programs", str(programs_file(tmp_path)), "--cache", str(tmp_path / "cache")], fetch=Downloads())
    assert code == 0
    assert Path(capsys.readouterr().out.strip()) == tmp_path / "cache" / "tool-v1.2.3" / "tool"


def test_the_command_reports_a_failed_download(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def no_network(address: str) -> bytes:
        raise ip.InstallError(f"{address} could not be downloaded: no network")

    code = ip.main(["tool", "--programs", str(programs_file(tmp_path)), "--cache", str(tmp_path / "cache")], fetch=no_network)
    assert code == 1
    assert "could not be downloaded" in capsys.readouterr().err


# --- The platform


def test_the_platform_line_is_read(tmp_path: Path) -> None:
    path = programs_file(tmp_path)
    path.write_text("platform  Linux  x86_64\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    (program,) = ip.read_programs(path).values()
    assert program.platform == ("Linux", "x86_64")


def test_a_program_for_another_platform_is_not_downloaded(tmp_path: Path) -> None:
    path = programs_file(tmp_path)
    path.write_text("platform  Linux  x86_64\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    (program,) = ip.read_programs(path).values()
    downloads = Downloads()
    with pytest.raises(ip.UnsupportedPlatform, match="Linux on x86_64"):
        ip.install(program, tmp_path / "cache", fetch=downloads, this_platform=("Darwin", "arm64"))
    assert downloads.addresses == []


def test_the_command_reports_another_platform_with_its_own_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = programs_file(tmp_path)
    path.write_text("platform  Linux  x86_64\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    code = ip.main(
        ["tool", "--programs", str(path), "--cache", str(tmp_path / "cache")], fetch=Downloads(), this_platform=("Linux", "aarch64")
    )
    assert code == ip.EXIT_OTHER_PLATFORM
    assert "Linux on x86_64" in capsys.readouterr().err


def test_the_command_reports_a_changed_download_with_its_own_exit_code(tmp_path: Path) -> None:
    path = programs_file(tmp_path, sha256="0" * 64)
    code = ip.main(["tool", "--programs", str(path), "--cache", str(tmp_path / "cache")], fetch=Downloads())
    assert code == ip.EXIT_HASH_MISMATCH


# --- Reusing a download and writing files


def test_the_program_is_unpacked_again_from_the_checked_download(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    downloads = Downloads()
    path = ip.install(program, tmp_path / "cache", fetch=downloads)
    path.write_bytes(b"changed after the download")
    assert ip.install(program, tmp_path / "cache", fetch=downloads).read_bytes() == b"#!/bin/sh\necho tool\n"
    assert len(downloads.addresses) == 1


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path)).values()
    path = ip.install(program, tmp_path / "cache", fetch=Downloads())
    assert sorted(p.name for p in path.parent.iterdir()) == ["tool", "tool_1.2.3_linux_x64.tar.gz"]


@pytest.mark.parametrize("name", [".", ".."])
def test_a_name_of_dots_is_refused(tmp_path: Path, name: str) -> None:
    path = tmp_path / "programs.txt"
    path.write_text(f"{name}  v1  {'a' * 64}  https://example.org/a.tar.gz\n", encoding="utf-8")
    with pytest.raises(ip.InstallError, match="line 1"):
        ip.read_programs(path)


# --- Downloading


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, size: int) -> None:
        self.size = size

    def open(self, url: str, timeout: float) -> FakeResponse:
        return FakeResponse(b"x" * self.size)


def test_a_download_larger_than_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr(ip, "OPENER", FakeOpener(11))
    with pytest.raises(ip.InstallError, match="larger than"):
        ip.download("https://example.org/a.tar.gz")
    monkeypatch.setattr(ip, "OPENER", FakeOpener(10))
    assert ip.download("https://example.org/a.tar.gz") == b"x" * 10


def test_a_redirect_to_an_address_that_is_not_https_is_refused() -> None:
    handler = ip.HttpsOnlyRedirects()
    request = urllib.request.Request("https://github.com/a")
    with pytest.raises(ip.InstallError, match="not https"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", http.client.HTTPMessage(), "http://example.org/a")
    assert handler.redirect_request(request, io.BytesIO(), 302, "Found", http.client.HTTPMessage(), "https://example.org/a") is not None


# --- The programs in this repository


def test_the_programs_in_this_repository_can_be_read() -> None:
    programs = ip.read_programs(ip.PROGRAMS)
    assert "gitleaks" in programs
    assert programs["gitleaks"].platform == ("Linux", "x86_64")
    assert all(program.url.startswith("https://github.com/") for program in programs.values())


def test_renovate_finds_each_program_with_its_version_and_hash() -> None:
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    (manager,) = [
        m for m in config["customManagers"] if any(re.search(p.strip("/"), "tools/programs.txt") for p in m["managerFilePatterns"])
    ]
    assert manager["datasourceTemplate"] == "github-release-attachments"
    text = ip.PROGRAMS.read_text(encoding="utf-8")
    found = {
        (match["depName"], match["currentValue"], match["currentDigest"])
        for match_string in manager["matchStrings"]
        for match in re.finditer(match_string.replace("(?<", "(?P<"), text)
    }
    expected = {
        (re.search(r"github\.com/([^/]+/[^/]+)/", p.url)[1], p.tag, p.sha256)  # type: ignore[index]
        for p in ip.read_programs(ip.PROGRAMS).values()
    }
    assert found == expected
