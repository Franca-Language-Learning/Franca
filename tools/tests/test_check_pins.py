"""Tests for tools/check_pins.py (stories E01-004 and E01-013).

A tag such as python:3.14.10-slim or v0.19.1 can be moved to other content after it is published. The images and
source code that Franca is built from are named by digest or commit as well, so a moved tag is noticed.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pins", ROOT / "tools" / "check_pins.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pins"] = module
    spec.loader.exec_module(module)
    return module


check_pins = load_tool()


def problems_in(tmp_path: Path, name: str, text: str) -> list[str]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return [problem.message for problem in check_pins.check_file(path)]


# --- Dockerfiles


def test_a_base_image_with_a_digest_passes(tmp_path: Path) -> None:
    assert problems_in(tmp_path, "x.Dockerfile", f"FROM python:3.14.10-slim@{DIGEST}\n") == []


def test_a_base_image_named_by_tag_only_is_refused(tmp_path: Path) -> None:
    assert problems_in(tmp_path, "x.Dockerfile", "FROM python:3.14.10-slim AS build\n") == ["python:3.14.10-slim has no digest"]


def test_an_earlier_stage_needs_no_digest(tmp_path: Path) -> None:
    text = f"FROM golang:1.27.4@{DIGEST} AS tools\nFROM tools AS second\nCOPY --from=tools /out /out\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == []


def test_from_with_a_platform_option_is_read(tmp_path: Path) -> None:
    assert problems_in(tmp_path, "x.Dockerfile", "FROM --platform=linux/amd64 alpine:3.23\n") == ["alpine:3.23 has no digest"]


def test_a_git_clone_checked_against_its_commit_passes(tmp_path: Path) -> None:
    text = (
        f"FROM golang:1.27.4@{DIGEST}\n"
        "RUN git clone --quiet --depth 1 --branch v1.0.0 https://github.com/example/tool /src \\\n"
        f'    && cd /src && test "$(git rev-parse HEAD)" = {COMMIT} \\\n'
        "    && go build ./...\n"
    )
    assert problems_in(tmp_path, "x.Dockerfile", text) == []


def test_a_git_clone_without_a_commit_check_is_refused(tmp_path: Path) -> None:
    text = f"FROM golang:1.27.4@{DIGEST}\nRUN git clone --branch v1.0.0 https://github.com/example/tool /src && go build ./...\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["git clone without a check of the commit"]


# --- Compose files


def test_a_compose_image_with_a_digest_passes(tmp_path: Path) -> None:
    text = f"services:\n  proxy:\n    image: lscr.io/linuxserver/socket-proxy:3.4.8@{DIGEST}\n"
    assert problems_in(tmp_path, "compose.yaml", text) == []


def test_a_compose_image_named_by_tag_only_is_refused(tmp_path: Path) -> None:
    text = "services:\n  proxy:\n    image: lscr.io/linuxserver/socket-proxy:3.4.8\n"
    assert problems_in(tmp_path, "compose.yaml", text) == ["lscr.io/linuxserver/socket-proxy:3.4.8 has no digest"]


def test_franca_images_in_compose_are_named_by_the_installer(tmp_path: Path) -> None:
    text = "services:\n  app:\n    image: ${FRANCA_APP_IMAGE:-franca/app:${FRANCA_VERSION:-0.1.0-dev}}\n"
    assert problems_in(tmp_path, "compose.yaml", text) == []


# --- Images marked for Renovate in scripts and workflows


def test_a_marked_image_with_a_digest_passes(tmp_path: Path) -> None:
    text = f'PHONE = "tailscale/tailscale:v1.104.7@{DIGEST}"  # renovate: image\n'
    assert problems_in(tmp_path, "rehearse.py", text) == []


def test_a_marked_image_without_a_digest_is_refused(tmp_path: Path) -> None:
    text = 'PHONE = "tailscale/tailscale:v1.104.7"  # renovate: image\n'
    assert problems_in(tmp_path, "rehearse.py", text) == ["tailscale/tailscale:v1.104.7 has no digest"]


def test_a_marked_image_in_a_workflow_is_read(tmp_path: Path) -> None:
    text = '      PLAYWRIGHT_IMAGE: "mcr.microsoft.com/playwright:v1.65.1-noble"  # renovate: image\n'
    assert problems_in(tmp_path, ".github/workflows/ci.yml", text) == ["mcr.microsoft.com/playwright:v1.65.1-noble has no digest"]


def test_a_problem_names_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "x.Dockerfile"
    path.write_text(f"FROM python:3.14@{DIGEST}\nFROM alpine:3.23\n", encoding="utf-8")
    (problem,) = check_pins.check_file(path)
    assert (problem.path, problem.line, problem.image) == (path, 2, "alpine:3.23")


# --- More Dockerfile forms


def test_an_image_copied_from_with_copy_needs_a_digest(tmp_path: Path) -> None:
    text = f"FROM python:3.14@{DIGEST}\nCOPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["ghcr.io/astral-sh/uv:0.11.32 has no digest"]


def test_an_image_mounted_in_run_needs_a_digest(tmp_path: Path) -> None:
    text = f"FROM python:3.14@{DIGEST}\nRUN --mount=type=bind,from=alpine:3.23,target=/a ls /a\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["alpine:3.23 has no digest"]


def test_a_remote_add_needs_a_checksum(tmp_path: Path) -> None:
    text = f"FROM python:3.14@{DIGEST}\nADD https://example.org/tool.tar.gz /tmp/\nADD --checksum=sha256:{'c' * 64} https://example.org/b /tmp/\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["ADD of https://example.org/tool.tar.gz without --checksum=sha256:"]


def test_scratch_lowercase_and_split_from_lines_are_read(tmp_path: Path) -> None:
    text = "FROM scratch AS empty\nfrom --platform linux/amd64 \\\n    alpine:3.23 AS Base\nFROM base\nCOPY --from=0 /a /b\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["alpine:3.23 has no digest"]


def test_a_comment_inside_a_continuation_is_left_out(tmp_path: Path) -> None:
    text = (
        f"FROM golang:1.27@{DIGEST}\n"
        "RUN git clone --branch v1 https://github.com/example/tool /src \\\n"
        "    # the commit is checked next\n"
        f'    && cd /src && test "$(git rev-parse HEAD)" = {COMMIT}\n'
    )
    assert problems_in(tmp_path, "x.Dockerfile", text) == []


@pytest.mark.parametrize(
    "run",
    [
        f'git clone A /a && git clone B /b && cd /b && test "$(git rev-parse HEAD)" = {COMMIT}',
        f'git clone A /a && cd /a && test "$(git rev-parse HEAD)" = {COMMIT} || true',
        f'git clone A /a && cd /a && test "$(git rev-parse HEAD)" = {COMMIT} && git checkout main',
        f'git clone A /a && test "$(git rev-parse HEAD)" = {COMMIT} && git -C /a switch other',
    ],
    ids=["two clones, one check", "check made optional", "commit changed after the check", "git -C after the check"],
)
def test_a_commit_check_that_can_be_bypassed_is_reported(tmp_path: Path, run: str) -> None:
    assert problems_in(tmp_path, "x.Dockerfile", f"FROM golang:1.27@{DIGEST}\nRUN {run}\n") != []


def test_images_named_by_a_variable_or_as_franca_need_a_digest_in_a_dockerfile(tmp_path: Path) -> None:
    text = "ARG B=alpine:3.23\nFROM ${B}\nFROM franca/evil:1\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["${B} has no digest", "franca/evil:1 has no digest"]


def test_from_with_a_platform_value_and_a_stage_is_read(tmp_path: Path) -> None:
    text = f"FROM --platform=$BUILDPLATFORM golang:1.27@{DIGEST} AS build\nFROM build\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == []


def test_a_syntax_frontend_needs_a_digest(tmp_path: Path) -> None:
    text = f"# syntax=docker/dockerfile:1.7\nFROM alpine:3.23@{DIGEST}\n"
    assert problems_in(tmp_path, "x.Dockerfile", text) == ["docker/dockerfile:1.7 has no digest"]


# --- More Compose and workflow forms


def test_a_franca_variable_with_another_default_image_is_refused(tmp_path: Path) -> None:
    text = "services:\n  cache:\n    image: ${FRANCA_CACHE:-redis:7}\n"
    assert problems_in(tmp_path, "compose.yaml", text) == ["${FRANCA_CACHE:-redis:7} has no digest"]


@pytest.mark.parametrize(
    ("line", "image"),
    [
        ("    container: node:22", "node:22"),
        ("        image: postgres:17", "postgres:17"),
        ("      - uses: docker://alpine:3.23", "alpine:3.23"),
        ("        run: docker run --rm busybox:1.37 true", "busybox:1.37"),
    ],
)
def test_images_in_workflows_need_a_digest(tmp_path: Path, line: str, image: str) -> None:
    assert problems_in(tmp_path, ".github/workflows/ci.yml", line + "\n") == [f"{image} has no digest"]


def test_images_built_in_the_job_and_expressions_need_no_digest(tmp_path: Path) -> None:
    text = "          image: franca/app:0.1.0-dev\n          image: ${{ env.IMAGE }}@${{ steps.build.outputs.digest }}\n"
    assert problems_in(tmp_path, ".github/workflows/ci.yml", text) == []


def test_a_matrix_of_names_is_not_read_as_an_image(tmp_path: Path) -> None:
    assert problems_in(tmp_path, ".github/workflows/release.yml", "        image: [app, caddy]\n") == []


# --- Scripts


def test_an_unmarked_image_in_a_python_script_needs_a_digest(tmp_path: Path) -> None:
    text = 'PROXY = "alpine:3.23"\nPORT = "caddy:8443"\nOPTION = "no-new-privileges:true"\n'
    assert problems_in(tmp_path, "infra/tests/rehearse_x.py", text) == ["alpine:3.23 has no digest"]


def test_an_image_in_a_shell_docker_command_needs_a_digest(tmp_path: Path) -> None:
    text = 'docker run --rm "$updater_image" true\ndocker pull busybox:1.37\n'
    assert problems_in(tmp_path, "infra/tests/x.sh", text) == ["busybox:1.37 has no digest"]


@pytest.mark.parametrize(
    ("command", "image"),
    [
        ("docker run --rm alpine true", "alpine"),
        ("docker run --name proxy -v /a:/b redis:7", "redis:7"),
        ("docker pull node:22", "node:22"),
        ("docker run --rm \\\n    busybox:1.37 true", "busybox:1.37"),
    ],
    ids=["no tag", "options with values", "digits only", "continued line"],
)
def test_the_image_of_a_docker_command_is_its_first_argument(tmp_path: Path, command: str, image: str) -> None:
    assert problems_in(tmp_path, "infra/tests/x.sh", command + "\n") == [f"{image} has no digest"]


def test_a_pinned_image_without_the_exact_marker_is_reported(tmp_path: Path) -> None:
    text = f"PHONE = 'tailscale/tailscale:v1@{DIGEST}' # renovate: image\n"
    assert problems_in(tmp_path, "infra/tests/rehearse_x.py", text) == [
        "tailscale/tailscale:v1 has a digest but no '  # renovate: image' marker"
    ]


# --- Running the check


def test_the_report_and_exit_code(tmp_path: Path) -> None:
    (tmp_path / "infra" / "images").mkdir(parents=True)
    (tmp_path / "infra" / "images" / "x.Dockerfile").write_text("FROM alpine:3.23\n", encoding="utf-8")
    assert check_pins.report(tmp_path, resolve=False) == (["infra/images/x.Dockerfile:1: alpine:3.23 has no digest"], 1)
    (tmp_path / "infra" / "images" / "x.Dockerfile").write_text(f"FROM alpine:3.23@{DIGEST}\n", encoding="utf-8")
    assert check_pins.report(tmp_path, resolve=False) == ([], 0)


def test_the_report_with_digests_looked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "infra" / "images").mkdir(parents=True)
    (tmp_path / "infra" / "images" / "x.Dockerfile").write_text("FROM alpine:3.23\n", encoding="utf-8")
    monkeypatch.setattr(check_pins, "look_up_digest", lambda image: DIGEST)
    lines, code = check_pins.report(tmp_path, resolve=True)
    assert lines[1] == f"infra/images/x.Dockerfile:1:   alpine:3.23@{DIGEST}"
    assert code == 1


# --- Looking up digests


def test_the_digest_is_read_from_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        return f'{{"mediaType": "application/vnd.oci.image.index.v1+json", "digest": "{DIGEST}"}}\n'

    monkeypatch.setattr(check_pins, "run_docker", fake_run)
    assert check_pins.look_up_digest("alpine:3.23") == DIGEST
    assert calls == [["docker", "buildx", "imagetools", "inspect", "alpine:3.23", "--format", "{{json .Manifest}}"]]


def test_a_digest_that_is_not_sha256_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_pins, "run_docker", lambda command: '{"digest": "md5:abc"}')
    with pytest.raises(check_pins.PinError):
        check_pins.look_up_digest("alpine:3.23")


# --- This repository


def test_every_image_and_source_in_this_repository_is_pinned() -> None:
    problems = [f"{problem.path.relative_to(ROOT)}:{problem.line}: {problem.message}" for problem in check_pins.check_repository(ROOT)]
    assert problems == [], "Run  python3 -I tools/check_pins.py --resolve  on a computer with access to the registries."


def test_the_repository_check_reads_the_files_that_name_images() -> None:
    names = {path.relative_to(ROOT).as_posix() for path in check_pins.files_to_check(ROOT)}
    assert {"infra/compose.yaml", "infra/images/app.Dockerfile", ".github/workflows/ci.yml", "infra/tests/rehearse_tailnet.py"} <= names


def renovate_matches(manager_description_start: str) -> set[tuple[str, str]]:
    """What a custom manager in .github/renovate.json finds, as (file, dependency and version) pairs."""
    config = json.loads((ROOT / ".github" / "renovate.json").read_text(encoding="utf-8"))
    manager = next(m for m in config["customManagers"] if m["description"].startswith(manager_description_start))
    found = set()
    for path in check_pins.files_to_check(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        if not any(re.search(pattern.strip("/"), relative) for pattern in manager["managerFilePatterns"]):
            continue
        text = path.read_text(encoding="utf-8")
        for match_string in manager["matchStrings"]:
            for match in re.finditer(match_string.replace("(?<", "(?P<"), text):
                found.add((relative, f"{match['depName']}:{match['currentValue']}"))
    return found


def test_renovate_finds_the_marked_images_that_the_check_reads() -> None:
    marked = {
        (path.relative_to(ROOT).as_posix(), image.split("@")[0])
        for path in check_pins.files_to_check(ROOT)
        for image in check_pins.marked_images(path.read_text(encoding="utf-8"))
    }
    renovate = renovate_matches("Images in Python scripts") | renovate_matches("Images named in the workflows")
    assert marked == renovate


def test_renovate_finds_each_cloned_source() -> None:
    clones = {
        (path.relative_to(ROOT).as_posix(), clone)
        for path in check_pins.files_to_check(ROOT)
        for clone in re.findall(r"--branch (\S+) https://github\.com/(\S+?)(?:\.git)?\s", path.read_text(encoding="utf-8"))
    }
    expected = {(relative, f"{name}:{tag}") for relative, (tag, name) in clones}
    assert renovate_matches("Source code cloned in the Dockerfiles") == expected
    dockerfiles = [path for path in check_pins.files_to_check(ROOT) if path.name.endswith("Dockerfile")]
    all_clones = sum(len(check_pins.GIT_CLONE.findall(path.read_text(encoding="utf-8"))) for path in dockerfiles)
    assert all_clones == len(expected), "a git clone that Renovate does not find (another host, or no --branch)"
