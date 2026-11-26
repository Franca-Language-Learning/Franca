"""Tests for the content guard (story E01-014).

The guard is run by the Git hooks and the pipeline, to keep course material, media, harvested text, learner data
and secrets out of the public repository. The tests in the second half make a small Git repository in a temporary
folder and run the guard as the hooks run it, with  python -I.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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
    ],
)
def test_private_paths_are_refused(path: str) -> None:
    assert check(path)


@pytest.mark.parametrize(
    "path",
    [
        "packs/fixture/course/u05-l03.lesson.yaml",
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


def test_fingerprints_are_made_from_a_content_folder(tmp_path: Path) -> None:
    lesson = tmp_path / "course" / "lesson.yaml"
    lesson.parent.mkdir()
    lesson.write_text(f"title: x\nprompt: {LONG_LINE}\n", encoding="utf-8")
    values = guard.make_fingerprints(tmp_path, KEY)
    fp = guard.Fingerprints(key=KEY, values=frozenset())
    assert fp.of_line(LONG_LINE) <= values
    assert fp.of_file(lesson.read_bytes()) in values


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
    guard.load_fingerprints(guard.DEFAULT_FINGERPRINTS, key=guard.read_key())


# --- the pipeline's choice of commits


@pytest.mark.parametrize(
    "event_name,event,ref",
    [
        ("push", {"before": "0" * 40}, "refs/heads/main"),  # first push of a branch
        ("push", {"before": "1" * 40, "created": True}, "refs/heads/new"),
        ("push", {"before": "1" * 40}, "refs/tags/v1"),
        ("push", {"before": "2" * 40}, "refs/heads/main"),  # a base that is not in the repository (force-push)
        ("schedule", {}, "refs/heads/main"),
        ("workflow_dispatch", {}, "refs/heads/main"),
    ],
)
def test_the_pipeline_checks_the_whole_history_when_there_is_no_usable_base(
    repo: Path, monkeypatch: pytest.MonkeyPatch, event_name: str, event: dict[str, object], ref: str
) -> None:
    monkeypatch.chdir(repo)
    assert guard.ci_revisions(event_name, event, ref) is None


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


def git(repo: Path, *args: str, stdin: str | None = None) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, input=stdin, env=env).stdout


def run_guard(repo: Path, *args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base_env = {k: v for k, v in os.environ.items() if not k.startswith(("FRANCA_FINGERPRINT", "GITHUB_"))}
    return subprocess.run(
        [sys.executable, "-I", str(GUARD_PATH), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
        env={**base_env, **(env or {})},
    )


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
