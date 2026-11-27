"""Content guard: keeps course material, media, learner data and secrets out of the public repository (story E01-014).

Franca's code is public and its content is private (decision record 0001, docs/repository-split.md). Anything
pushed to a public repository can be copied before it is removed. The pre-push hook is what prevents a leak; the
pipeline check finds one after the push, when the file is already public.

  pre-commit hook   python3 -I tools/content_guard.py --staged
  pre-push hook     python3 -I tools/content_guard.py --push REMOTE   (Git passes the refs on standard input)
  pipeline          python3 -I tools/content_guard.py --ci            (reads the GitHub event)
  scripts/check     python3 -I tools/content_guard.py --index
  whole history     python3 -I tools/content_guard.py --history

The push, pipeline and history checks look at every file version in every new commit, under every path it had,
so a file that was added and removed again is found. The guard uses the Python standard library only and is run
with -I, so PYTHONPATH, the user's site folder and files in the current folder are not loaded.

Fingerprints of the private repository are HMAC-SHA-256 values made with a key that is kept out of this
repository (see docs/repository-split.md). To refresh them, run in a checkout of franca-content:
  python3 -I <path to franca>/tools/content_guard.py --fingerprint . > <path to franca>/tools/content-fingerprints.txt
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FINGERPRINTS = HERE / "content-fingerprints.txt"
ALLOWED_MEDIA_FILE = HERE / "content-guard-allowed-media.txt"
KEY_FILE = Path.home() / ".config" / "franca" / "fingerprint-key"
MAX_BYTES = 2 * 1024 * 1024
MIN_LINE_CHARS = 40
MIN_FILE_BYTES = 64  # smaller files (empty files, one-line stubs) are too common to fingerprint
# Files in the private repository that are not fingerprinted. The fixture pack has the real planner settings, so that
# the tests use them, and the keys in secrets/ are not content.
NOT_FINGERPRINTED = ("course-config.yaml", "secrets/*")
ZERO_SHA = "0" * 40
GITLINK_MODE = "160000"
MARKER = "franca:" + "private"  # files in the private repository have this marker; in two parts so this file has not

# Folders that hold private material. Those in ROOT_ONLY are refused at the top of the repository only, because
# names such as "media" are also normal folder names in code (a media player component, for example).
PRIVATE_FOLDERS_ANYWHERE = {"packs", "harvest", "learner-data", "backups", "secrets"}
PRIVATE_FOLDERS_ROOT_ONLY = {"content", "media"}
PUBLIC_PREFIXES = ("packs/fixture/",)  # the made-up pack for the tests
PRIVATE_EXTENSIONS = {".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm", ".db-journal", ".pem", ".key", ".crt", ".cer", ".p12", ".pfx"}
PRIVATE_NAMES = {".gitmodules", ".envrc"}
PUBLIC_ENV_NAMES = {".env.example"}

MEDIA_EXTENSIONS = {
    # pictures
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".ico",
    # sound
    ".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac", ".wma",
    # video and subtitles
    ".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".srt", ".vtt", ".ass", ".ssa",
    # books and office documents
    ".epub", ".mobi", ".azw3", ".pdf", ".docx", ".doc", ".odt", ".pptx", ".xlsx", ".xls", ".ods",
    # archives, which can hold any of the above
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".whl",
}  # fmt: skip

# The first bytes that an allowed media file must start with, so a file in an allowed folder is what its name says.
ALLOWED_MEDIA_SIGNATURES = {".png": b"\x89PNG\r\n\x1a\n", ".ico": b"\x00\x00\x01\x00"}

TEXT_EXTENSIONS_FOR_FINGERPRINTS = {".yaml", ".yml", ".md", ".txt", ".csv", ".tsv", ".json", ".srt", ".vtt", ".html"}

# Common secret formats. Each pattern needs the characters that follow the prefix, so this file does not match itself.
SECRET_PATTERNS = {
    "an Anthropic API key": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "a GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    "an AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "a Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}"),
    "a Google OAuth client secret": re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    "a Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "a Tailscale key": re.compile(rb"\btskey-(?:auth|api|client)-[A-Za-z0-9-]{10,}"),
    "a private key": re.compile(rb"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
}


class GuardError(Exception):
    """A problem that stops the guard from checking, as opposed to a file that fails the check."""


# --- rules for one file version


def _magic(data: bytes) -> str | None:
    """The media, archive or database type that the first bytes show, whatever the file is called."""
    head = data[:16]
    checks = [
        (head.startswith(b"\xff\xd8\xff"), "JPEG picture"),
        (head.startswith(b"\x89PNG\r\n\x1a\n"), "PNG picture"),
        (head.startswith((b"GIF87a", b"GIF89a")), "GIF picture"),
        (head[:4] == b"RIFF" and head[8:12] == b"WEBP", "WebP picture"),
        (head[:4] == b"RIFF" and head[8:12] == b"WAVE", "WAV sound"),
        (head[:4] == b"RIFF" and head[8:12] == b"AVI ", "AVI video"),
        (head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), "MP3 sound"),
        (head[:2] in (b"\xff\xf1", b"\xff\xf9"), "AAC sound"),
        (head.startswith(b"OggS"), "Ogg sound"),
        (head.startswith(b"fLaC"), "FLAC sound"),
        (head[4:8] == b"ftyp", "MP4, M4A, HEIC or AVIF media"),
        (head.startswith(b"\x1a\x45\xdf\xa3"), "WebM or Matroska video"),
        (head.startswith(b"%PDF"), "PDF document"),
        (head.startswith(b"PK\x03\x04"), "ZIP archive (also EPUB, Office documents and wheels)"),
        (head.startswith(b"7z\xbc\xaf\x27\x1c"), "7-Zip archive"),
        (head.startswith(b"Rar!\x1a\x07"), "RAR archive"),
        (head.startswith(b"\x1f\x8b"), "gzip archive"),
        (head.startswith(b"BZh"), "bzip2 archive"),
        (head.startswith(b"\xfd7zXZ\x00"), "xz archive"),
        (head.startswith(b"\x28\xb5\x2f\xfd"), "Zstandard archive"),
        (data[257:262] == b"ustar", "tar archive"),
        (head.startswith(b"SQLite format 3\x00"), "SQLite database"),
        (head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), "old Office document"),
        (head.startswith((b"II*\x00", b"MM\x00*")), "TIFF picture"),
        (head.startswith((b"WEBVTT", b"\xef\xbb\xbfWEBVTT")), "WebVTT subtitles"),
    ]
    return next((name for hit, name in checks if hit), None)


def _glob(path: str, pattern: str) -> bool:
    """fnmatch for each folder level, so * does not match across a slash."""
    parts, pattern_parts = path.split("/"), pattern.split("/")
    return len(parts) == len(pattern_parts) and all(fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pattern_parts, strict=True))


def _allowed_media_patterns() -> list[str]:
    if not ALLOWED_MEDIA_FILE.exists():
        return []
    lines = ALLOWED_MEDIA_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


def _private_path(lower: str) -> bool:
    if lower.startswith(PUBLIC_PREFIXES):
        return False
    parts = lower.split("/")
    name = parts[-1]
    folders = parts[:-1]
    if folders and folders[0] in PRIVATE_FOLDERS_ROOT_ONLY:
        return True
    if PRIVATE_FOLDERS_ANYWHERE.intersection(folders):
        return True
    if name in PRIVATE_NAMES or Path(name).suffix in PRIVATE_EXTENSIONS:
        return True
    is_env = name == ".env" or name.startswith(".env.") or name.endswith(".env")
    return is_env and name not in PUBLIC_ENV_NAMES


def _media_problems(path: str, lower: str, data: bytes) -> list[str]:
    suffix = Path(lower).suffix
    if any(_glob(lower, p) for p in _allowed_media_patterns()):
        signature = ALLOWED_MEDIA_SIGNATURES.get(suffix)
        if signature and data.startswith(signature):
            return []
        return [f"the file is in a folder allowed for icons, but it is not a {suffix or 'picture'} file"]
    if suffix in MEDIA_EXTENSIONS:
        return [f"media, document and archive files ({suffix}) are kept in the private repository"]
    kind = _magic(data)
    if kind:
        return [f"the file is media, a document, an archive or a database ({kind}), whatever its name"]
    if suffix == ".svg" and re.search(rb"data:[^,\"'>]*;base64,", data, re.IGNORECASE):
        return ["the SVG file has an embedded picture (a data: URI)"]
    if data.startswith(b"version https://git-lfs"):
        return ["the file is a Git LFS pointer, so its content would go to the public LFS store"]
    return []


def check_text(data: bytes, fingerprints: Fingerprints) -> list[str]:
    """Problems in the text of a file, or of a commit or tag message."""
    problems: list[str] = []
    if MARKER.encode() in data:
        problems.append(f"it has the private-content marker ({MARKER})")
    problems += [f"it has what looks like {name}" for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)]
    return problems + fingerprints.problems(data)


def check_path(path: str) -> list[str]:
    if _private_path(path.lower()):
        return ["this folder or file type is kept in the private repository or on the PC"]
    return []


def too_large() -> str:
    return f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB"


def check_file(path: str, data: bytes, fingerprints: Fingerprints) -> list[str]:
    """Reasons why this file version must not go into the public repository; empty when it may."""
    problems = check_path(path) + _media_problems(path, path.lower(), data)
    if len(data) > MAX_BYTES:
        problems.append(too_large())
    return problems + check_text(data, fingerprints)


# --- fingerprints of the private repository


def _normalise(line: str) -> str:
    return " ".join(unicodedata.normalize("NFC", line).split()).casefold()


YAML_KEY_OR_DASH = re.compile(r"^\s*(?:-\s+)?(?:[\w.-]+:\s+)?")
QUOTED = re.compile(rf"\"([^\"]{{{MIN_LINE_CHARS},}})\"|'([^']{{{MIN_LINE_CHARS},}})'")


def _line_variants(line: str) -> list[str]:
    """A line, its value without a YAML key or list dash, and long quoted strings in it.

    So a sentence from a pack file is found when it is pasted into code as a string, and the other way round.
    """
    parts = [line, YAML_KEY_OR_DASH.sub("", line, count=1)]
    parts += [a or b for a, b in QUOTED.findall(line)]
    parts += [part.strip().strip("\"'") for part in list(parts)]
    return [text for part in parts if len(text := _normalise(part)) >= MIN_LINE_CHARS]


@dataclass(frozen=True)
class Fingerprints:
    """HMAC values of the private files and of their long lines. Without the key, the values show nothing."""

    key: bytes
    values: frozenset[str]

    def _mac(self, kind: str, data: bytes) -> str:
        return f"{kind}:" + hmac.new(self.key, data, hashlib.sha256).hexdigest()[:24]

    def of_file(self, data: bytes) -> str:
        return self._mac("file", data)

    def of_line(self, line: str) -> set[str]:
        return {self._mac("line", text.encode("utf-8")) for text in _line_variants(line)}

    def problems(self, data: bytes) -> list[str]:
        if not self.values:
            return []
        if len(data) >= MIN_FILE_BYTES and self.of_file(data) in self.values:
            return ["it is a copy of a file in the private repository"]
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
            if self.of_line(line) & self.values:
                return [f"line {number} is a copy of a line in the private repository"]
        return []


NO_FINGERPRINTS = Fingerprints(key=b"", values=frozenset())


def read_key(environ: dict[str, str] | None = None) -> bytes | None:
    """The fingerprint key, from FRANCA_FINGERPRINT_KEY or from the key file. None when there is none."""
    env = os.environ if environ is None else environ
    if env.get("FRANCA_FINGERPRINT_KEY"):
        return env["FRANCA_FINGERPRINT_KEY"].strip().encode()
    key_file = Path(env.get("FRANCA_FINGERPRINT_KEY_FILE", str(KEY_FILE)))
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip().encode()
    return None


def load_fingerprints(path: Path, key: bytes | None) -> Fingerprints:
    if not path.exists():
        raise GuardError(f"The fingerprint file {path} is missing.")
    lines = path.read_text(encoding="utf-8").splitlines()
    values = frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))
    if not values:
        return NO_FINGERPRINTS
    if not key:
        raise GuardError(
            "The fingerprint key is missing, so files cannot be compared with the private repository. Put the key in"
            f" {KEY_FILE} or in the variable FRANCA_FINGERPRINT_KEY (see docs/repository-split.md)."
        )
    return Fingerprints(key=key, values=values)


def make_fingerprints(content_root: Path, key: bytes) -> set[str]:
    """Fingerprints of every file in a checkout of the private repository, and of the long lines in its text files."""
    prints = Fingerprints(key=key, values=frozenset())
    values: set[str] = set()
    for file in sorted(content_root.rglob("*")):
        relative = file.relative_to(content_root)
        if not file.is_file() or ".git" in relative.parts:
            continue
        if any(fnmatch.fnmatch(relative.as_posix(), pattern) or fnmatch.fnmatch(file.name, pattern) for pattern in NOT_FINGERPRINTED):
            continue
        data = file.read_bytes()
        if len(data) >= MIN_FILE_BYTES:
            values.add(prints.of_file(data))
        if file.suffix.lower() in TEXT_EXTENSIONS_FOR_FINGERPRINTS:
            for line in data.decode("utf-8", errors="replace").splitlines():
                values |= prints.of_line(line)
    return values


# --- reading file versions from Git


@dataclass(frozen=True)
class Entry:
    """One file version under one path. mode 160000 is a submodule; sha is then a commit, not a file."""

    path: str
    mode: str
    sha: str


@dataclass(frozen=True)
class Message:
    """The text of a commit or an annotated tag, which is public once pushed."""

    label: str
    text: bytes


# Settings that change the output that the guard parses are fixed, whatever the user's Git configuration says.
GIT_SETTINGS = ["-c", "log.diffMerges=separate", "-c", "log.showSignature=false", "-c", "core.quotePath=false"]


def _git(*args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *GIT_SETTINGS, *args], input=stdin, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GuardError(f"git {' '.join(args[:3])} failed: {message}")
    return result.stdout


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def _read_blobs(shas: Iterable[str]) -> dict[str, bytes | None]:
    """Reads many files with one git cat-file process. Files larger than MAX_BYTES are not read (value None)."""
    wanted = list(dict.fromkeys(shas))
    if not wanted:
        return {}
    sizes: dict[str, int] = {}
    for sha, line in zip(
        wanted, _git("cat-file", "--batch-check", stdin="".join(f"{sha}\n" for sha in wanted).encode()).splitlines(), strict=True
    ):
        fields = line.split()
        if len(fields) < 3 or fields[1] == b"missing":
            raise GuardError(f"object {sha} is not in this repository; run git fetch first")
        sizes[sha] = int(fields[2])
    small = [sha for sha in wanted if sizes[sha] <= MAX_BYTES]
    blobs: dict[str, bytes | None] = dict.fromkeys(wanted)
    out = _git("cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in small).encode()) if small else b""
    pos = 0
    for sha in small:
        end = out.index(b"\n", pos)
        size = sizes[sha]
        blobs[sha] = out[end + 1 : end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def _raw_entries(raw: bytes) -> Iterator[Entry]:
    """Parses `git diff --raw -z` or `git log --raw -z` output (with --no-renames, so one path per record)."""
    tokens = iter(raw.split(b"\0"))
    for token in tokens:
        token = token.lstrip(b"\n")
        if token.startswith(b"::"):
            raise GuardError("combined merge output from git log, which the guard cannot read")
        if not token.startswith(b":"):
            continue
        meta = token[1:].split()
        path = _decode(next(tokens))
        status = meta[4][:1]
        if status != b"D":
            yield Entry(path=path, mode=meta[1].decode(), sha=meta[3].decode())


def staged_entries() -> list[Entry]:
    return list(_raw_entries(_git("diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "--diff-filter=ACMRT")))


def index_entries() -> list[Entry]:
    entries = []
    for record in _git("ls-files", "--stage", "-z").split(b"\0"):
        if record:
            meta, _, path = record.partition(b"\t")
            mode, sha, _stage = meta.split()
            entries.append(Entry(path=_decode(path), mode=mode.decode(), sha=sha.decode()))
    return entries


def commit_entries(rev_args: list[str]) -> list[Entry]:
    """Every file version added or changed by the commits, under every path, including merges against each parent."""
    raw = _git("log", "--raw", "-z", "--diff-merges=separate", "--root", "--no-renames", "--no-abbrev", "--format=", *rev_args, "--")
    return list(dict.fromkeys(_raw_entries(raw)))


def commit_messages(rev_args: list[str]) -> list[Message]:
    raw = _git("log", "-z", "--format=%H%x01%B", *rev_args, "--")
    messages = []
    for record in raw.split(b"\0"):
        sha, _, text = record.lstrip(b"\n").partition(b"\x01")
        if sha:
            messages.append(Message(label=f"message of commit {_decode(sha)[:12]}", text=text))
    return messages


def _object_type(sha: str) -> str:
    return _decode(_git("cat-file", "-t", sha)).strip()


@dataclass
class Found:
    """File versions and messages to check."""

    entries: list[Entry]
    messages: list[Message]

    def __iadd__(self, other: Found) -> Found:
        self.entries += other.entries
        self.messages += other.messages
        return self


def commits(rev_args: list[str]) -> Found:
    return Found(commit_entries(rev_args), commit_messages(rev_args))


def ref_contents(name: str, sha: str) -> Found:
    """What a ref adds besides commits: the messages of annotated tags, and files or folders it points to directly."""
    found = Found([], [])
    target = sha
    while _object_type(target) == "tag":
        found.messages.append(Message(label=f"message of tag {name}", text=_git("cat-file", "tag", target)))
        target = _decode(_git("rev-parse", f"{target}^{{}}")).strip()
    kind = _object_type(target)
    if kind == "blob":
        found.entries.append(Entry(path=name, mode="100644", sha=target))
    elif kind == "tree":
        for record in _git("ls-tree", "-r", "-z", "--full-tree", target).split(b"\0"):
            if record:
                meta, _, path = record.partition(b"\t")
                mode, _type, entry_sha = meta.split()
                found.entries.append(Entry(path=f"{name}:{_decode(path)}", mode=mode.decode(), sha=entry_sha.decode()))
    return found


def all_refs() -> Found:
    found = commits(["--all"])
    listing = _decode(_git("for-each-ref", "--format=%(objectname) %(refname)"))
    for line in listing.splitlines():
        sha, _, name = line.partition(" ")
        found += ref_contents(name, sha)
    return found


def _exists(sha: str, kind: str = "commit") -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{{kind}}}"], capture_output=True).returncode == 0


def push_contents(stdin: str, remote: str) -> Found:
    """Git's pre-push input, one line per ref: <local ref> <local sha> <remote ref> <remote sha>."""
    found = Found([], [])
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, _, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue  # deleting a ref adds nothing
        found += ref_contents(local_ref, local_sha)
        if not _exists(local_sha):
            continue
        if remote_sha == ZERO_SHA or not _exists(remote_sha):
            # A new branch or tag, or a remote that has moved on since the last fetch:
            # the commits that this remote is not known to have.
            found += commits([local_sha, "--not", f"--remotes={remote}"])
        else:
            found += commits([local_sha, f"^{remote_sha}"])
    return found


def parse_range(text: str) -> list[str]:
    if "..." in text or ".." not in text:
        raise GuardError(f"--range needs BASE..HEAD, not {text!r}. To check every commit, use --history.")
    base, _, head = text.partition("..")
    if not base:
        raise GuardError("--range needs a base commit. To check every commit, use --history.")
    return [head or "HEAD", f"^{base}"]


def _get(event: dict[str, object], *keys: str) -> object:
    value: object = event
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def ci_revisions(event_name: str, event: dict[str, object], ref: str) -> list[str] | None:
    """The commits to check in the pipeline, or None to check every branch and tag (the weekly and manual runs).
    A push without a usable base (a new branch or tag, or a force-push) is checked over the history of the pushed
    commit. Other branches are checked in their own runs, so a file on an open pull request's branch does not stop
    this one."""
    if event_name in ("pull_request", "pull_request_target"):
        base = _get(event, "pull_request", "base", "sha")
    elif event_name == "merge_group":
        base = _get(event, "merge_group", "base_sha")
    elif event_name == "push" and not ref.startswith("refs/tags/") and not event.get("created"):
        base = _get(event, "before")
    else:
        base = None
    if isinstance(base, str) and base and base != ZERO_SHA and _exists(base):
        return ["HEAD", f"^{base}"]
    return ["HEAD"] if event_name == "push" else None


def is_fork_pull_request(event_name: str, event: dict[str, object]) -> bool:
    """Pull requests from forks get no Actions secrets, so the fingerprint key is not there."""
    head_repo = _get(event, "pull_request", "head", "repo", "full_name")
    base_repo = _get(event, "pull_request", "base", "repo", "full_name")
    return event_name.startswith("pull_request") and head_repo != base_repo


# --- running the guard


def _report(problems: list[tuple[str, list[str]]]) -> int:
    if not problems:
        return 0
    print("The content guard stopped this commit or push. These must not go into the public repository:\n", file=sys.stderr)
    for label, reasons in problems:
        print(f"  {label}", file=sys.stderr)
        for reason in reasons:
            print(f"      {reason}", file=sys.stderr)
    print(
        "\nCourse material, pictures, sound, harvested text, learner data and secrets are kept in the private repository"
        " franca-content or on the PC. Before a commit, remove the files with  git restore --staged <file>. If they"
        " are already committed, remove them from the commits, or ask for help before going on."
        " See docs/repository-split.md.",
        file=sys.stderr,
    )
    return 1


def check_found(found: Found, prints: Fingerprints) -> list[tuple[str, list[str]]]:
    entries = list(dict.fromkeys(found.entries))
    blobs = _read_blobs(e.sha for e in entries if e.mode != GITLINK_MODE)
    problems = []
    for entry in entries:
        if entry.mode == GITLINK_MODE:
            reasons = ["submodules are not used in this repository, because their address would be public"]
        elif (data := blobs[entry.sha]) is None:
            reasons = [*check_path(entry.path), too_large()]
        else:
            reasons = check_file(entry.path, data, prints)
        if reasons:
            problems.append((entry.path, reasons))
    for message in dict.fromkeys(found.messages):
        if reasons := check_text(message.text, prints):
            problems.append((message.label, reasons))
    return problems


def _ci_event() -> tuple[str, dict[str, object]]:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
    return os.environ.get("GITHUB_EVENT_NAME", ""), event


def _contents_for(args: argparse.Namespace) -> Found:
    if args.staged:
        return Found(staged_entries(), [])
    if args.index:
        return Found(index_entries(), [])
    if args.history:
        return all_refs()
    if args.range:
        return commits(parse_range(args.range))
    if args.ci:
        event_name, event = _ci_event()
        revisions = ci_revisions(event_name, event, os.environ.get("GITHUB_REF", ""))
        if revisions is None:
            print("Checking every branch and tag.", file=sys.stderr)
            return all_refs()
        found = commits(revisions)
        ref = os.environ.get("GITHUB_REF", "")
        if ref.startswith("refs/tags/"):
            found += ref_contents(ref, _decode(_git("rev-parse", ref)).strip())  # an annotated tag's message
        return found
    return push_contents(sys.stdin.read(), args.push)


def _fingerprints_for(args: argparse.Namespace) -> Fingerprints:
    try:
        return load_fingerprints(args.fingerprints, read_key())
    except GuardError:
        if args.ci and is_fork_pull_request(*_ci_event()):
            print(
                "This pull request is from a fork, so it has no fingerprint key. The merge queue checks the fingerprints.", file=sys.stderr
            )
            return NO_FINGERPRINTS
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check the files staged for the next commit")
    mode.add_argument("--push", metavar="REMOTE", help="check the commits being pushed to REMOTE (pre-push hook)")
    mode.add_argument("--range", metavar="BASE..HEAD", help="check every file version and message in these commits")
    mode.add_argument("--ci", action="store_true", help="check the commits of the current GitHub Actions event")
    mode.add_argument("--index", action="store_true", help="check every file in the index")
    mode.add_argument("--history", action="store_true", help="check every file version and message in every commit and ref")
    mode.add_argument("--fingerprint", metavar="CONTENT_FOLDER", help="print the fingerprints of a checkout of franca-content")
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    args = parser.parse_args(argv)

    try:
        if args.fingerprint:
            key = read_key()
            if not key:
                raise GuardError(f"The fingerprint key is missing. Put it in {KEY_FILE} or in FRANCA_FINGERPRINT_KEY.")
            print("# Fingerprints of the private repository franca-content, made by  tools/content_guard.py --fingerprint")
            print("\n".join(sorted(make_fingerprints(Path(args.fingerprint), key))))
            return 0
        prints = _fingerprints_for(args)
        return _report(check_found(_contents_for(args), prints))
    except GuardError as error:
        print(f"The content guard could not run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
