"""Pin check: the images and source code that Franca is built from are named by digest or commit (E01-004, E01-013).

A tag such as python:3.14.10-slim or v0.19.1 can be moved to other content after it is published. This check
refuses:

  - a base image in a Dockerfile (FROM) with no @sha256 digest, apart from an earlier stage of the same file
  - a git clone in a Dockerfile with no  test "$(git rev-parse HEAD)" = <commit>  in the same RUN instruction
  - an image in a Compose file with no digest, apart from Franca's own images, which the installer and the
    updater name by digest (${FRANCA_..._IMAGE})
  - an image marked  # renovate: image  in a script or workflow with no digest

Renovate adds and updates the digests and commits (.github/renovate.json). Where Renovate has not yet done so,
the digests can be looked up with Docker:

  python3 -I tools/check_pins.py             check the repository
  python3 -I tools/check_pins.py --resolve   check, and print the digest of each image that has none

The check uses the Python standard library only.
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
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
FROM_LINE = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?", re.IGNORECASE)
COMPOSE_IMAGE = re.compile(r"^\s*image:\s*[\"']?(?P<image>[^\"'\s]+)")
MARKED_IMAGE = re.compile(r"[\"'](?P<image>[^\"'\s]+)[\"']\s+# renovate: image")
COMMIT_CHECK = re.compile(r'test "\$\(git rev-parse HEAD\)" = [0-9a-f]{40}\b')
FRANCA_IMAGE = "${FRANCA_"


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


def _instructions(text: str) -> Iterator[tuple[int, str]]:
    """Dockerfile instructions with their continuation lines joined, and the line each one starts on."""
    start = 0
    parts: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not parts:
            start = number
        if line.rstrip().endswith("\\"):
            parts.append(line.rstrip()[:-1])
            continue
        parts.append(line)
        yield start, " ".join(parts)
        parts = []
    if parts:
        yield start, " ".join(parts)


def check_dockerfile(path: Path, text: str) -> list[Problem]:
    problems, stages = [], set()
    for line, instruction in _instructions(text):
        match = FROM_LINE.match(instruction)
        if match:
            image = match["image"]
            if image.lower() not in stages and not DIGEST.search(image):
                problems.append(_no_digest(path, line, image))
            if match["stage"]:
                stages.add(match["stage"].lower())
        elif "git clone" in instruction and not COMMIT_CHECK.search(instruction):
            problems.append(Problem(path, line, "git clone without a check of the commit"))
    return problems


def check_compose(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, content in enumerate(text.splitlines(), start=1):
        match = COMPOSE_IMAGE.match(content)
        if match and not match["image"].startswith(FRANCA_IMAGE) and not DIGEST.search(match["image"]):
            problems.append(_no_digest(path, line, match["image"]))
    return problems


def check_marked_images(path: Path, text: str) -> list[Problem]:
    problems = []
    for line, content in enumerate(text.splitlines(), start=1):
        for match in MARKED_IMAGE.finditer(content):
            if not DIGEST.search(match["image"]):
                problems.append(_no_digest(path, line, match["image"]))
    return problems


def check_file(path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    if path.name.endswith("Dockerfile"):
        return check_dockerfile(path, text)
    problems = check_compose(path, text) if path.name.startswith("compose") else []
    return problems + check_marked_images(path, text)


def files_to_check(root: Path) -> list[Path]:
    patterns = ["infra/images/*Dockerfile", "infra/compose*.yaml", ".github/workflows/*.yml", "infra/tests/*.py", "installer/**/*.py"]
    return sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file()})


def check_repository(root: Path) -> list[Problem]:
    return [problem for path in files_to_check(root) for problem in check_file(path)]


def run_docker(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        raise PinError(result.stderr.strip() or f"{command[0]} failed")
    return result.stdout


def look_up_digest(image: str) -> str:
    """The digest of the image's index (or manifest), as Docker reads it from the registry."""
    manifest = json.loads(run_docker(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest}}"]))
    digest = manifest.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PinError(f"{image}: Docker did not return a sha256 digest")
    return str(digest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resolve", action="store_true", help="print the digest of each image that has none")
    args = parser.parse_args(argv)
    problems = check_repository(ROOT)
    for problem in problems:
        location = f"{problem.path.relative_to(ROOT)}:{problem.line}"
        print(f"{location}: {problem.message}")
        if args.resolve and problem.image:
            try:
                print(f"{location}:   {problem.image}@{look_up_digest(problem.image)}")
            except PinError as error:
                print(f"{location}:   the digest could not be looked up: {error}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
