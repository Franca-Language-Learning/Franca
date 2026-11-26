"""Pin check: the images and source code that Franca is built from are named by digest or commit (E01-004, E01-013).

A tag such as python:3.14.10-slim or v0.19.1 can be moved to other content after it is published. These are
reported as problems:

  Dockerfiles   an image in FROM, COPY --from= or RUN --mount=from= with no @sha256 digest, apart from scratch and
                earlier stages of the same file; ADD of a remote file with no --checksum=sha256:; a git clone with no
                test "$(git rev-parse HEAD)" = <commit> after it, or with a git checkout, fetch, reset or pull, or
                an || after the check, in the same RUN instruction
  Compose       an image with no digest, apart from Franca's own images, which are named by digest in the .env file
                that is written by the installer and the updater (${FRANCA_<NAME>_IMAGE:-franca/<name>:...})
  Workflows     an image in image:, container:, uses: docker:// or docker run/pull/create with no digest, apart
                from images built in the same job (franca/...)
  Scripts       an image in a string or a docker run/pull/create command with no digest

An image named in a script or workflow is marked with  # renovate: image  so that Renovate can update its digest
(.github/renovate.json). A test checks that the marked images and cloned sources found here are the ones that
Renovate's managers find.

  python3 -I tools/check_pins.py             check the repository
  python3 -I tools/check_pins.py --resolve   check, and print the digest of each image that has none

Only the Python standard library is needed. Dockerfile heredocs and the escape directive are not read; an
instruction that uses them is checked as plain text, so a problem in it is reported rather than missed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIGEST_SUFFIX = re.compile(r"@sha256:[0-9a-f]{64}$")
# An image reference: optional registry and path, a name and a tag. A tag of digits only is a port, and true or false
# is an option such as no-new-privileges:true.
IMAGE_REFERENCE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9._-]+)*:(?!(?:true|false)$)(?=[\w.-]*[A-Za-z_.-])[\w.-]+(?:@sha256:[0-9a-f]{64})?$"
)
FRANCA_IMAGE_VARIABLE = re.compile(r"^\$\{FRANCA_[A-Z]+_IMAGE:-franca/[a-z]+:\$\{FRANCA_VERSION:-[^}]+\}\}$")
LOCAL_IMAGE_PREFIX = "franca/"

FROM_LINE = re.compile(r"^FROM\s+(?:--\S+(?:\s+(?!AS\b)[^-\s]\S*)?\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?", re.IGNORECASE)
COPY_FROM = re.compile(r"^COPY\b.*?--from=(?P<image>\S+)", re.IGNORECASE)
MOUNT_FROM = re.compile(r"--mount=\S*?\bfrom=(?P<image>[^,\s]+)", re.IGNORECASE)
REMOTE_ADD = re.compile(r"^ADD\b(?P<options>(?:\s+--\S+)*)\s+(?P<source>(?:https?|git)://\S+|\S+\.git(?:#\S*)?)", re.IGNORECASE)
GIT_CLONE = re.compile(r"\bgit clone\b")
COMMIT_CHECK = re.compile(r'test "\$\(git rev-parse HEAD\)" = [0-9a-f]{40}\b')
AFTER_CHECK_NOT_ALLOWED = re.compile(r"\|\||\bgit (?:checkout|fetch|reset|pull)\b")

COMPOSE_IMAGE = re.compile(r"^\s*image:\s*[\"']?(?P<image>[^\"'\s]+)")
WORKFLOW_IMAGE = re.compile(r"^\s*(?:-\s+)?(?:image|container):\s*[\"']?(?P<image>[^\"'\s#\[{]+)[\"']?\s*(?:#.*)?$")
DOCKER_USES = re.compile(r"\buses:\s*[\"']?docker://(?P<image>[^\"'\s]+)")
DOCKER_COMMAND = re.compile(r"\bdocker\s+(?:run|pull|create)\b(?P<arguments>[^;&|\n]*)")
# The forms Renovate's managers read (.github/renovate.json): = "image" in Python, : "image" in YAML.
MARKED_IMAGE = re.compile(r"(?:= |: )\"(?P<image>[^\"\s]+)\"  # renovate: image")
PYTHON_STRING = re.compile(r"\"([^\"\s]+)\"|'([^'\s]+)'")

DOCKERFILES = ["**/Dockerfile", "**/*.Dockerfile", "**/Containerfile"]
COMPOSE_FILES = ["**/compose*.yaml", "**/compose*.yml", "**/docker-compose*.yaml", "**/docker-compose*.yml"]
WORKFLOWS = [".github/workflows/*.yml", ".github/workflows/*.yaml"]
SCRIPTS = ["infra/**/*.py", "infra/**/*.sh", "installer/**/*.py", "installer/**/*.sh", "scripts/*", "tools/*.sh"]
SKIPPED_FOLDERS = {"node_modules", ".venv", ".git", "__pycache__"}


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str
    image: str | None = None


class PinError(Exception):
    """A digest could not be looked up."""


def _no_digest(path: Path, line: int, image: str) -> Problem:
    return Problem(path, line, f"{image} has no digest", image)


def _needs_digest(image: str) -> bool:
    return "$" not in image and not image.startswith(LOCAL_IMAGE_PREFIX) and not DIGEST_SUFFIX.search(image)


def _instructions(text: str) -> Iterator[tuple[int, str]]:
    """Dockerfile instructions with their continuation lines joined, and the line each one starts on.

    Comment lines and blank lines inside a continuation are left out, as Docker leaves them out.
    """
    start = 0
    parts: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not parts:
            start = number
        if stripped.endswith("\\"):
            parts.append(stripped[:-1].strip())
            continue
        parts.append(stripped)
        yield start, " ".join(parts)
        parts = []
    if parts:
        yield start, " ".join(parts)


def _check_clones(path: Path, line: int, instruction: str) -> list[Problem]:
    clones = len(GIT_CLONE.findall(instruction))
    if not clones:
        return []
    checks = list(COMMIT_CHECK.finditer(instruction))
    if len(checks) < clones:
        return [Problem(path, line, "git clone without a check of the commit")]
    if AFTER_CHECK_NOT_ALLOWED.search(instruction[checks[0].start() :]):
        return [Problem(path, line, "the commit check is followed by || or by a git command that changes the commit")]
    return []


def check_dockerfile(path: Path, text: str) -> list[Problem]:
    problems: list[Problem] = []
    stages: set[str] = set()

    def check_image(line: int, image: str) -> None:
        name = image.lower()
        if name in stages or name == "scratch" or name.isdigit():
            return
        if _needs_digest(image):
            problems.append(_no_digest(path, line, image))

    for line, instruction in _instructions(text):
        if match := FROM_LINE.match(instruction):
            check_image(line, match["image"])
            if match["stage"]:
                stages.add(match["stage"].lower())
            continue
        if match := COPY_FROM.match(instruction):
            check_image(line, match["image"])
        for match in MOUNT_FROM.finditer(instruction):
            check_image(line, match["image"])
        if (match := REMOTE_ADD.match(instruction)) and "--checksum=sha256:" not in match["options"]:
            problems.append(Problem(path, line, f"ADD of {match['source']} without --checksum=sha256:"))
        problems += _check_clones(path, line, instruction)
    return problems


def check_compose(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, content in enumerate(text.splitlines(), start=1):
        match = COMPOSE_IMAGE.match(content)
        if match and not FRANCA_IMAGE_VARIABLE.match(match["image"]) and not DIGEST_SUFFIX.search(match["image"]):
            problems.append(_no_digest(path, line, match["image"]))
    return problems


def _images_in_docker_commands(content: str) -> Iterator[str]:
    for command in DOCKER_COMMAND.finditer(content):
        for word in command["arguments"].split():
            word = word.strip("\"'")
            if IMAGE_REFERENCE.match(word):
                yield word


def check_workflow(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, content in enumerate(text.splitlines(), start=1):
        images = [match["image"] for match in (WORKFLOW_IMAGE.match(content), DOCKER_USES.search(content)) if match]
        images += _images_in_docker_commands(content)
        images += marked_images(content)
        problems += [_no_digest(path, line, image) for image in dict.fromkeys(images) if _needs_digest(image)]
    return problems


def check_script(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, content in enumerate(text.splitlines(), start=1):
        images = list(_images_in_docker_commands(content))
        if path.suffix == ".py":
            images += [a or b for a, b in PYTHON_STRING.findall(content) if IMAGE_REFERENCE.match(a or b)]
        problems += [_no_digest(path, line, image) for image in dict.fromkeys(images) if _needs_digest(image)]
    return problems


def check_file(path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    name = path.name
    if name == "Dockerfile" or name.endswith(".Dockerfile") or name == "Containerfile":
        return check_dockerfile(path, text)
    if name.startswith(("compose", "docker-compose")) and path.suffix in {".yaml", ".yml"}:
        return check_compose(path, text)
    if ".github/workflows" in path.as_posix():
        return check_workflow(path, text)
    return check_script(path, text)


def _glob(root: Path, patterns: list[str]) -> set[Path]:
    found = {path for pattern in patterns for path in root.glob(pattern) if path.is_file()}
    return {path for path in found if not SKIPPED_FOLDERS & set(path.relative_to(root).parts)}


def files_to_check(root: Path) -> list[Path]:
    """The files that can name images. Unit tests (test_*.py) are left out, because their images are made up."""
    return sorted(path for path in _glob(root, DOCKERFILES + COMPOSE_FILES + WORKFLOWS + SCRIPTS) if not path.name.startswith("test_"))


def check_repository(root: Path) -> list[Problem]:
    return [problem for path in files_to_check(root) for problem in check_file(path)]


def marked_images(text: str) -> list[str]:
    """The images marked for Renovate in a script or workflow, in order."""
    return [match["image"] for match in MARKED_IMAGE.finditer(text)]


def run_docker(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        raise PinError(result.stderr.strip() or f"{command[0]} failed")
    return result.stdout


def look_up_digest(image: str) -> str:
    """The digest of the image's index (or manifest), as read from the registry with docker buildx imagetools."""
    manifest = json.loads(run_docker(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest}}"]))
    digest = manifest.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PinError(f"{image}: no sha256 digest was returned by docker buildx imagetools")
    return str(digest)


def report(root: Path, resolve: bool) -> tuple[list[str], int]:
    """The lines to print for the problems in the repository, and the exit code."""
    lines = []
    problems = check_repository(root)
    for problem in problems:
        location = f"{problem.path.relative_to(root)}:{problem.line}"
        lines.append(f"{location}: {problem.message}")
        if resolve and problem.image:
            try:
                lines.append(f"{location}:   {problem.image}@{look_up_digest(problem.image)}")
            except PinError as error:
                lines.append(f"{location}:   the digest could not be looked up: {error}")
    return lines, 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resolve", action="store_true", help="print the digest of each image that has none")
    args = parser.parse_args(argv)
    lines, code = report(ROOT, args.resolve)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
