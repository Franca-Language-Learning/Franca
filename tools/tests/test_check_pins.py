"""Tests for tools/check_pins.py (stories E01-004 and E01-013).

A tag such as python:3.14.10-slim or v0.19.1 can be moved to other content after it is published. The images and
source code that Franca is built from are named by digest or commit as well, so a moved tag is noticed.
"""

from __future__ import annotations

import importlib.util
import json
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
    assert problems_in(tmp_path, "ci.yml", text) == ["mcr.microsoft.com/playwright:v1.65.1-noble has no digest"]


def test_a_problem_names_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "x.Dockerfile"
    path.write_text(f"FROM python:3.14@{DIGEST}\nFROM alpine:3.23\n", encoding="utf-8")
    (problem,) = check_pins.check_file(path)
    assert (problem.path, problem.line, problem.image) == (path, 2, "alpine:3.23")


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
    assert problems == [], "Run  python3 -I tools/check_pins.py --resolve  where Docker can reach the registries."


def test_the_repository_check_reads_the_files_that_name_images() -> None:
    names = {path.relative_to(ROOT).as_posix() for path in check_pins.files_to_check(ROOT)}
    assert {"infra/compose.yaml", "infra/images/app.Dockerfile", ".github/workflows/ci.yml", "infra/tests/rehearse_tailnet.py"} <= names


def test_the_browser_image_matches_the_playwright_package() -> None:
    package = json.loads((ROOT / "client" / "package.json").read_text(encoding="utf-8"))
    version = package["devDependencies"]["@playwright/test"]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f'"mcr.microsoft.com/playwright:v{version}-noble' in workflow
