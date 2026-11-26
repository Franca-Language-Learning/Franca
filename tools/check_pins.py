"""Pin check: the images and source code that Franca is built from are named by digest or commit (E01-004, E01-013).

A tag such as python:3.14.10-slim or v0.19.1 can be moved to other content after it is published. These are
reported as problems:

  Dockerfiles   an image in FROM, COPY --from=, RUN --mount=from= or a # syntax= line with no @sha256 digest, apart
                from scratch and earlier stages of the same file; ADD of a remote file with no --checksum=sha256:; a git clone with no
                test "$(git rev-parse HEAD)" = <commit> after it, or with a git checkout, fetch, reset or pull, or
                an || after the check, in the same RUN instruction. The number of clones in an instruction is
                compared with the number of checks. A check is not matched to its clone
  Compose       an image with no digest, apart from Franca's own images, which are named by digest in the .env file
                that is written by the installer and the updater (${FRANCA_<NAME>_IMAGE:-franca/<name>:...})
  Workflows     an image in image:, container:, uses: docker:// or docker run/pull/create with no digest, apart
                from images built in the same job (franca/...)
  Scripts       an image in a string or a docker run/pull/create command with no digest

An image named in a script or workflow is marked with  # renovate: image  so that Renovate can update its digest
(.github/renovate.json). An image with a digest but without that marker is reported too, because Renovate would not
update it. There is a test that the marked images and cloned sources found here are the ones that Renovate's managers
find.

  python3 -I tools/check_pins.py             check the repository
  python3 -I tools/check_pins.py --resolve   check, and print the digest of each image that has none

Only the Python standard library is needed. Dockerfile heredocs and the escape directive are not read. An
instruction that uses them is checked as plain text, so a problem in it is still reported.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIGEST_SUFFIX = re.compile(r"@sha256:[0-9a-f]{64}$")
# An image reference in a Python string: optional registry and path, a name and a tag. A tag of digits only is taken
# to be a port (caddy:8443), so an image such as redis:7, or an image with no tag, is not found in a Python string.
# true and false are options, as in no-new-privileges:true.
IMAGE_REFERENCE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9._-]+)*:(?!(?:true|false)$)(?=[\w.-]*[A-Za-z_.-])[\w.-]+(?:@sha256:[0-9a-f]{64})?$"
)
FRANCA_IMAGE_VARIABLE = re.compile(r"^\$\{FRANCA_[A-Z]+_IMAGE:-franca/[a-z]+:\$\{FRANCA_VERSION:-[^}]+\}\}$")
LOCAL_IMAGE_PREFIX = "franca/"

FROM_LINE = re.compile(
    r"^FROM\s+(?:--[\w-]+=\S+\s+|--[\w-]+\s+(?!AS\b)[^-\s]\S*\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?", re.IGNORECASE
)
SYNTAX_LINE = re.compile(r"^#\s*syntax\s*=\s*(?P<image>\S+)", re.IGNORECASE)
COPY_FROM = re.compile(r"^COPY\b.*?--from=(?P<image>\S+)", re.IGNORECASE)
MOUNT_FROM = re.compile(r"--mount=\S*?\bfrom=(?P<image>[^,\s]+)", re.IGNORECASE)
REMOTE_ADD = re.compile(r"^ADD\b(?P<options>(?:\s+--\S+)*)\s+(?P<source>(?:https?|git)://\S+|\S+\.git(?:#\S*)?)", re.IGNORECASE)
GIT_CLONE = re.compile(r"\bgit clone\b")
COMMIT_CHECK = re.compile(r'test "\$\(git rev-parse HEAD\)" = [0-9a-f]{40}\b')
AFTER_CHECK_NOT_ALLOWED = re.compile(r"\|\||\bgit(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+(?:checkout|switch|fetch|reset|pull|am|apply)\b")

COMPOSE_IMAGE = re.compile(r"^\s*image:\s*[\"']?(?P<image>[^\"'\s]+)")
WORKFLOW_IMAGE = re.compile(r"^\s*(?:-\s+)?(?:image|container):\s*[\"']?(?P<image>[^\"'\s#\[{]+)[\"']?\s*(?:#.*)?$")
DOCKER_USES = re.compile(r"\buses:\s*[\"']?docker://(?P<image>[^\"'\s]+)")
DOCKER_COMMAND = re.compile(r"\bdocker\s+(?:run|pull|create)\b(?P<arguments>[^;&|\n]*)")
# Options of docker run, pull and create that take a value as the next word.
DOCKER_OPTIONS_WITH_VALUES = {
    "--name", "-v", "--volume", "-e", "--env", "--env-file", "--network", "--network-alias", "--user", "-u", "-w",
    "--workdir", "--entrypoint", "-p", "--publish", "--shm-size", "--security-opt", "--cap-drop", "--cap-add",
    "--mount", "--platform", "-l", "--label", "--tmpfs", "--add-host", "--ipc", "--pid", "--memory", "--cpus",
    "--hostname", "-h", "--restart", "--log-driver", "--log-opt", "--device", "--ulimit", "--dns", "--gpus",
    "--group-add", "--runtime", "--stop-signal",
}  # fmt: skip
# The forms that are matched by Renovate's managers in .github/renovate.json: = "image" in Python, : "image" in YAML.
MARKED_IMAGE = re.compile(r"(?:= |: )\"(?P<image>[^\"\s]+)\"  # renovate: image")
PYTHON_STRING = re.compile(r"\"([^\"\s]+)\"|'([^'\s]+)'")
QUOTED_PINNED_IMAGE = re.compile(r"[\"'](?P<image>[a-z0-9][^\"'\s]*@sha256:[0-9a-f]{64})[\"']")

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
    """For scripts and workflows: a variable is checked where it is defined, and franca/ images are built in the job."""
    return "$" not in image and not image.startswith(LOCAL_IMAGE_PREFIX) and not DIGEST_SUFFIX.search(image)


def _not_marked(path: Path, line: int, content: str) -> list[Problem]:
    """Pinned images in quotes on a line without the exact marker that Renovate's managers need."""
    if MARKED_IMAGE.search(content) or WORKFLOW_IMAGE.match(content):
        return []
    return [
        Problem(path, line, f"{match['image'].split('@')[0]} has a digest but no '  # renovate: image' marker", match["image"])
        for match in QUOTED_PINNED_IMAGE.finditer(content)
    ]


def _instructions(text: str) -> Iterator[tuple[int, str]]:
    """Instructions with their continuation lines joined, and the line each one starts on.

    Comment lines and blank lines are left out, as they are in Docker.
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
        if not DIGEST_SUFFIX.search(image):
            problems.append(_no_digest(path, line, image))

    for line, content in enumerate(text.splitlines()[:5], start=1):
        if match := SYNTAX_LINE.match(content.strip()):
            check_image(line, match["image"])
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
    """The image of each docker run, pull or create: the first word that is not an option or an option's value."""
    for command in DOCKER_COMMAND.finditer(content):
        words = iter(command["arguments"].split())
        for word in words:
            if word in DOCKER_OPTIONS_WITH_VALUES:
                next(words, None)
            elif not word.startswith("-"):
                yield word.strip("\"'")
                break


def _docker_command_problems(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, instruction in _instructions(text):
        problems += [_no_digest(path, line, image) for image in _images_in_docker_commands(instruction) if _needs_digest(image)]
    return problems


def check_workflow(path: Path, text: str) -> list[Problem]:
    problems = _docker_command_problems(path, text)
    for line, content in enumerate(text.splitlines(), start=1):
        images = [match["image"] for match in (WORKFLOW_IMAGE.match(content), DOCKER_USES.search(content)) if match]
        images += marked_images(content)
        problems += [_no_digest(path, line, image) for image in dict.fromkeys(images) if _needs_digest(image)]
        problems += _not_marked(path, line, content)
    return sorted(problems, key=lambda problem: problem.line)


def check_script(path: Path, text: str) -> list[Problem]:
    problems = _docker_command_problems(path, text) if path.suffix != ".py" else []
    if path.suffix == ".py":
        for line, content in enumerate(text.splitlines(), start=1):
            images = [a or b for a, b in PYTHON_STRING.findall(content) if IMAGE_REFERENCE.match(a or b)]
            problems += [_no_digest(path, line, image) for image in dict.fromkeys(images) if _needs_digest(image)]
            problems += _not_marked(path, line, content)
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


def _glob_pattern(pattern: str) -> re.Pattern[str]:
    """A glob pattern with ** for any number of folders, as a regular expression (Path.full_match needs Python 3.13)."""
    parts = re.split(r"(\*\*/|\*)", pattern)
    replacements = {"**/": "(?:.*/)?", "*": "[^/]*"}
    return re.compile("".join(replacements.get(part, re.escape(part)) for part in parts))


def files_to_check(root: Path) -> list[Path]:
    """The files in which images can be named. Unit tests (test_*.py) are left out, because their images are made up.

    The folders are walked once, and node_modules, .venv and the like are not entered.
    """
    patterns = [_glob_pattern(pattern) for pattern in DOCKERFILES + COMPOSE_FILES + WORKFLOWS + SCRIPTS]
    found = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in SKIPPED_FOLDERS]
        for name in files:
            path = Path(folder, name)
            relative = path.relative_to(root).as_posix()
            if not name.startswith("test_") and any(pattern.fullmatch(relative) for pattern in patterns):
                found.append(path)
    return sorted(found)


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
