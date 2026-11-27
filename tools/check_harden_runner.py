"""Harden-Runner check: the pipeline's jobs are in block mode, each with its own list of allowed endpoints (E01-013).

Harden-Runner (step-security/harden-runner) logs a job's network connections. In block mode, a connection to a host that
is not in the job's allowed-endpoints is refused. These problems are reported for the jobs in .github/workflows:

  - the job calls a reusable workflow (uses: at job level). The steps of a reusable workflow run in a job that is
    written in another repository, so no Harden-Runner step can be added to it. The jobs in
    REUSABLE_WORKFLOW_EXCEPTIONS are not reported, and each of them has a reason. An exception for a job that does
    not call a reusable workflow, or that was removed from its workflow file, is reported, so that the list is kept
    short;
  - the job has no Harden-Runner step, or the Harden-Runner step is not the first step;
  - the step is in audit mode, apart from the jobs in release.yml, which stay in audit mode until the endpoints of
    the first release are known;
  - the step is in block mode with no allowed endpoints;
  - the endpoints are on separate lines. The agent splits the list at spaces only, so the list is written as a folded
    block (>), one endpoint per line, with no blank or more-indented line;
  - an endpoint is not host:port, has a port outside 1 to 65535, or is listed twice, or the list is not in
    alphabetical order;
  - a second Harden-Runner step in the job is not in block mode;
  - a step is not a mapping.

With no egress-policy, the action is in block mode (the default in its action.yml). In Harden-Runner 2.23.0 (agent
v0.18.1), these hosts are allowed in block mode without a list:

  - in the agent's code: *.actions.githubusercontent.com, codeload.github.com,
    actions-results-receiver-production.githubapp.com and productionresultssa*.blob.core.windows.net;
  - from GitHub's meta API, read when the job starts, and missing if that request fails: github.com, *.github.com,
    *.githubapp.com, ghcr.io and the productionresultssa<n>.blob.core.windows.net hosts;
  - StepSecurity's API, while telemetry is on (the default): agent.api.stepsecurity.io and prod.app-api.stepsecurity.io;
  - by address: Azure's 168.63.129.16 and 169.254.169.254, and the private ranges 10.0.0.0/8, 172.16.0.0/12 and
    192.168.0.0/16.

The GitHub hosts that a job's steps call, such as github.com, are listed anyway, because the hosts from the meta API
are missing when the request for them fails.

  uv run python -I tools/check_harden_runner.py    check the repository

The steps for adding an endpoint are in docs/package-updates.md, under "Allowed endpoints in the pipeline".
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = "step-security/harden-runner@"
# The workflow whose jobs may stay in audit mode.
AUDIT_ALLOWED = "release.yml"
# The jobs that may call a reusable workflow, as (workflow file name, job id), with the reason.
REUSABLE_WORKFLOW_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("osv-scanner.yml", "scan-pr"): "removed after the required check is swapped (N2)",
    ("osv-scanner.yml", "scan-main"): "removed after the required check is swapped (N2)",
}
# A host name, which may start with *. for a wildcard, a colon and a port number.
ENDPOINT = re.compile(r"^(?:\*\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+:(?P<port>[0-9]{1,5})$")
HIGHEST_PORT = 65535
SEPARATE_LINES = (
    "the allowed endpoints are on separate lines (a | block, or a blank or more-indented line in a > block); "
    "write them as a folded block (allowed-endpoints: >) with one endpoint on each line"
)


@dataclass(frozen=True)
class Job:
    """A job that has steps, as written in the workflow file. A step that is not a mapping is kept as it is."""

    workflow: str
    job_id: str
    steps: list[Any]

    def harden_runner_steps(self) -> list[tuple[int, dict[str, Any]]]:
        """Each Harden-Runner step, as (its number in the job, counted from 1, and its settings under with:)."""
        return [
            (number, dict(step.get("with") or {}))
            for number, step in enumerate(self.steps, start=1)
            if isinstance(step, dict) and str(step.get("uses", "")).startswith(ACTION)
        ]


@dataclass(frozen=True)
class Problem:
    workflow: str
    job_id: str
    message: str

    def __str__(self) -> str:
        return f"{self.workflow}, job {self.job_id}: {self.message}"


def workflow_files(root: Path) -> list[Path]:
    folder = root / ".github" / "workflows"
    return sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")])


def all_jobs(root: Path) -> Iterator[tuple[str, str, Any]]:
    """Each job in the workflows, as (workflow file name, job id, the job as written)."""
    for path in workflow_files(root):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            yield path.name, str(job_id), job


def calls_reusable_workflow(job: Any) -> bool:
    return isinstance(job, dict) and "uses" in job


def jobs_with_steps(root: Path) -> Iterator[Job]:
    """Each job in the workflows, apart from jobs that call a reusable workflow (uses: at job level), which have no
    steps of their own."""
    for workflow, job_id, job in all_jobs(root):
        if isinstance(job, dict) and not calls_reusable_workflow(job):
            yield Job(workflow, job_id, list(job.get("steps") or []))


def reusable_workflow_problems(root: Path) -> list[Problem]:
    """The jobs that call a reusable workflow and are not exceptions, the exceptions with no reason, and the
    exceptions for jobs that do not call a reusable workflow or are not in their workflow file. An exception for a
    workflow file that is not in the repository is not reported."""
    problems = []
    found = set()
    for workflow, job_id, job in all_jobs(root):
        found.add((workflow, job_id))
        reason = REUSABLE_WORKFLOW_EXCEPTIONS.get((workflow, job_id))
        if calls_reusable_workflow(job):
            if reason is None:
                problems.append(Problem(workflow, job_id, "the job calls a reusable workflow, which has no Harden-Runner step"))
            elif not reason.strip():
                problems.append(Problem(workflow, job_id, "the job is on the list of exceptions for reusable workflows with no reason"))
        elif reason is not None:
            problems.append(
                Problem(workflow, job_id, "the job is on the list of exceptions for reusable workflows, and it does not call one")
            )
    files = {path.name for path in workflow_files(root)}
    for workflow, job_id in REUSABLE_WORKFLOW_EXCEPTIONS:
        if workflow in files and (workflow, job_id) not in found:
            problems.append(
                Problem(workflow, job_id, "the job is on the list of exceptions for reusable workflows, and it is not in the workflow")
            )
    return problems


def harden_runner_jobs(root: Path) -> Iterator[Job]:
    """Each job in the workflows that has a Harden-Runner step."""
    return (job for job in jobs_with_steps(root) if job.harden_runner_steps())


def endpoint_problems(endpoints: str) -> list[str]:
    """The problems with a list of allowed endpoints, as the action receives it."""
    if "\n" in endpoints.strip():
        return [SEPARATE_LINES]
    listed = endpoints.split()
    problems: list[str] = []
    for endpoint in listed:
        match = ENDPOINT.match(endpoint)
        if not match:
            problems.append(f"allowed endpoint {endpoint!r} is not written as host:port")
        elif not 1 <= int(match["port"]) <= HIGHEST_PORT:
            problems.append(f"allowed endpoint {endpoint!r} has a port outside 1 to {HIGHEST_PORT}")
    seen: set[str] = set()
    for endpoint in listed:
        if endpoint in seen:
            problems.append(f"allowed endpoint {endpoint!r} is listed twice")
        seen.add(endpoint)
    if listed != sorted(listed):
        problems.append("the allowed endpoints are not in alphabetical order")
    return problems


def settings_problems(settings: dict[str, Any], audit_allowed: bool, name: str = "Harden-Runner") -> list[str]:
    """The problems with the settings of one Harden-Runner step. The name is used at the start of the messages."""
    policy = str(settings.get("egress-policy", "block"))
    endpoints = str(settings.get("allowed-endpoints") or "")
    if policy == "audit":
        return [] if audit_allowed else [f"{name} is in audit mode, not block mode"]
    if policy != "block":
        return [f"{name} has egress-policy {policy!r}, which is neither audit nor block"]
    if not endpoints.strip():
        return [f"{name} is in block mode with no allowed endpoints"]
    return endpoint_problems(endpoints)


def job_problems(job: Job) -> list[str]:
    problems = [f"step {number} is not a mapping" for number, step in enumerate(job.steps, start=1) if not isinstance(step, dict)]
    steps = job.harden_runner_steps()
    if not steps:
        return [*problems, "the job has no Harden-Runner step"]
    (first, settings), later = steps[0], steps[1:]
    if first != 1:
        problems.append(f"Harden-Runner is step {first}, not the first step")
    problems += settings_problems(settings, audit_allowed=job.workflow == AUDIT_ALLOWED)
    for number, settings in later:
        problems += settings_problems(settings, audit_allowed=False, name=f"Harden-Runner step {number}")
    return problems


def check_repository(root: Path) -> list[Problem]:
    with_steps = [Problem(job.workflow, job.job_id, message) for job in jobs_with_steps(root) for message in job_problems(job)]
    return reusable_workflow_problems(root) + with_steps


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the pipeline's Harden-Runner steps are in block mode.")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository folder (default: this repository)")
    options = parser.parse_args(arguments)
    problems = check_repository(options.root)
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"\n{len(problems)} problem(s) with Harden-Runner. The steps for fixing them are in docs/package-updates.md, "
            'under "Allowed endpoints in the pipeline".'
        )
        return 1
    jobs = len(list(jobs_with_steps(options.root)))
    print(f"Harden-Runner: {jobs} job(s) checked, no problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
