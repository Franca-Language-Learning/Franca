"""Tests for the content guard (story E01-014).

The guard is run by the Git hooks and the pipeline, to keep course material, media, harvested text, learner data
and secrets out of the public repository. The tests in the second half make a small Git repository in a temporary
folder and run the guard as the hooks run it, with  python -I.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

GUARD_PATH = Path(__file__).resolve().parents[1] / "content_guard.py"
_spec = importlib.util.spec_from_file_location("content_guard", GUARD_PATH)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["content_guard"] = guard  # dataclasses look the module up by name
_spec.loader.exec_module(guard)

NONE = guard.NO_FINGERPRINTS
MARKER = "franca:" + "private"  # in two parts so this file does not have the marker itself
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP3 = b"ID3\x04" + b"\x00" * 64
LONG_LINE = "Dit is een lange zin uit een privé lesbestand die niet publiek mag worden."
KEY = b"test-key"


def check(path: str, data: bytes = b"plain text\n", prints: object = NONE) -> list[str]:
    return guard.check_file(path, data, prints)


# --- paths


@pytest.mark.parametrize(
    "path",
    [
        "packs/nl-be/course/u05-l03.lesson.yaml",
        "Packs/nl/u01.yaml",
        "server/packs/nl/u01.yaml",
        "content/harvest/source-01.txt",
        "media/pictures/de-kaas.webp",
        "tools/harvest/notes.txt",
        "learner-data/backup.sqlite",
        "server/franca.db",
        "data/app.DB",
        ".env",
        ".env.local",
        "client/.env.production.local",
        "infra/prod.env",
        "infra/secrets/google-client-secret.txt",
        "infra/tls/server.pem",
        ".gitmodules",
        ".envrc",
        "infra/tls/server.crt",
        "packs/nl-be/CLAUDE.md",  # notes inside a real pack are private like the rest of it
    ],
)
def test_private_paths_are_refused(path: str) -> None:
    assert check(path)


@pytest.mark.parametrize(
    "path",
    [
        "packs/fixture/course/u05-l03.lesson.yaml",
        "packs/CLAUDE.md",  # the notes about the packs folder
        "server/src/franca/api/app.py",
        "docs/repository-split.md",
        ".env.example",
        "client/src/media/Player.tsx",  # "media" is a private folder at the top level only
        "server/src/franca/catalogue/content.py",
    ],
)
def test_public_paths_are_allowed(path: str) -> None:
    assert check(path) == []


# --- media


@pytest.mark.parametrize(
    "path", ["docs/a.jpg", "docs/a.MP3", "x/y.epub", "x/y.pdf", "x/y.srt", "x/y.webm", "x/y.docx", "x/y.tar.bz2", "x/y.whl"]
)
def test_media_document_and_archive_types_are_refused_by_extension(path: str) -> None:
    assert check(path, b"x")


@pytest.mark.parametrize(
    "data",
    [
        JPEG,
        PNG,
        MP3,
        b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        b"OggS" + b"\x00" * 20,
        b"%PDF-1.7\n",
        b"\xff\xf1\x50\x80" + b"\x00" * 20,  # AAC
        b"Rar!\x1a\x07\x00",
        b"BZh91AY&SY",
        b"\xfd7zXZ\x00\x00",
        b"\x00" * 257 + b"ustar\x0000",
        b"SQLite format 3\x00",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8,  # old Office document
        b"II*\x00" + b"\x00" * 8,  # TIFF
        b"WEBVTT\n\n00:00.000 --> 00:01.000\n",
    ],
)
def test_media_is_refused_by_its_first_bytes_whatever_the_name(data: bytes) -> None:
    assert any("whatever its name" in p for p in check("docs/notes.txt", data))


def test_an_icon_in_an_allowed_folder_is_accepted() -> None:
    assert check("client/public/icons/icon-192.png", PNG) == []


@pytest.mark.parametrize(
    "path,data",
    [
        ("client/public/icons/icon-192.png", b"PK\x03\x04" + b"\x00" * 20),  # a ZIP named .png
        ("client/public/favicon.ico", MP3),
        ("docs/images/course/u01/kaas.png", PNG),  # * does not match across folders
    ],
)
def test_allowed_folders_accept_real_icons_only(path: str, data: bytes) -> None:
    assert check(path, data)


@pytest.mark.parametrize("uri", [b"data:image/jpeg;base64,/9j/4AAQ", b"data:image/jpeg;name=a.jpg;base64,/9j/", b"data:;base64,/9j/"])
def test_an_svg_with_an_embedded_photo_is_refused(uri: bytes) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="' + uri + b'"/></svg>'
    assert check("docs/erd/diagram.svg", svg)


def test_a_plain_svg_is_accepted() -> None:
    assert check("docs/erd/diagram.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1"/></svg>') == []


def test_a_git_lfs_pointer_is_refused() -> None:
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12345\n"
    assert check("docs/video.txt", pointer)


# --- marker, size and secrets


def test_the_private_marker_is_refused() -> None:
    assert any("marker" in p for p in check("docs/x.md", f"# {MARKER}\nhello\n".encode()))


def test_files_over_the_size_limit_are_refused() -> None:
    assert any("larger" in p for p in check("docs/big.txt", b"a\n" * (guard.MAX_BYTES // 2 + 1)))


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-" + "api03-" + "A" * 40,
        "ghp_" + "a1" * 18,
        "github_pat_" + "B" * 50,
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "AIza" + "x" * 35,
        "GOCSPX-" + "y" * 28,
        "tskey-auth-" + "k" * 20,
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    ],
)
def test_secrets_in_a_file_are_refused(secret: str) -> None:
    data = f'API_KEY = "{secret}"\n'.encode()
    assert any("looks like" in p for p in check("server/src/franca/settings.py", data))


def test_the_guard_does_not_refuse_its_own_source() -> None:
    assert check("tools/content_guard.py", GUARD_PATH.read_bytes()) == []


# --- fingerprints


def prints_of(*lines: str, files: tuple[bytes, ...] = ()) -> object:
    fp = guard.Fingerprints(key=KEY, values=frozenset())
    values = {v for line in lines for v in fp.of_line(line)} | {fp.of_file(f) for f in files}
    return guard.Fingerprints(key=KEY, values=frozenset(values))


def test_a_line_copied_from_the_private_repository_is_refused() -> None:
    data = f"x = 1\n  {LONG_LINE.upper()}  \n".encode()  # case and spacing do not matter
    assert any("private repository" in p for p in check("server/src/franca/x.py", data, prints_of(LONG_LINE)))


def test_a_file_copied_from_the_private_repository_is_refused() -> None:
    data = b"a file of more than sixty-four bytes, so that it is fingerprinted as a whole\n"
    assert check("docs/x.txt", data, prints_of(files=(data,)))


def test_small_files_are_not_compared_as_whole_files() -> None:
    assert check("server/src/franca/py.typed", b"", prints_of(files=(b"",))) == []


def test_a_pack_sentence_pasted_into_code_as_a_string_is_refused() -> None:
    data = f'GREETING = "{LONG_LINE}"\n'.encode()
    assert check("server/src/franca/x.py", data, prints_of(f"  - prompt: {LONG_LINE}"))


def test_short_lines_are_not_fingerprinted() -> None:
    assert guard.Fingerprints(key=KEY, values=frozenset()).of_line("de kaas") == set()


def test_fingerprints_depend_on_the_key() -> None:
    a = guard.Fingerprints(key=b"one", values=frozenset()).of_line(LONG_LINE)
    b = guard.Fingerprints(key=b"two", values=frozenset()).of_line(LONG_LINE)
    assert a and b and not a & b


def content_checkout(root: Path, files: dict[str, str]) -> Path:
    """A made-up checkout of franca-content: a Git repository in root with these files added to the index."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
        git(root, "add", "--", name)
    return root


def public_checkout(root: Path, files: dict[str, str]) -> Path:
    """A made-up checkout of franca: the guard's own file and these files, committed, with origin/main at the commit
    as after a git fetch."""
    content_checkout(root, {"tools/content_guard.py": "# a stand-in for the guard\n", **files})
    git(root, "commit", "-q", "-m", "start")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def text_with_long_lines(line: str = LONG_LINE) -> str:
    """Text that is fingerprinted as a whole file and line by line, if the file is fingerprinted at all."""
    return f"prompt: {line}\nanswer: {line[::-1]}\n"


def values_of(text: str) -> set[str]:
    """The values of a text file: the whole file and its long lines."""
    fp = guard.Fingerprints(key=KEY, values=frozenset())
    return {v for line in text.splitlines() for v in fp.of_line(line)} | {fp.of_file(text.encode())}


def test_fingerprints_are_made_from_a_content_folder(tmp_path: Path) -> None:
    root = content_checkout(tmp_path / "content", {"course/lesson.yaml": f"title: x\nprompt: {LONG_LINE}\n"})
    values = guard.make_fingerprints(root, KEY)
    fp = guard.Fingerprints(key=KEY, values=frozenset())
    assert fp.of_line(LONG_LINE) <= values
    assert fp.of_file((root / "course" / "lesson.yaml").read_bytes()) in values


def test_planner_settings_and_keys_are_not_fingerprinted(tmp_path: Path) -> None:
    # The fixture pack has the real planner settings, so that the tests use them. The key file is not content.
    root = content_checkout(
        tmp_path / "content",
        {
            "packs/nl-be/course-config.yaml": f"warmup:\n  bridge_min: 3   # {LONG_LINE}\n",
            "secrets/fingerprint-key": "a" * 64 + "\n",
        },
    )
    assert guard.make_fingerprints(root, KEY) == set()


def test_untracked_files_and_the_virtual_environment_are_not_fingerprinted(tmp_path: Path) -> None:
    # After uv sync, a checkout has a .venv folder with thousands of files, and some of their lines are the same as
    # lines in this repository. Files that Git does not track are left out.
    lesson = f"prompt: {LONG_LINE}\n"
    root = content_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson})
    other = "Een andere lange zin die alleen in een bestand buiten Git staat, niet in de index."
    for name in ("notes.yaml", ".venv/lib/python3.12/site-packages/x/schema.json", ".pytest_cache/README.md"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text_with_long_lines(other), encoding="utf-8")
    assert guard.make_fingerprints(root, KEY) == values_of(lesson)


def test_a_tracked_link_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text(text_with_long_lines(), encoding="utf-8")
    root = content_checkout(tmp_path / "content", {})
    (root / "packs").mkdir()
    (root / "packs" / "link.yaml").symlink_to(outside)
    git(root, "add", "packs/link.yaml")
    assert guard.make_fingerprints(root, KEY) == set()


NOT_FINGERPRINTED_PATHS = ["secrets/fingerprint-key", "secrets/sub/other-key", "course-config.yaml", "packs/nl-be/course-config.yaml"]


@pytest.mark.parametrize("path", NOT_FINGERPRINTED_PATHS)
def test_paths_in_not_fingerprinted_are_left_out(tmp_path: Path, path: str) -> None:
    root = content_checkout(tmp_path / "content", {path: text_with_long_lines()})
    assert guard.make_fingerprints(root, KEY) == set()


FINGERPRINTED_PATHS = [
    # Tooling and notes at the top of franca-content are fingerprinted like the rest. Lines that are also in this
    # repository are left out with --public instead.
    ".github/workflows/check.yml",
    ".githooks/pre-commit",
    "scripts/check",
    "tools/refresh.py",
    "tests/fixtures/lesson.yaml",
    "docs/notes.md",
    "docs/sub/deeper.md",
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    ".gitattributes",
    ".gitignore",
    "franca-schemas-commit.txt",
    "packs/nl-be/README.md",
    "packs/nl-be/tools/words.yaml",
    "packs/secrets.md",
    "Secrets/notes.md",  # Git records Secrets/ as a different folder when no secrets/ folder is tracked
    "harvest/scripts/source.txt",
    "course-config.yaml.bak",
]


@pytest.mark.parametrize("path", FINGERPRINTED_PATHS)
def test_files_outside_not_fingerprinted_are_fingerprinted(tmp_path: Path, path: str) -> None:
    text = text_with_long_lines()
    root = content_checkout(tmp_path / "content", {path: text})
    assert guard.Fingerprints(key=KEY, values=frozenset()).of_file(text.encode()) in guard.make_fingerprints(root, KEY)


@pytest.mark.parametrize("path", ["secrets/../packs/nl-be/lesson.yaml", "./secrets/key", "/secrets/key", "secrets//key", "secrets/./key"])
def test_a_path_with_dots_or_empty_parts_is_fingerprinted(path: str) -> None:
    # git ls-files does not give such paths. If one came from somewhere else, it is not left out as part of secrets/.
    assert guard.is_fingerprinted(path)


# --- files that are tracked but not in the work tree


def committed_checkout(root: Path, files: dict[str, str]) -> Path:
    content_checkout(root, files)
    git(root, "commit", "-q", "-m", "start")
    return root


def test_a_file_in_a_folder_left_out_by_a_sparse_checkout_is_fingerprinted(tmp_path: Path) -> None:
    lesson = text_with_long_lines()
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson, "packs/fr/lesson.yaml": "x: 1\n"})
    git(root, "sparse-checkout", "set", "packs/fr")
    assert not (root / "packs" / "nl-be" / "lesson.yaml").exists()
    assert values_of(lesson) <= guard.make_fingerprints(root, KEY)


def test_a_tracked_file_deleted_from_the_work_tree_is_fingerprinted(tmp_path: Path) -> None:
    lesson = text_with_long_lines()
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson})
    (root / "packs" / "nl-be" / "lesson.yaml").unlink()
    assert guard.make_fingerprints(root, KEY) == values_of(lesson)
    assert guard.unstaged_changes(root) == ["packs/nl-be/lesson.yaml"]


def test_a_skip_worktree_file_removed_from_the_work_tree_is_fingerprinted(tmp_path: Path) -> None:
    lesson = text_with_long_lines()
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson})
    git(root, "update-index", "--skip-worktree", "packs/nl-be/lesson.yaml")
    (root / "packs" / "nl-be" / "lesson.yaml").unlink()
    assert guard.make_fingerprints(root, KEY) == values_of(lesson)


def test_the_staged_version_is_fingerprinted_and_unstaged_changes_are_named(tmp_path: Path) -> None:
    lesson = text_with_long_lines()
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson})
    (root / "packs" / "nl-be" / "lesson.yaml").write_text(text_with_long_lines("Een nieuwe zin die nog niet in de index van Git staat."))
    assert guard.make_fingerprints(root, KEY) == values_of(lesson)
    assert guard.unstaged_changes(root) == ["packs/nl-be/lesson.yaml"]


def test_the_fingerprint_command_stops_for_a_submodule(tmp_path: Path) -> None:
    other = committed_checkout(tmp_path / "other", {"lesson.yaml": text_with_long_lines()})
    sha = git(other, "rev-parse", "HEAD").strip()
    root = content_checkout(tmp_path / "content", {"packs/fr/lesson.yaml": "x: 1\n"})
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{sha},packs/nl-be")
    with pytest.raises(guard.GuardError, match=r"submodule.*packs/nl-be"):
        guard.make_fingerprints(root, KEY)


def test_the_fingerprint_command_stops_for_a_merge_conflict(tmp_path: Path) -> None:
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": "a: 1\n"})
    git(root, "checkout", "-q", "-b", "other")
    (root / "packs" / "nl-be" / "lesson.yaml").write_text("a: 2\n")
    git(root, "commit", "-q", "-am", "two")
    git(root, "checkout", "-q", "main")
    (root / "packs" / "nl-be" / "lesson.yaml").write_text("a: 3\n")
    git(root, "commit", "-q", "-am", "three")
    git(root, "merge", "-q", "other", check=False)  # the merge stops with a conflict
    assert git(root, "ls-files", "--unmerged")
    with pytest.raises(guard.GuardError, match=r"merge conflict.*packs/nl-be/lesson\.yaml"):
        guard.make_fingerprints(root, KEY)


@pytest.mark.parametrize("variable", ["GIT_INDEX_FILE", "GIT_DIR"])
def test_git_variables_from_a_hook_do_not_change_the_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    # Git hooks run with GIT_INDEX_FILE and GIT_DIR. They belong to the repository of the hook, not to franca-content.
    lesson = text_with_long_lines()
    root = committed_checkout(tmp_path / "content", {"packs/nl-be/lesson.yaml": lesson})
    other = committed_checkout(tmp_path / "other", {"notes.md": "x\n"})
    monkeypatch.setenv(variable, str(other / ".git" / ("index" if variable == "GIT_INDEX_FILE" else "")))
    assert guard.make_fingerprints(root, KEY) == values_of(lesson)


def test_the_fingerprint_command_needs_a_git_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # With GIT_CEILING_DIRECTORIES, Git does not look for a checkout above the temporary folder. That matters when TMPDIR
    # is inside a checkout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "lesson.yaml").write_text(text_with_long_lines(), encoding="utf-8")
    with pytest.raises(guard.GuardError, match="not a Git checkout") as error:
        guard.make_fingerprints(folder, KEY)
    assert "not a git repository" in str(error.value)  # Git's own reason
    env = {"FRANCA_FINGERPRINT_KEY": "test", "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    result = run_guard(tmp_path, "--fingerprint", str(folder), "--skip-public", env=env)
    assert result.returncode == 2
    assert "not a Git checkout" in result.stderr
    assert result.stdout == ""


def test_the_fingerprint_command_needs_the_top_folder_of_the_checkout(tmp_path: Path) -> None:
    # Paths are matched from the root of the checkout, so the paths from a subfolder would be wrong.
    root = content_checkout(tmp_path / "content", {"packs/docs/notes.md": text_with_long_lines()})
    with pytest.raises(guard.GuardError, match="top folder"):
        guard.make_fingerprints(root / "packs", KEY)


# --- the fingerprint command, with the values that are also in the public repository left out


WORKFLOW_LINE = "      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2"
WORKFLOW = f"jobs:\n  check:\n    steps:\n{WORKFLOW_LINE}\n"
LESSON = text_with_long_lines()
SETUP = f"{WORKFLOW_LINE}\n"


SETUP_PATH = ".github/workflows/release.yml"


def private_values() -> set[str]:
    """The values that are kept when the public checkout of the fixture is left out: the lesson, and the second workflow
    as a whole file, because only its line is public."""
    return values_of(LESSON) | {guard.Fingerprints(key=KEY, values=frozenset()).of_file(SETUP.encode())}


def fingerprint_command(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_guard(cwd, "--fingerprint", ".", *args, env={"FRANCA_FINGERPRINT_KEY": KEY.decode()})


def written_values(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == guard.FINGERPRINT_HEADER
    return set(lines[1:])


@pytest.fixture
def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    """A made-up franca-content with a lesson and two tooling files, and a made-up franca with the same workflow line."""
    content = committed_checkout(
        tmp_path / "content", {"packs/nl-be/lesson.yaml": LESSON, ".github/workflows/check.yml": WORKFLOW, SETUP_PATH: SETUP}
    )
    public = public_checkout(
        tmp_path / "franca", {".github/workflows/check.yml": WORKFLOW, "scripts/pins.py": f"PIN = '''\n{WORKFLOW_LINE}\n'''\n"}
    )
    return content, public


def test_values_that_are_also_in_the_public_checkout_are_left_out(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    output = tmp_path / "prints.txt"
    result = fingerprint_command(content, "--public", str(public), "--output", str(output))
    assert result.returncode == 0, result.stderr
    assert written_values(output) == private_values()
    assert result.stdout == ""


def test_the_left_out_values_are_reported_by_path_without_their_text(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    result = fingerprint_command(content, "--public", str(public), "--output", str(tmp_path / "prints.txt"))
    report = result.stderr
    assert "  .github/workflows/check.yml is a copy of .github/workflows/check.yml\n" in report
    assert f"  .github/workflows/check.yml has lines that are in {SETUP_PATH}\n" in report
    assert "  scripts/pins.py has lines that are in .github/workflows/check.yml\n" in report
    assert "packs/nl-be/lesson.yaml" not in report
    assert "actions/checkout" not in report and LONG_LINE not in report


def test_the_fingerprint_command_stops_without_the_public_checkout(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, _ = checkouts
    output = tmp_path / "prints.txt"
    result = fingerprint_command(content, "--output", str(output))
    assert result.returncode == 2
    assert "--public" in result.stderr and "--skip-public" in result.stderr
    assert not output.exists()
    result = fingerprint_command(content, "--skip-public", "--output", str(output))
    assert result.returncode == 0, result.stderr
    assert values_of(LESSON) | values_of(WORKFLOW) <= written_values(output)


def test_public_and_skip_public_cannot_be_used_together(checkouts: tuple[Path, Path]) -> None:
    content, public = checkouts
    assert fingerprint_command(content, "--public", str(public), "--skip-public").returncode == 2
    result = fingerprint_command(content, "--skip-public", "--public-ref", "main")
    assert result.returncode == 2
    assert "--public-ref can be used with --public only" in result.stderr


@pytest.mark.parametrize("option", [("--public", "."), ("--skip-public",), ("--output", "x.txt"), ("--public-ref", "main")])
def test_the_fingerprint_options_need_the_fingerprint_command(repo: Path, option: tuple[str, ...]) -> None:
    result = run_guard(repo, "--index", *option)
    assert result.returncode == 2
    assert "--fingerprint" in result.stderr


def test_the_public_checkout_must_not_be_the_content_checkout(checkouts: tuple[Path, Path]) -> None:
    content, _ = checkouts
    result = fingerprint_command(content, "--public", ".")
    assert result.returncode == 2
    assert "same checkout" in result.stderr


def test_the_public_checkout_must_be_a_checkout_of_franca(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, _ = checkouts
    other = committed_checkout(tmp_path / "other", {"notes.md": "x\n"})
    git(other, "update-ref", "refs/remotes/origin/main", "HEAD")
    result = fingerprint_command(content, "--public", str(other))
    assert result.returncode == 2
    assert "tools/content_guard.py" in result.stderr


def test_a_run_that_fingerprints_nothing_is_an_error(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"secrets/fingerprint-key": "a" * 64 + "\n"})
    output = tmp_path / "prints.txt"
    result = fingerprint_command(content, "--skip-public", "--output", str(output))
    assert result.returncode == 2
    assert "No files were fingerprinted" in result.stderr
    assert not output.exists()


def test_a_run_whose_values_are_all_public_is_an_error(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {".github/workflows/check.yml": WORKFLOW})
    public = public_checkout(tmp_path / "franca", {".github/workflows/check.yml": WORKFLOW})
    result = fingerprint_command(content, "--public", str(public), "--output", str(tmp_path / "prints.txt"))
    assert result.returncode == 2
    assert "also in the public checkout" in result.stderr


def test_a_failed_refresh_does_not_change_the_fingerprint_file(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    output = tmp_path / "prints.txt"
    output.write_text(f"{guard.FINGERPRINT_HEADER}\nline:0123456789abcdef01234567\n", encoding="utf-8")
    before = output.read_bytes()
    result = run_guard(
        content / "packs",
        "--fingerprint",
        ".",
        "--public",
        str(public),
        "--output",
        str(output),
        env={"FRANCA_FINGERPRINT_KEY": KEY.decode()},
    )
    assert result.returncode == 2
    assert "top folder" in result.stderr
    assert output.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["content", "franca", "prints.txt"]  # no temporary file is left


def test_a_refresh_replaces_the_fingerprint_file(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    output = tmp_path / "prints.txt"
    output.write_text(f"{guard.FINGERPRINT_HEADER}\nline:0123456789abcdef01234567\n", encoding="utf-8")
    assert fingerprint_command(content, "--public", str(public), "--output", str(output)).returncode == 0
    assert written_values(output) == private_values()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["content", "franca", "prints.txt"]


def test_unstaged_changes_are_named_by_the_fingerprint_command(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    (content / "packs" / "nl-be" / "lesson.yaml").write_text("x: 2\n")
    result = fingerprint_command(content, "--public", str(public), "--output", str(tmp_path / "prints.txt"))
    assert result.returncode == 0, result.stderr
    assert "not staged" in result.stderr and "packs/nl-be/lesson.yaml" in result.stderr


# --- the public values: read from origin/main, from a checkout of franca and not of franca-content


SENTENCE = "Dit is een verzonnen lange zin uit een proefles die nergens anders staat, nummer een."


def refresh(content: Path, public: Path, ref: str = guard.DEFAULT_PUBLIC_REF) -> tuple[set[str] | None, str]:
    """Runs the refresh in this process. Gives the values, or None when it stopped, and what was printed or the error."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            guard.refresh_fingerprints(content, public, None, KEY, public_ref=ref)
    except guard.GuardError as error:
        return None, f"{err.getvalue()}{error}"
    return {line for line in out.getvalue().splitlines() if not line.startswith("#")}, err.getvalue()


@pytest.fixture
def lesson_checkout(tmp_path: Path) -> Path:
    """A made-up franca-content with one lesson sentence."""
    return committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})


def sentence_kept(values: set[str] | None) -> bool:
    return values is not None and guard.Fingerprints(key=KEY, values=frozenset()).of_line(SENTENCE) <= values


@pytest.mark.parametrize(
    "path,text",
    [
        ("docs/x.md", f"{SENTENCE}\n"),  # a course line that is already public
        ("server/x.py", f"msg = '{SENTENCE}'  # comment\n"),  # pasted into code as a string
        ("docs/y.md", f"  {SENTENCE.upper()}   \n"),  # in upper case, with extra spaces
    ],
)
def test_the_refresh_stops_for_a_course_line_in_a_public_file(lesson_checkout: Path, tmp_path: Path, path: str, text: str) -> None:
    public = public_checkout(tmp_path / "franca", {path: text})
    values, message = refresh(lesson_checkout, public)
    assert values is None
    assert f"{path} has lines that are in packs/nl/l.yaml" in message
    assert "product owner" in message
    assert SENTENCE not in message and SENTENCE.upper() not in message


SCHEMA_COMMENT = "# yaml-language-server: $schema=../../spec/lesson.schema.json"


def test_a_comment_line_of_a_lesson_in_the_public_fixture_pack_is_left_out_with_a_notice(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"{SCHEMA_COMMENT}\nprompt: {SENTENCE}\n"})
    public = public_checkout(tmp_path / "franca", {"packs/fixture/l.yaml": f"{SCHEMA_COMMENT}\n"})
    values, message = refresh(content, public)
    assert sentence_kept(values)
    assert not guard.Fingerprints(key=KEY, values=frozenset()).of_line(SCHEMA_COMMENT) & (values or set())
    assert "one comment line of a file of franca-content is in the fixture pack" in message
    assert "packs/fixture/l.yaml has lines that are in packs/nl/l.yaml" in message


def test_the_same_comment_line_of_many_lessons_in_the_fixture_pack_is_left_out_with_a_notice(tmp_path: Path) -> None:
    lessons = {f"packs/nl/u{i}.yaml": f"{SCHEMA_COMMENT}\nprompt: {SENTENCE} {i}\n" for i in range(8)}
    content = committed_checkout(tmp_path / "content", lessons)
    public = public_checkout(tmp_path / "franca", {"packs/fixture/l.yaml": f"{SCHEMA_COMMENT}\n"})
    values, message = refresh(content, public)
    assert values is not None, message
    for path in lessons:
        assert f"packs/fixture/l.yaml has lines that are in {path}" in message


def made_up_line(number: int) -> str:
    return f"Dit is een verzonnen lange zin uit een proefles die nergens anders staat, nummer {number}."


EIGHT_LESSONS = {f"packs/nl/u{i}.yaml": f"prompt: {made_up_line(10 + i)}\nanswer: {made_up_line(50 + i)}\n" for i in range(8)}
FLOW_LIST_SENTENCES = [made_up_line(30), made_up_line(31), made_up_line(32)]
FLOW_LIST_LINE = 'examples: ["' + '", "'.join(FLOW_LIST_SENTENCES) + '"]\n'


@pytest.mark.parametrize(
    "lessons,fixture_files",
    [
        # one line of each of eight lessons, in eight fixture files (probe Q4)
        (EIGHT_LESSONS, {f"packs/fixture/f{i}.yaml": f"prompt: {made_up_line(10 + i)}\n" for i in range(8)}),
        # one line of each of eight lessons, all in one fixture file (probe Q4b)
        (EIGHT_LESSONS, {"packs/fixture/all.yaml": "".join(f"prompt: {made_up_line(10 + i)}\n" for i in range(8))}),
        # one lesson line with three sentences in a YAML flow list, copied whole (probe Q6)
        ({"packs/nl/l.yaml": f"{FLOW_LIST_LINE}prompt: {made_up_line(33)}\n"}, {"packs/fixture/a.yaml": FLOW_LIST_LINE}),
        # the three sentences of that line as three fixture lines (probe Q6b)
        (
            {"packs/nl/l.yaml": f"{FLOW_LIST_LINE}prompt: {made_up_line(33)}\n"},
            {"packs/fixture/a.yaml": "".join(f'- "{s}"\n' for s in FLOW_LIST_SENTENCES)},
        ),
        # a line that starts with # in a YAML block scalar is text, not a comment
        (
            {"packs/nl/l.yaml": f"text: |\n  # {made_up_line(40)}\nprompt: {made_up_line(41)}\n"},
            {"packs/fixture/a.yaml": f"# {made_up_line(40)}\n"},
        ),
        # a Markdown heading is text, not a comment
        ({"packs/nl/l.md": f"# {made_up_line(42)}\n\n{made_up_line(43)}\n"}, {"packs/fixture/a.yaml": f"# {made_up_line(42)}\n"}),
    ],
)
def test_the_refresh_stops_for_a_line_of_a_lesson_that_is_not_a_comment_in_the_fixture_pack(
    tmp_path: Path, lessons: dict[str, str], fixture_files: dict[str, str]
) -> None:
    content = committed_checkout(tmp_path / "content", lessons)
    public = public_checkout(tmp_path / "franca", fixture_files)
    values, message = refresh(content, public)
    assert values is None
    for path in lessons:
        assert f" has lines that are in {path}\n" in message
    assert "product owner" in message and "comment line" in message
    assert "Dit is een verzonnen" not in message


SECOND_SENTENCE = "Een tweede verzonnen zin uit dezelfde proefles, die ook nergens anders te vinden is."


@pytest.mark.parametrize(
    "fixture_files",
    [
        {"packs/fixture/l.yaml": f"prompt: {SENTENCE}\nanswer: {SECOND_SENTENCE}\n"},  # a whole-file copy
        {"packs/fixture/l.yaml": f"title: x\nprompt: {SENTENCE}\nanswer: {SECOND_SENTENCE}\n"},  # two lines in one file
        {"packs/fixture/a.yaml": f"prompt: {SENTENCE}\n", "packs/fixture/b.yaml": f"answer: {SECOND_SENTENCE}\n"},  # one in each
    ],
)
def test_the_refresh_stops_for_more_than_one_line_of_a_course_file_in_the_fixture_pack(
    tmp_path: Path, fixture_files: dict[str, str]
) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\nanswer: {SECOND_SENTENCE}\n"})
    public = public_checkout(tmp_path / "franca", fixture_files)
    values, message = refresh(content, public)
    assert values is None
    for path in fixture_files:
        assert f"  {path} " in message and "packs/nl/l.yaml" in message
    assert "product owner" in message
    assert SENTENCE not in message and SECOND_SENTENCE not in message


def test_the_refresh_stops_for_two_comment_lines_of_a_course_file_in_the_fixture_pack(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"# {SENTENCE}\n# {SECOND_SENTENCE}\nprompt: x\n"})
    public = public_checkout(tmp_path / "franca", {"packs/fixture/l.yaml": f"# {SENTENCE}\n# {SECOND_SENTENCE}\n"})
    values, message = refresh(content, public)
    assert values is None
    assert "packs/fixture/l.yaml has lines that are in packs/nl/l.yaml" in message


def test_the_refresh_stops_for_a_whole_course_file_of_one_line_in_the_fixture_pack(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    public = public_checkout(tmp_path / "franca", {"packs/fixture/l.yaml": f"prompt: {SENTENCE}\n"})
    values, message = refresh(content, public)
    assert values is None
    assert "packs/fixture/l.yaml is a copy of packs/nl/l.yaml" in message


@pytest.mark.parametrize("private_path", ["tests/fixtures/lesson.yaml", "notes/lesson-ideas.md", "docs/setup.md", "README.md"])
def test_the_refresh_stops_for_text_of_a_file_outside_the_tooling_list_in_a_public_file(tmp_path: Path, private_path: str) -> None:
    # Course text can be in any folder of franca-content, so only the files in TOOLING_PATHS may share text with franca.
    content = committed_checkout(tmp_path / "content", {private_path: f"prompt: {SENTENCE}\n", "packs/nl/l.yaml": LESSON})
    public = public_checkout(tmp_path / "franca", {"docs/a.md": f"{SENTENCE}\n"})
    values, message = refresh(content, public)
    assert values is None
    assert f"docs/a.md has lines that are in {private_path}" in message
    assert "TOOLING_PATHS" in message


@pytest.mark.parametrize(
    "path,expected",
    [
        (".github/workflows/check.yml", True),
        (".github/renovate.json", True),
        (".github/ISSUE_TEMPLATE/lesson.yaml", False),
        (".github/lesson.yaml", False),
        (".github/actions/setup/action.yml", False),
        (".github/workflows", False),
        ("pyproject.toml", True),
        ("uv.lock", True),
        ("renovate.json", True),
        (".gitattributes", True),
        (".gitignore", True),
        ("server/pyproject.toml", False),
        ("packs/nl/.gitignore", False),
        ("notes/.github/x.md", False),
        (".GITHUB/workflows/check.yml", False),
        ("pyproject.toml.orig", False),
        ("docs/setup.md", False),
    ],
)
def test_the_tooling_list_names_folders_and_files_from_the_top_of_the_checkout(path: str, expected: bool) -> None:
    assert guard.is_tooling(path) is expected


def test_the_tooling_list_is_named_in_the_docs() -> None:
    docs = (GUARD_PATH.parents[1] / "docs" / "repository-split.md").read_text(encoding="utf-8")
    assert "TOOLING_PATHS" in docs
    for rule in guard.TOOLING_PATHS:
        assert f"`{rule}`" in docs, rule


def test_a_tooling_file_that_is_in_the_public_commit_is_left_out_with_a_notice(checkouts: tuple[Path, Path]) -> None:
    content, public = checkouts
    values, message = refresh(content, public)
    assert values == private_values()
    assert "tooling file of franca-content" in message
    assert "  .github/workflows/check.yml is a copy of .github/workflows/check.yml\n" in message


@pytest.mark.parametrize(
    "private_path",
    [
        ".github/ISSUE_TEMPLATE/lesson.yaml",  # probe Q1
        ".github/lesson.yaml",  # where Git records .GitHub/lesson.yaml when core.ignorecase is true (probe Q2)
    ],
)
def test_the_refresh_stops_for_course_text_of_other_github_files_in_a_public_file(tmp_path: Path, private_path: str) -> None:
    content = committed_checkout(tmp_path / "content", {private_path: f"prompt: {SENTENCE}\n", ".github/workflows/check.yml": WORKFLOW})
    public = public_checkout(tmp_path / "franca", {"docs/a.md": f"{SENTENCE}\n"})
    values, message = refresh(content, public)
    assert values is None
    assert f"docs/a.md has lines that are in {private_path}" in message


def test_the_refresh_stops_for_text_of_a_tooling_file_in_the_public_fixture_pack(tmp_path: Path) -> None:
    # A workflow and the fixture pack are not expected to have text in common (probe Q7).
    content = committed_checkout(tmp_path / "content", {".github/workflows/x.yml": f"run: echo '{SENTENCE}'\n", "packs/nl/l.yaml": LESSON})
    public = public_checkout(tmp_path / "franca", {"packs/fixture/a.yaml": f"x: {SENTENCE}\n"})
    values, message = refresh(content, public)
    assert values is None
    assert "packs/fixture/a.yaml has lines that are in .github/workflows/x.yml" in message


@pytest.mark.parametrize("odd_path", [".GITHUB/workflows/check.yml", ".github/Workflows/check.yml", "PyProject.toml", "UV.LOCK"])
def test_the_refresh_stops_for_a_path_that_differs_from_a_tooling_path_only_in_case(tmp_path: Path, odd_path: str) -> None:
    content = committed_checkout(tmp_path / "content", {odd_path: "x = 1\n", "packs/nl/l.yaml": LESSON})
    public = public_checkout(tmp_path / "franca", {})
    values, message = refresh(content, public)
    assert values is None
    assert odd_path in message and "case" in message
    assert "The fingerprint file was not changed" in message


def test_a_copy_staged_in_the_public_checkout_is_not_public(lesson_checkout: Path, tmp_path: Path) -> None:
    public = public_checkout(tmp_path / "franca", {})
    (public / "notes.md").write_text(f"{SENTENCE}\n")
    git(public, "add", "notes.md")
    (public / "packs" / "nl").mkdir(parents=True)
    (public / "packs" / "nl" / "l.yaml").write_text(f"prompt: {SENTENCE}\n")
    git(public, "add", "-f", "packs/nl/l.yaml")
    values, message = refresh(lesson_checkout, public)
    assert sentence_kept(values), message


def test_a_copy_in_a_local_commit_of_the_public_checkout_is_not_public(lesson_checkout: Path, tmp_path: Path) -> None:
    public = public_checkout(tmp_path / "franca", {})
    git(public, "checkout", "-q", "-b", "feature")
    (public / "draft.py").write_text(f'X = "{SENTENCE}"\n')
    git(public, "add", "draft.py")
    git(public, "commit", "-q", "-m", "draft")
    values, message = refresh(lesson_checkout, public)
    assert sentence_kept(values), message


def test_the_public_commit_must_exist(lesson_checkout: Path, tmp_path: Path) -> None:
    public = committed_checkout(tmp_path / "franca", {"tools/content_guard.py": "# a stand-in for the guard\n"})
    values, message = refresh(lesson_checkout, public)
    assert values is None
    assert "origin/main" in message and "git fetch" in message


def test_the_public_commit_can_be_named(lesson_checkout: Path, tmp_path: Path) -> None:
    public = committed_checkout(tmp_path / "franca", {"tools/content_guard.py": "# a stand-in for the guard\n"})
    values, message = refresh(lesson_checkout, public, ref="main")
    assert sentence_kept(values), message


def test_the_public_commit_is_read_from_the_remote_tracking_ref(lesson_checkout: Path, tmp_path: Path) -> None:
    # A local branch called origin/main is found by Git before refs/remotes/origin/main, so the full name is used.
    assert guard.DEFAULT_PUBLIC_REF == "refs/remotes/origin/main"
    public = public_checkout(tmp_path / "franca", {})
    git(public, "checkout", "-q", "-b", "origin/main")
    (public / "docs").mkdir()
    (public / "docs" / "b.md").write_text(f"{SENTENCE}\n")
    git(public, "add", "docs/b.md")
    git(public, "commit", "-q", "-m", "a local branch with the name of the remote-tracking branch")
    git(public, "checkout", "-q", "main")
    values, message = refresh(lesson_checkout, public)
    assert sentence_kept(values), message


@pytest.mark.parametrize(
    "url",
    [
        "https://someone:made-up-token@example.invalid/franca.git",
        "https://someone:made%40up-token@example.invalid/franca.git",  # an @ in the password, written as it should be
        "https://someone:made@up@token@example.invalid/franca.git",  # a plain @ in the password (probe Q8)
        "https://made-up-token@example.invalid/franca.git",
    ],
)
def test_the_public_commit_and_the_remote_are_printed(lesson_checkout: Path, tmp_path: Path, url: str) -> None:
    public = public_checkout(tmp_path / "franca", {})
    git(public, "remote", "add", "origin", url)
    commit = git(public, "rev-parse", "refs/remotes/origin/main").strip()
    values, message = refresh(lesson_checkout, public)
    assert sentence_kept(values), message
    assert commit in message
    assert "The URL of remote origin is https://example.invalid/franca.git." in message
    for part in ("someone", "made", "token"):
        assert part not in message


def test_a_public_checkout_without_a_remote_url_is_reported(lesson_checkout: Path, tmp_path: Path) -> None:
    values, message = refresh(lesson_checkout, public_checkout(tmp_path / "franca", {}))
    assert sentence_kept(values), message
    assert "Remote origin has no URL" in message


def test_a_content_checkout_that_has_fetched_franca_is_not_a_copy(lesson_checkout: Path, tmp_path: Path) -> None:
    # Only the history of HEAD in franca-content is compared, not the remote-tracking refs it has fetched.
    public = public_checkout(tmp_path / "franca", {})
    git(lesson_checkout, "remote", "add", "franca", str(public))
    git(lesson_checkout, "fetch", "-q", "franca")
    values, message = refresh(lesson_checkout, public)
    assert sentence_kept(values), message


def test_the_refresh_stops_for_a_public_commit_with_a_pack(lesson_checkout: Path, tmp_path: Path) -> None:
    public = public_checkout(tmp_path / "franca", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    values, message = refresh(lesson_checkout, public)
    assert values is None
    assert "packs/nl/l.yaml" in message and "keeps out of franca" in message


def test_an_older_clone_of_franca_content_is_not_a_public_checkout(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n", "tools/content_guard.py": "# a copy\n"})
    git(tmp_path, "clone", "-q", str(content), str(tmp_path / "clone"))
    values, message = refresh(content, tmp_path / "clone")
    assert values is None
    assert "packs/nl/l.yaml" in message


def test_a_clone_of_franca_content_without_packs_is_not_a_public_checkout(tmp_path: Path) -> None:
    # The first commit is the same in both, so the clone is found even without files that the guard keeps out.
    content = committed_checkout(tmp_path / "content", {"docs/notes.md": f"{SENTENCE}\n", "tools/content_guard.py": "# a copy\n"})
    git(tmp_path, "clone", "-q", str(content), str(tmp_path / "clone"))
    (content / "packs" / "nl").mkdir(parents=True)
    (content / "packs" / "nl" / "l.yaml").write_text(f"prompt: {SENTENCE[::-1]}\n")
    git(content, "add", "packs/nl/l.yaml")
    git(content, "commit", "-q", "-m", "more")
    values, message = refresh(content, tmp_path / "clone")
    assert values is None
    assert "start from the same first commit" in message
    assert "history from franca" in message


def test_a_linked_worktree_of_franca_content_is_not_a_public_checkout(tmp_path: Path) -> None:
    content = committed_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n", "tools/content_guard.py": "# a copy\n"})
    git(content, "worktree", "add", "-q", str(tmp_path / "worktree"))
    values, _ = refresh(content, tmp_path / "worktree", ref="HEAD")
    assert values is None


def test_the_public_checkout_is_checked_before_its_files_are_read(
    lesson_checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = public_checkout(tmp_path / "franca", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    read: list[Path] = []
    original = guard._checkout_blobs

    def recording(root: Path, shas: Iterable[str]) -> Iterator[tuple[str, bytes]]:
        read.append(root)
        return original(root, shas)

    monkeypatch.setattr(guard, "_checkout_blobs", recording)
    values, _ = refresh(lesson_checkout, public)
    assert values is None
    assert public not in read


# --- files that are not in the index as their content


def lfs_available() -> bool:
    return subprocess.run(["git", "lfs", "version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not lfs_available(), reason="Git LFS is not installed")
def test_a_file_stored_with_git_lfs_is_fingerprinted_by_its_content(tmp_path: Path) -> None:
    root = content_checkout(tmp_path / "content", {".gitattributes": "*.csv filter=lfs diff=lfs merge=lfs -text\n"})
    git(root, "lfs", "install", "--local")
    words = f"{SENTENCE}\n{SENTENCE[::-1]}\n"
    (root / "packs" / "nl").mkdir(parents=True)
    (root / "packs" / "nl" / "words.csv").write_text(words)
    git(root, "add", "packs/nl/words.csv")
    assert git(root, "cat-file", "-p", ":packs/nl/words.csv").startswith("version https://git-lfs")
    assert values_of(words) <= guard.make_fingerprints(root, KEY)


def test_the_command_stops_for_a_git_lfs_file_whose_content_cannot_be_read(tmp_path: Path) -> None:
    root = content_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    pointer = f"version https://git-lfs.github.com/spec/v1\noid sha256:{'ab' * 32}\nsize 120\n"
    sha = git(root, "hash-object", "-w", "--stdin", stdin=pointer).strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{sha},packs/nl/words.csv")
    with pytest.raises(guard.GuardError, match=r"Git LFS.*packs/nl/words\.csv"):
        guard.make_fingerprints(root, KEY)


def test_a_pointer_with_an_extension_line_is_read_as_a_git_lfs_pointer(tmp_path: Path) -> None:
    root = content_checkout(tmp_path / "content", {"packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    pointer = f"version https://git-lfs.github.com/spec/v1\next-0-foo sha256:{'cd' * 32}\noid sha256:{'ab' * 32}\nsize 120\n"
    sha = git(root, "hash-object", "-w", "--stdin", stdin=pointer).strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{sha},packs/nl/words.csv")
    with pytest.raises(guard.GuardError, match=r"Git LFS.*packs/nl/words\.csv"):
        guard.make_fingerprints(root, KEY)


def add_blob(root: Path, path: str, text: str) -> None:
    """Adds text to the index under path as it is, without the clean filter that git add would run."""
    sha = git(root, "hash-object", "-w", "--stdin", stdin=text).strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{sha},{path}")


LFS_ATTRIBUTES = "*.csv filter=lfs diff=lfs merge=lfs -text\n"


@pytest.mark.parametrize("path", ["packs/nl/words.csv", "packs/nl/a b é.csv"])
def test_a_path_that_uses_the_git_lfs_filter_is_read_with_git_lfs_whatever_its_content(
    tmp_path: Path, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file that was committed before the path was given to Git LFS is not a pointer, but Git asks Git LFS for it.
    root = content_checkout(tmp_path / "content", {".gitattributes": LFS_ATTRIBUTES})
    add_blob(root, path, "plain text that is not a pointer\n")
    asked: list[str] = []
    smudged = f"prompt: {SENTENCE}\n"

    def fake_lfs_content(_root: Path, lfs_path: str, _blob: bytes) -> bytes:
        asked.append(lfs_path)
        return smudged.encode()

    monkeypatch.setattr(guard, "_lfs_content", fake_lfs_content)
    assert values_of(smudged) <= guard.make_fingerprints(root, KEY)
    assert asked == [path]


@pytest.mark.parametrize(
    "blob",
    [
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{'ab' * 32}\nsize 120",  # no newline at the end
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{'ab' * 32}\nsize 120\nx-note: hand-made\n",  # an extra line
        f"version https://hawser.github.com/spec/v1\noid sha256:{'ab' * 32}\nsize 120\n",  # the old name of the format
    ],
)
def test_the_command_stops_for_a_path_that_uses_the_git_lfs_filter_and_cannot_be_read(tmp_path: Path, blob: str) -> None:
    root = content_checkout(tmp_path / "content", {".gitattributes": LFS_ATTRIBUTES, "packs/nl/l.yaml": f"prompt: {SENTENCE}\n"})
    add_blob(root, "packs/nl/words.csv", blob)
    with pytest.raises(guard.GuardError, match=r"Git LFS.*packs/nl/words\.csv"):
        guard.make_fingerprints(root, KEY)


def test_the_git_lfs_paths_are_read_from_the_attributes_in_the_index(tmp_path: Path) -> None:
    root = content_checkout(tmp_path / "content", {".gitattributes": LFS_ATTRIBUTES, "packs/nl/l.yaml": "x: 1\n"})
    add_blob(root, "packs/nl/words.csv", "a,b\n")
    (root / ".gitattributes").write_text("", encoding="utf-8")  # a change in the work tree that is not staged
    assert guard.lfs_paths(root, ["packs/nl/words.csv", "packs/nl/l.yaml"]) == {"packs/nl/words.csv"}


def test_a_text_file_that_starts_like_a_git_lfs_pointer_is_fingerprinted(tmp_path: Path) -> None:
    text = f"version https://git-lfs is how a pointer starts, but this is a lesson.\nprompt: {SENTENCE}\n"
    root = content_checkout(tmp_path / "content", {"packs/nl/odd.md": text})
    assert values_of(text) <= guard.make_fingerprints(root, KEY)


def test_new_files_that_are_not_added_are_named(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    content, public = checkouts
    (content / "packs" / "nl-be" / "new.yaml").write_text(f"prompt: {SENTENCE}\n")
    (content / ".gitignore").write_text("ignored.txt\n")
    (content / "ignored.txt").write_text("x\n")
    assert guard.untracked_files(content) == [".gitignore", "packs/nl-be/new.yaml"]
    result = fingerprint_command(content, "--public", str(public), "--output", str(tmp_path / "prints.txt"))
    assert result.returncode == 0, result.stderr
    assert "not added" in result.stderr and "packs/nl-be/new.yaml" in result.stderr
    assert "ignored.txt" not in result.stderr


# --- the fingerprint file


@pytest.mark.parametrize("text", ["", "\n", f"{guard.FINGERPRINT_HEADER}\n"])
def test_the_guard_stops_for_a_fingerprint_file_without_values(tmp_path: Path, text: str) -> None:
    # When a refresh that was redirected with > stops, the file is left empty. Without this check, copies of course
    # material would pass the guard.
    file = tmp_path / "prints.txt"
    file.write_text(text, encoding="utf-8")
    with pytest.raises(guard.GuardError, match="has no values"):
        guard.load_fingerprints(file, key=KEY)


def test_a_fingerprint_file_that_says_it_has_no_values_is_accepted(tmp_path: Path) -> None:
    file = tmp_path / "prints.txt"
    file.write_text("# No fingerprints in this test.\n", encoding="utf-8")
    assert guard.load_fingerprints(file, key=None) == guard.NO_FINGERPRINTS
    with pytest.raises(guard.GuardError, match="has no values"):
        guard.load_fingerprints(file, key=None, values_expected=True)


def test_the_check_of_a_fork_pull_request_stops_for_an_empty_fingerprint_file(repo: Path, tmp_path: Path) -> None:
    # A pull request from a fork has no key, so the fingerprints are skipped. An emptied file is still an error.
    prints = tmp_path / "prints.txt"
    prints.write_text("", encoding="utf-8")
    base = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "a.txt", b"a\n")
    event = tmp_path / "event.json"
    pr = {"base": {"sha": base, "repo": {"full_name": "org/franca"}}, "head": {"repo": {"full_name": "someone/franca"}}}
    event.write_text(json.dumps({"pull_request": pr}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event)}
    result = run_guard(repo, "--ci", "--fingerprints", str(prints), env=env)
    assert result.returncode == 2
    assert "has no values" in result.stderr


def test_the_fingerprint_file_of_this_repository_has_values() -> None:
    lines = guard.DEFAULT_FINGERPRINTS.read_text(encoding="utf-8").splitlines()
    assert lines[0] == guard.FINGERPRINT_HEADER
    assert [line for line in lines if not line.startswith("#")]


def test_fingerprints_without_a_key_stop_the_guard(tmp_path: Path) -> None:
    file = tmp_path / "prints.txt"
    file.write_text("# header\nline:0123456789abcdef01234567\n")
    with pytest.raises(guard.GuardError, match="key is missing"):
        guard.load_fingerprints(file, key=None)


def test_a_missing_fingerprint_file_stops_the_guard(tmp_path: Path) -> None:
    with pytest.raises(guard.GuardError, match="missing"):
        guard.load_fingerprints(tmp_path / "none.txt", key=KEY)


def test_the_key_is_read_from_the_environment_or_a_file(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("from-file\n")
    assert guard.read_key({"FRANCA_FINGERPRINT_KEY": "from-env"}) == b"from-env"
    assert guard.read_key({"FRANCA_FINGERPRINT_KEY_FILE": str(key_file)}) == b"from-file"
    assert guard.read_key({"FRANCA_FINGERPRINT_KEY_FILE": str(tmp_path / "none")}) is None


def test_the_fingerprint_file_of_this_repository_loads() -> None:
    key = guard.read_key()
    if key is None:
        # The key is an Actions secret that the Content guard job has. That job loads this file with it.
        pytest.skip("No fingerprint key on this computer or in this job")
    guard.load_fingerprints(guard.DEFAULT_FINGERPRINTS, key=key)


# --- the pipeline's choice of commits


@pytest.mark.parametrize(
    "event,ref",
    [
        ({"before": "0" * 40}, "refs/heads/main"),  # first push of a branch
        ({"before": "1" * 40, "created": True}, "refs/heads/new"),
        ({"before": "1" * 40}, "refs/tags/v1"),
        ({"before": "2" * 40}, "refs/heads/main"),  # a base that is not in the repository (force-push)
    ],
)
def test_a_push_without_a_usable_base_checks_the_history_of_the_pushed_commit_only(
    repo: Path, monkeypatch: pytest.MonkeyPatch, event: dict[str, object], ref: str
) -> None:
    # Other branches, such as open pull requests, are checked in their own runs. Checking them here would stop this
    # branch, for example a merge queue branch, for a file on another branch.
    monkeypatch.chdir(repo)
    assert guard.ci_revisions("push", event, ref) == ["HEAD"]


@pytest.mark.parametrize(
    "event_name,event",
    [
        ("schedule", {}),
        ("workflow_dispatch", {}),
        ("merge_group", {"merge_group": {"base_sha": "2" * 40}}),  # a base that is not in the repository
    ],
)
def test_runs_without_a_pushed_commit_or_a_usable_base_check_every_branch_and_tag(
    repo: Path, monkeypatch: pytest.MonkeyPatch, event_name: str, event: dict[str, object]
) -> None:
    monkeypatch.chdir(repo)
    assert guard.ci_revisions(event_name, event, "refs/heads/main") is None


def test_a_force_push_with_a_known_base_checks_the_new_commits(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    before = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "app.py", b"print('hello')\n")
    assert guard.ci_revisions("push", {"before": before, "forced": True}, "refs/heads/main") == ["HEAD", f"^{before}"]


def test_a_new_branch_is_not_stopped_by_a_file_on_another_branch(repo: Path, tmp_path: Path) -> None:
    git(repo, "checkout", "-q", "-b", "other")
    commit(repo, "packs/nl-be/words.yaml", b"words\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "new")
    commit(repo, "app.py", b"print('hello')\n")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40, "created": True}), encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event), "GITHUB_REF": "refs/heads/new"}

    assert run_guard(repo, "--ci", env=env).returncode == 0


def test_the_pipeline_checks_from_the_base_of_a_pull_request(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    base = git(repo, "rev-parse", "HEAD").strip()
    assert guard.ci_revisions("pull_request", {"pull_request": {"base": {"sha": base}}}, "refs/pull/1/merge") == ["HEAD", f"^{base}"]
    assert guard.ci_revisions("merge_group", {"merge_group": {"base_sha": base}}, "refs/heads/gh-readonly-queue") == ["HEAD", f"^{base}"]
    assert guard.ci_revisions("push", {"before": base}, "refs/heads/main") == ["HEAD", f"^{base}"]


@pytest.mark.parametrize("text", ["HEAD~1", "a...b", "..HEAD"])
def test_a_range_without_a_base_is_an_error(text: str) -> None:
    with pytest.raises(guard.GuardError):
        guard.parse_range(text)


# --- the guard as the hooks and the pipeline run it


def git(repo: Path, *args: str, stdin: str | None = None, check: bool = True) -> str:
    """Runs git in repo with a made-up author, so that commits and merges work without a Git identity on the computer."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True, input=stdin, env=env).stdout


def run_guard(repo: Path, *args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Runs the guard in repo. Unless the test names a fingerprint file, an empty one is used. HOME is a new temporary
    folder, so the result does not depend on this repository's fingerprints or on a key on the developer's computer."""
    home = Path(tempfile.mkdtemp(prefix="guard-home-"))
    base_env = {k: v for k, v in os.environ.items() if not k.startswith(("FRANCA_FINGERPRINT", "GITHUB_"))}
    base_env["HOME"] = str(home)
    if "--fingerprints" not in args:
        empty = home / "no-fingerprints.txt"
        empty.write_text("# No fingerprints in this test.\n", encoding="utf-8")
        args = (*args, "--fingerprints", str(empty))
    try:
        return subprocess.run(
            [sys.executable, "-I", str(GUARD_PATH), *args],
            cwd=repo,
            capture_output=True,
            text=True,
            input=stdin,
            env={**base_env, **(env or {})},
        )
    finally:
        shutil.rmtree(home, ignore_errors=True)


def commit(repo: Path, name: str, data: bytes, message: str = "add") -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_bytes(data)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    commit(path, "README.md", b"public\n", "start")
    return path


def test_staged_check_passes_clean_changes(repo: Path) -> None:
    (repo / "app.py").write_text("print('hello')\n")
    git(repo, "add", "app.py")
    assert run_guard(repo, "--staged").returncode == 0


def test_staged_check_refuses_a_pack_file(repo: Path) -> None:
    (repo / "packs" / "nl-be").mkdir(parents=True)
    (repo / "packs" / "nl-be" / "a.yaml").write_text("x: 1\n")
    git(repo, "add", "packs")
    result = run_guard(repo, "--staged")
    assert result.returncode == 1
    assert "packs/nl-be/a.yaml" in result.stderr


def test_staged_check_reads_the_staged_version_not_the_working_file(repo: Path) -> None:
    (repo / "notes.txt").write_text(f"{MARKER}\n")
    git(repo, "add", "notes.txt")
    (repo / "notes.txt").write_text("clean now, but not staged\n")
    assert run_guard(repo, "--staged").returncode == 1


def test_staged_check_refuses_a_submodule(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    commit(other, "x.txt", b"x\n")
    sha = git(other, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/other")
    result = run_guard(repo, "--staged")
    assert result.returncode == 1
    assert "submodules" in result.stderr


def test_push_check_finds_a_file_that_a_later_commit_removed(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "photo.txt", JPEG)
    git(repo, "rm", "-q", "photo.txt")
    git(repo, "commit", "-q", "-m", "remove")
    head = git(repo, "rev-parse", "HEAD").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/heads/main {head} refs/heads/main {base}\n")
    assert result.returncode == 1
    assert "photo.txt" in result.stderr


def test_push_check_finds_a_file_under_a_second_path(repo: Path) -> None:
    # The same file version under a public path and a private path: the private path is checked too.
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "notes").mkdir()
    (repo / "notes" / "les.yaml").write_text("x: 1\n")
    (repo / "packs" / "nl").mkdir(parents=True)
    (repo / "packs" / "nl" / "les.yaml").write_text("x: 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "two paths")
    head = git(repo, "rev-parse", "HEAD").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/heads/main {head} refs/heads/main {base}\n")
    assert result.returncode == 1
    assert "packs/nl/les.yaml" in result.stderr


def test_push_check_of_a_new_branch_checks_commits_the_remote_does_not_have(repo: Path) -> None:
    head = commit(repo, "photo.txt", JPEG)
    result = run_guard(repo, "--push", "origin", stdin=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n")
    assert result.returncode == 1


def test_push_check_ignores_what_another_remote_has(repo: Path, tmp_path: Path) -> None:
    # Commits fetched from the private repository are new to the public remote, so they are checked.
    content = tmp_path / "content"
    content.mkdir()
    git(content, "init", "-q", "-b", "main")
    commit(content, "packs/nl/u01.yaml", b"x: 1\n")
    git(repo, "remote", "add", "content", str(content))
    git(repo, "fetch", "-q", "content")
    git(repo, "tag", "leak", "content/main")
    tag = git(repo, "rev-parse", "leak").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/tags/leak {tag} refs/tags/leak {'0' * 40}\n")
    assert result.returncode == 1
    assert "packs/nl/u01.yaml" in result.stderr


def test_push_check_refuses_a_tag_that_points_at_a_file(repo: Path) -> None:
    blob = git(repo, "hash-object", "-w", "--stdin", stdin=f"{MARKER}\n").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/tags/file {blob} refs/tags/file {'0' * 40}\n")
    assert result.returncode == 1


def test_the_pipeline_checks_the_message_of_a_new_tag(repo: Path, tmp_path: Path) -> None:
    git(repo, "tag", "-a", "v1", "-m", f"release notes\n{MARKER}\n")
    git(repo, "checkout", "-q", "v1")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40, "created": True}), encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event), "GITHUB_REF": "refs/tags/v1"}

    assert run_guard(repo, "--ci", env=env).returncode == 1


def test_the_pipeline_checks_the_history_of_a_new_tag(repo: Path, tmp_path: Path) -> None:
    commit(repo, "packs/nl-be/words.yaml", b"words\n")
    git(repo, "rm", "-q", "-r", "packs")
    git(repo, "commit", "-q", "-m", "remove")
    git(repo, "tag", "-a", "v1", "-m", "release")
    git(repo, "checkout", "-q", "v1")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40, "created": True}), encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event), "GITHUB_REF": "refs/tags/v1"}

    assert run_guard(repo, "--ci", env=env).returncode == 1


def test_a_push_needs_the_key_when_there_are_fingerprints(repo: Path, tmp_path: Path) -> None:
    prints = tmp_path / "prints.txt"
    prints.write_text("0" * 64 + "\n", encoding="utf-8")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40, "created": True}), encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event), "GITHUB_REF": "refs/heads/main"}

    assert run_guard(repo, "--ci", "--fingerprints", str(prints), env=env).returncode == 2


def test_push_check_allows_deleting_a_branch(repo: Path) -> None:
    assert run_guard(repo, "--push", "origin", stdin=f"(delete) {'0' * 40} refs/heads/old {'1' * 40}\n").returncode == 0


def test_range_check(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "packs/nl-be/a.yaml", b"x: 1\n")
    assert run_guard(repo, "--range", f"{base}..HEAD").returncode == 1
    assert run_guard(repo, "--range", f"{base}..{base}").returncode == 0


def test_history_check_finds_a_file_in_the_first_commit(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "a.mp3", MP3)
    git(repo, "rm", "-q", "a.mp3")
    git(repo, "commit", "-q", "-m", "remove")
    assert run_guard(repo, "--history").returncode == 1


def test_ci_check_of_a_first_push_checks_the_whole_history(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "a.mp3", MP3)
    git(repo, "rm", "-q", "a.mp3")
    git(repo, "commit", "-q", "-m", "remove")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40, "created": True}))
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event), "GITHUB_REF": "refs/heads/main"}
    result = run_guard(repo, "--ci", env=env)
    assert result.returncode == 1
    assert "a.mp3" in result.stderr


def test_push_check_refuses_a_tag_that_points_at_a_folder(repo: Path) -> None:
    blob = git(repo, "hash-object", "-w", "--stdin", stdin=f"{MARKER}\n").strip()
    tree = git(repo, "mktree", stdin=f"100644 blob {blob}\tsecret.txt\n").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/tags/folder {tree} refs/tags/folder {'0' * 40}\n")
    assert result.returncode == 1
    assert "secret.txt" in result.stderr
    git(repo, "tag", "folder", tree)
    assert run_guard(repo, "--history").returncode == 1


def test_a_merge_that_adds_a_file_is_checked_whatever_the_git_settings(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "side.txt", b"side\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "main.txt", b"main\n")
    git(repo, "merge", "-q", "--no-commit", "side")
    (repo / "added-in-merge.txt").write_text(f"{MARKER}\n")
    git(repo, "add", "added-in-merge.txt")
    git(repo, "commit", "-q", "-m", "merge")
    git(repo, "config", "log.diffMerges", "combined")
    head = git(repo, "rev-parse", "HEAD").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/heads/main {head} refs/heads/main {base}\n")
    assert result.returncode == 1
    assert "added-in-merge.txt" in result.stderr


def test_push_check_works_when_the_remote_has_moved_on(repo: Path) -> None:
    head = commit(repo, "photo.txt", JPEG)
    unknown = "4" * 40  # a commit on the remote that has not been fetched
    result = run_guard(repo, "--push", "origin", stdin=f"refs/heads/main {head} refs/heads/main {unknown}\n")
    assert result.returncode == 1
    assert "photo.txt" in result.stderr


def test_a_secret_in_a_commit_message_is_refused(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "key " + "AKIA" + "ABCDEFGHIJKLMNOP")
    assert run_guard(repo, "--range", f"{base}..HEAD").returncode == 1


def test_a_secret_in_a_tag_message_is_refused(repo: Path) -> None:
    git(repo, "tag", "-a", "v1", "-m", "token " + "ghp_" + "a1" * 18)
    tag = git(repo, "rev-parse", "v1").strip()
    result = run_guard(repo, "--push", "origin", stdin=f"refs/tags/v1 {tag} refs/tags/v1 {'0' * 40}\n")
    assert result.returncode == 1
    assert "message of tag" in result.stderr


def test_a_file_too_large_to_read_is_refused_without_reading_it(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "big.txt", b"x" * (guard.MAX_BYTES + 1))
    monkeypatch.chdir(repo)
    found = guard.commits(guard.parse_range(f"{base}..HEAD"))
    assert guard._read_blobs(e.sha for e in found.entries) == {found.entries[0].sha: None}
    assert run_guard(repo, "--range", f"{base}..HEAD").returncode == 1


def test_a_fork_pull_request_without_the_key_skips_the_fingerprints(repo: Path, tmp_path: Path) -> None:
    prints = tmp_path / "prints.txt"
    prints.write_text("line:0123456789abcdef01234567\n")
    base = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "a.txt", b"a\n")
    event = tmp_path / "event.json"
    pr = {"base": {"sha": base, "repo": {"full_name": "org/franca"}}, "head": {"repo": {"full_name": "someone/franca"}}}
    event.write_text(json.dumps({"pull_request": pr}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "HOME": str(tmp_path)}
    assert run_guard(repo, "--ci", "--fingerprints", str(prints), env=env).returncode == 0
    pr["head"] = {"repo": {"full_name": "org/franca"}}
    event.write_text(json.dumps({"pull_request": pr}))
    assert run_guard(repo, "--ci", "--fingerprints", str(prints), env=env).returncode == 2


def test_a_git_error_is_reported_in_words(repo: Path) -> None:
    result = run_guard(repo, "--range", f"{'3' * 40}..HEAD")
    assert result.returncode == 2
    assert "could not run" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_guard_explains_what_to_do(repo: Path) -> None:
    (repo / "a.mp3").write_bytes(MP3)
    git(repo, "add", "a.mp3")
    result = run_guard(repo, "--staged")
    assert "franca-content" in result.stderr
    assert "git restore --staged" in result.stderr


def test_the_repository_passes_its_own_guard() -> None:
    root = GUARD_PATH.parents[1]
    if not (root / ".git").exists():
        if os.environ.get("CI"):
            pytest.fail("the pipeline checkout has no .git folder")
        pytest.skip("not a Git checkout")
    result = run_guard(root, "--index")
    assert result.returncode == 0, result.stdout + result.stderr
    key = guard.read_key()
    if key is not None:
        # With the key, the files are also compared with the private repository's fingerprints.
        result = run_guard(root, "--index", "--fingerprints", str(guard.DEFAULT_FINGERPRINTS), env={"FRANCA_FINGERPRINT_KEY": key.decode()})
        assert result.returncode == 0, result.stdout + result.stderr
