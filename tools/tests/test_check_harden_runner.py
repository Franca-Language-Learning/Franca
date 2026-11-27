"""Tests for tools/check_harden_runner.py (story E01-013).

Harden-Runner in block mode refuses connections from a job to any host that is not in the job's list of allowed
endpoints. The check reports a job with a Harden-Runner step that is in audit mode, apart from the jobs in release.yml,
and a job in block mode with no list or with a list the agent cannot read.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARDEN_RUNNER = "step-security/harden-runner@" + "a" * 40


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_harden_runner", ROOT / "tools" / "check_harden_runner.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_harden_runner"] = module
    spec.loader.exec_module(module)
    return module


check_harden_runner = load_tool()


def workflow(harden_runner_settings: str, name: str = "ci.yml", job: str = "build") -> tuple[str, str]:
    """A workflow file with one job, whose first step is Harden-Runner with the given lines under with:."""
    settings = "".join(f"          {line}\n" for line in harden_runner_settings.splitlines())
    text = f"""\
name: Test
on: push
jobs:
  {job}:
    runs-on: ubuntu-24.04
    steps:
      - uses: {HARDEN_RUNNER}
        with:
{settings}      - run: echo hello
"""
    return name, text


def problems_in(tmp_path: Path, *workflows: tuple[str, str]) -> list[str]:
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in workflows:
        (folder / name).write_text(text, encoding="utf-8")
    return [str(problem) for problem in check_harden_runner.check_repository(tmp_path)]


def test_a_job_in_block_mode_with_a_sorted_list_has_no_problem(tmp_path: Path) -> None:
    settings = "egress-policy: block\nallowed-endpoints: >\n  api.github.com:443\n  deb.debian.org:80\n  github.com:443"

    assert problems_in(tmp_path, workflow(settings)) == []


def test_a_job_in_audit_mode_is_reported(tmp_path: Path) -> None:
    assert problems_in(tmp_path, workflow("egress-policy: audit")) == ["ci.yml, job build: Harden-Runner is in audit mode, not block mode"]


def test_the_jobs_in_the_release_workflow_may_be_in_audit_mode(tmp_path: Path) -> None:
    assert problems_in(tmp_path, workflow("egress-policy: audit", name="release.yml")) == []


def test_a_job_in_block_mode_with_no_endpoints_is_reported(tmp_path: Path) -> None:
    assert problems_in(tmp_path, workflow("egress-policy: block")) == [
        "ci.yml, job build: Harden-Runner is in block mode with no allowed endpoints"
    ]


def test_a_job_in_the_release_workflow_in_block_mode_needs_endpoints_too(tmp_path: Path) -> None:
    assert problems_in(tmp_path, workflow("egress-policy: block", name="release.yml")) == [
        "release.yml, job build: Harden-Runner is in block mode with no allowed endpoints"
    ]


def test_with_no_egress_policy_the_action_is_in_block_mode(tmp_path: Path) -> None:
    # The default of egress-policy in Harden-Runner's action.yml is block.
    assert problems_in(tmp_path, workflow("disable-sudo: true")) == [
        "ci.yml, job build: Harden-Runner is in block mode with no allowed endpoints"
    ]


def test_an_unknown_egress_policy_is_reported(tmp_path: Path) -> None:
    assert problems_in(tmp_path, workflow("egress-policy: Block\nallowed-endpoints: github.com:443")) == [
        "ci.yml, job build: Harden-Runner has egress-policy 'Block', which is neither audit nor block"
    ]


def test_endpoints_on_separate_lines_of_a_literal_block_are_reported(tmp_path: Path) -> None:
    # The agent splits the list at spaces only, so the lines have to be folded into one with >.
    settings = "egress-policy: block\nallowed-endpoints: |\n  api.github.com:443\n  github.com:443"

    assert problems_in(tmp_path, workflow(settings)) == [
        "ci.yml, job build: the allowed endpoints are on separate lines; write them as a folded block (allowed-endpoints: >)"
    ]


def test_an_endpoint_with_no_port_is_reported(tmp_path: Path) -> None:
    settings = "egress-policy: block\nallowed-endpoints: >\n  api.github.com\n  github.com:443"

    assert problems_in(tmp_path, workflow(settings)) == ["ci.yml, job build: allowed endpoint 'api.github.com' is not written as host:port"]


def test_a_wildcard_endpoint_is_accepted(tmp_path: Path) -> None:
    settings = "egress-policy: block\nallowed-endpoints: >\n  *.data.mcr.microsoft.com:443\n  mcr.microsoft.com:443"

    assert problems_in(tmp_path, workflow(settings)) == []


def test_endpoints_out_of_order_are_reported(tmp_path: Path) -> None:
    settings = "egress-policy: block\nallowed-endpoints: >\n  github.com:443\n  api.github.com:443"

    assert problems_in(tmp_path, workflow(settings)) == ["ci.yml, job build: the allowed endpoints are not in alphabetical order"]


def test_an_endpoint_listed_twice_is_reported(tmp_path: Path) -> None:
    settings = "egress-policy: block\nallowed-endpoints: >\n  github.com:443\n  github.com:443"

    assert problems_in(tmp_path, workflow(settings)) == ["ci.yml, job build: allowed endpoint 'github.com:443' is listed twice"]


def test_a_job_without_harden_runner_and_a_reusable_workflow_job_are_not_reported(tmp_path: Path) -> None:
    text = """\
on: push
jobs:
  plain:
    runs-on: ubuntu-24.04
    steps:
      - run: echo hello
  reused:
    uses: example/workflows/.github/workflows/scan.yml@0123456789abcdef0123456789abcdef01234567
"""
    assert problems_in(tmp_path, ("other.yml", text)) == []


def test_the_problems_of_each_job_are_reported(tmp_path: Path) -> None:
    problems = problems_in(
        tmp_path,
        workflow("egress-policy: audit", name="a.yml", job="first"),
        workflow("egress-policy: block", name="b.yaml", job="second"),
    )

    assert problems == [
        "a.yml, job first: Harden-Runner is in audit mode, not block mode",
        "b.yaml, job second: Harden-Runner is in block mode with no allowed endpoints",
    ]


def test_the_command_exits_with_1_and_lists_the_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    problems_in(tmp_path, workflow("egress-policy: audit"))

    assert check_harden_runner.main(["--root", str(tmp_path)]) == 1
    assert "ci.yml, job build: Harden-Runner is in audit mode, not block mode" in capsys.readouterr().out


def test_the_command_exits_with_0_when_there_is_no_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    problems_in(tmp_path, workflow("egress-policy: block\nallowed-endpoints: github.com:443"))

    assert check_harden_runner.main(["--root", str(tmp_path)]) == 0
    assert "1 job" in capsys.readouterr().out


def test_the_jobs_in_this_repository_pass() -> None:
    assert [str(problem) for problem in check_harden_runner.check_repository(ROOT)] == []


def test_the_jobs_in_this_repository_are_found() -> None:
    jobs = {(job.workflow, job.job_id) for job in check_harden_runner.harden_runner_jobs(ROOT)}

    assert {("ci.yml", "container-bundle"), ("content-guard.yml", "content-guard"), ("release.yml", "images")} <= jobs
