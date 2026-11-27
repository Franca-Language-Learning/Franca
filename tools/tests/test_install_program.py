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
import ssl
import sys
import tarfile
import urllib.request
import zipfile
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


# --- Trying a download again

GALLERY = "https://www.powershellgallery.com/api/v2/package/Pester/5.7.1"
GITHUB = "https://github.com/example/tool/releases/download/v1.2.3/tool_1.2.3_linux_x64.tar.gz"


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "refused", http.client.HTTPMessage(), None)


class FlakyOpener:
    """Raises the errors in turn, then returns the file. Each call of open is recorded."""

    def __init__(self, *errors: BaseException) -> None:
        self.errors = list(errors)
        self.calls = 0

    def open(self, url: str, timeout: float) -> FakeResponse:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FakeResponse(b"file")


class Waits:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


@pytest.mark.parametrize(
    ("url", "error", "reason"),
    [
        (GALLERY, http_error(GALLERY, 403), "HTTP 403"),
        (GALLERY, http_error("https://cdn.powershellgallery.com/packages/pester.5.7.1.nupkg", 403), "HTTP 403"),
        (GITHUB, http_error(GITHUB, 429), "HTTP 429"),
        (GITHUB, http_error(GITHUB, 500), "HTTP 500"),
        (GITHUB, http_error(GITHUB, 503), "HTTP 503"),
        (GITHUB, urllib.error.URLError(ConnectionRefusedError("refused")), "connection error"),
        (GITHUB, ConnectionResetError("reset"), "connection error"),
        (GITHUB, http.client.IncompleteRead(b""), "connection error"),
        (GITHUB, TimeoutError("timed out"), "timeout"),
        (GITHUB, urllib.error.URLError(TimeoutError("timed out")), "timeout"),
    ],
    ids=["gallery 403", "gallery cdn 403", "429", "500", "503", "refused", "reset", "cut off", "timeout", "timeout in urlopen"],
)
def test_a_download_that_fails_for_a_passing_reason_is_tried_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str, error: BaseException, reason: str
) -> None:
    opener = FlakyOpener(error)
    monkeypatch.setattr(ip, "OPENER", opener)
    waits = Waits()
    assert ip.download(url, sleep=waits) == b"file"
    assert opener.calls == 2
    assert waits.seconds == [5]
    (line,) = capsys.readouterr().err.splitlines()
    assert url in line
    assert reason in line
    assert "attempt 2 of 3" in line


def test_a_download_is_tried_three_times_with_waits_of_5_and_15_seconds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opener = FlakyOpener(http_error(GALLERY, 403), http_error(GALLERY, 403), http_error(GALLERY, 403))
    monkeypatch.setattr(ip, "OPENER", opener)
    waits = Waits()
    with pytest.raises(ip.InstallError, match="HTTP 403"):
        ip.download(GALLERY, sleep=waits)
    assert opener.calls == 3
    assert waits.seconds == [5, 15]
    lines = capsys.readouterr().err.splitlines()
    assert ["attempt 2 of 3" in lines[0], "attempt 3 of 3" in lines[1]] == [True, True]
    assert len(lines) == 2


@pytest.mark.parametrize(
    ("url", "error"),
    [
        (GITHUB, http_error(GITHUB, 403)),
        (GITHUB, http_error(GITHUB, 404)),
        (GALLERY, http_error(GALLERY, 404)),
        (GITHUB, urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))),
        (GITHUB, ip.InstallError("https://github.com/a was redirected to an address that is not https: http://example.org/a")),
    ],
    ids=["403 from another host", "404", "gallery 404", "certificate", "redirect to http"],
)
def test_other_failures_are_not_tried_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str, error: BaseException
) -> None:
    opener = FlakyOpener(error)
    monkeypatch.setattr(ip, "OPENER", opener)
    waits = Waits()
    with pytest.raises(ip.InstallError):
        ip.download(url, sleep=waits)
    assert opener.calls == 1
    assert waits.seconds == []
    assert capsys.readouterr().err == ""


def test_a_download_larger_than_the_limit_is_not_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "MAX_DOWNLOAD_BYTES", 2)
    opener = FlakyOpener()
    monkeypatch.setattr(ip, "OPENER", opener)
    waits = Waits()
    with pytest.raises(ip.InstallError, match="larger than"):
        ip.download(GITHUB, sleep=waits)
    assert (opener.calls, waits.seconds) == (1, [])


def test_a_download_with_another_hash_is_not_tried_again(tmp_path: Path) -> None:
    (program,) = ip.read_programs(programs_file(tmp_path, sha256="0" * 64)).values()
    downloads = Downloads()
    with pytest.raises(ip.HashMismatch):
        ip.install(program, tmp_path / "cache", fetch=downloads)
    assert len(downloads.addresses) == 1


# --- PowerShell modules (.nupkg files are zip files)


def nupkg(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


MODULE = nupkg({"Module.psd1": b"@{ ModuleVersion = '1.2.3' }", "en-US/about_Module.help.txt": b"help", "[Content_Types].xml": b"<x/>"})


def module_programs_file(
    tmp_path: Path, data: bytes, address: str = "https://www.powershellgallery.com/api/v2/package/Module/{tag}"
) -> Path:
    path = tmp_path / "programs.txt"
    path.write_text(f"Module  1.2.3  {hashlib.sha256(data).hexdigest()}  {address}\n", encoding="utf-8")
    return path


def test_a_module_is_unpacked_into_a_folder(tmp_path: Path) -> None:
    (program,) = ip.read_programs(module_programs_file(tmp_path, MODULE)).values()
    folder = ip.install(program, tmp_path / "cache", fetch=Downloads(MODULE))
    assert folder == tmp_path / "cache" / "Module-1.2.3" / "Module"
    assert (folder / "Module.psd1").read_bytes() == b"@{ ModuleVersion = '1.2.3' }"
    assert (folder / "en-US" / "about_Module.help.txt").read_bytes() == b"help"


def test_a_module_from_a_github_release_is_unpacked_too(tmp_path: Path) -> None:
    address = "https://github.com/example/Module/releases/download/{tag}/Module.{version}.nupkg"
    (program,) = ip.read_programs(module_programs_file(tmp_path, MODULE, address)).values()
    assert (ip.install(program, tmp_path / "cache", fetch=Downloads(MODULE)) / "Module.psd1").is_file()


def test_a_kept_module_is_used_again_without_a_network(tmp_path: Path) -> None:
    (program,) = ip.read_programs(module_programs_file(tmp_path, MODULE)).values()
    downloads = Downloads(MODULE)
    ip.install(program, tmp_path / "cache", fetch=downloads)
    ip.install(program, tmp_path / "cache", fetch=downloads)
    assert len(downloads.addresses) == 1


def test_a_module_that_was_changed_in_the_cache_is_unpacked_again(tmp_path: Path) -> None:
    (program,) = ip.read_programs(module_programs_file(tmp_path, MODULE)).values()
    folder = ip.install(program, tmp_path / "cache", fetch=Downloads(MODULE))
    (folder / "Module.psd1").write_bytes(b"changed")
    (folder / "extra.ps1").write_bytes(b"added")
    folder = ip.install(program, tmp_path / "cache", fetch=Downloads(MODULE))
    assert (folder / "Module.psd1").read_bytes() == b"@{ ModuleVersion = '1.2.3' }"
    assert not (folder / "extra.ps1").exists()


@pytest.mark.parametrize("name", ["../outside.txt", "/etc/outside.txt", "folder/../../outside.txt"])
def test_a_module_with_a_path_outside_its_folder_is_refused(tmp_path: Path, name: str) -> None:
    data = nupkg({"Module.psd1": b"x", name: b"outside"})
    (program,) = ip.read_programs(module_programs_file(tmp_path, data)).values()
    with pytest.raises(ip.InstallError, match="outside"):
        ip.install(program, tmp_path / "cache", fetch=Downloads(data))
    assert not (tmp_path / "cache" / "outside.txt").exists()


def test_a_download_that_is_neither_a_tar_gz_nor_a_zip_file_is_refused(tmp_path: Path) -> None:
    data = b"<html>not a package</html>"
    (program,) = ip.read_programs(module_programs_file(tmp_path, data)).values()
    with pytest.raises(ip.InstallError, match="neither"):
        ip.install(program, tmp_path / "cache", fetch=Downloads(data))


# --- The programs in this repository


def renovate_matches(text: str) -> dict[str, set[tuple[str, str, str | None]]]:
    """What each Renovate manager for tools/programs.txt finds, by datasource: (dependency, version, hash) for each line."""
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    managers = [m for m in config["customManagers"] if any(re.search(p.strip("/"), "tools/programs.txt") for p in m["managerFilePatterns"])]
    found: dict[str, set[tuple[str, str, str | None]]] = {}
    for manager in managers:
        for match_string in manager["matchStrings"]:
            for match in re.finditer(match_string.replace("(?<", "(?P<"), text):
                digest = match.groupdict().get("currentDigest")
                found.setdefault(manager["datasourceTemplate"], set()).add((match["depName"], match["currentValue"], digest))
    return found


def test_the_programs_in_this_repository_can_be_read() -> None:
    programs = ip.read_programs(ip.PROGRAMS)
    assert set(programs) == {"gitleaks", "grype", "syft", "PSScriptAnalyzer", "Pester"}
    assert {name for name, program in programs.items() if program.platform == ("Linux", "x86_64")} == {"gitleaks", "grype", "syft"}
    assert programs["Pester"].platform is None


def test_renovate_finds_each_program_with_its_version_and_hash() -> None:
    programs = ip.read_programs(ip.PROGRAMS).values()
    on_github = {
        (match[1], p.tag, p.sha256) for p in programs if (match := re.match(r"https://github\.com/([^/]+/[^/]+)/releases/download/", p.url))
    }
    on_the_gallery = {(p.name, p.tag, None) for p in programs if p.url.startswith("https://www.powershellgallery.com/api/v2/package/")}
    assert len(on_github) + len(on_the_gallery) == len(programs)
    assert renovate_matches(ip.PROGRAMS.read_text(encoding="utf-8")) == {"github-release-attachments": on_github, "nuget": on_the_gallery}


def test_renovate_looks_up_powershell_modules_in_the_gallery() -> None:
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    (manager,) = [m for m in config["customManagers"] if m.get("datasourceTemplate") == "nuget"]
    assert manager["registryUrlTemplate"] == "https://www.powershellgallery.com/api/v2/"


def test_the_workflows_install_the_pinned_programs_only() -> None:
    """Anchore's actions and Install-Module download a version without checking a hash, so the workflows do not use them."""
    for path in [*(ROOT / ".github").rglob("*.yml"), *(ROOT / ".github").rglob("*.yaml")]:
        text = path.read_text(encoding="utf-8")
        for unpinned in ("anchore/scan-action", "anchore/sbom-action", "Install-Module"):
            assert unpinned not in text, f"{path.name} uses {unpinned}"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for name, workflow in [("grype", ci), ("Pester", ci), ("PSScriptAnalyzer", ci), ("grype", release), ("syft", release)]:
        assert f"tools/install_program.py {name}" in workflow, name


def test_renovate_finds_the_installers_cosign_with_its_version_and_hash() -> None:
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    (manager,) = [
        m
        for m in config["customManagers"]
        if "/^installer/.+\\.py$/" in m["managerFilePatterns"] and m.get("datasourceTemplate") == "github-release-attachments"
    ]
    text = (ROOT / "installer" / "linux" / "franca_install.py").read_text(encoding="utf-8")
    (match,) = re.finditer(manager["matchStrings"][0].replace("(?<", "(?P<"), text)
    version = re.search(r"COSIGN_URL = \".*/download/(v[^/]+)/", text)
    digest = re.search(r'COSIGN_SHA256 = "([0-9a-f]{64})"', text)
    assert version is not None and digest is not None
    assert (match["depName"], match["currentValue"], match["currentDigest"]) == ("sigstore/cosign", version[1], digest[1])


def test_updates_to_the_pinned_programs_wait_for_a_review() -> None:
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    (rule,) = [r for r in config["packageRules"] if "gitleaks/gitleaks" in r.get("matchDepNames", [])]
    assert rule["automerge"] is False
    assert rule["addLabels"]
    found = renovate_matches(ip.PROGRAMS.read_text(encoding="utf-8"))
    dependencies = {name for matches in found.values() for name, _, _ in matches} | {"sigstore/cosign"}
    assert dependencies == set(rule["matchDepNames"])
    assert set(rule["matchFileNames"]) == {"tools/programs.txt", "installer/**"}


def test_the_socket_proxy_waits_for_a_review() -> None:
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    rules = [r for r in config["packageRules"] if "lscr.io/linuxserver/socket-proxy" in r.get("matchPackageNames", [])]
    assert any(r.get("automerge") is False for r in rules)
