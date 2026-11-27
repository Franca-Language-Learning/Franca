"""Harden-Runner check: the pipeline's jobs are in block mode, each with its own list of allowed endpoints (E01-013).

Harden-Runner (step-security/harden-runner) watches a job's network connections. In audit mode it lists them, and in
block mode it refuses connections to hosts that are not in the job's allowed-endpoints. These are reported as problems,
for each job in .github/workflows that has a Harden-Runner step:

  - the step is in audit mode, apart from the jobs in release.yml, which stay in audit mode until the endpoints of
    the first release are known;
  - the step is in block mode with no allowed endpoints;
  - the endpoints are on separate lines of a literal block (|). The agent splits the list at spaces only, so the list
    is written as a folded block (>), one endpoint per line;
  - an endpoint is not host:port, is listed twice, or the list is not in alphabetical order.

With no egress-policy, the action is in block mode (the default in its action.yml). GitHub's own runner traffic is
allowed by the agent without a list: github.com, *.github.com, *.githubapp.com, *.actions.githubusercontent.com, the
results storage (productionresultssa*.blob.core.windows.net) and Azure's address 168.63.129.16.

  uv run python -I tools/check_harden_runner.py    check the repository

The steps for adding an endpoint are in docs/package-updates.md, under "Connections from the pipeline".
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
# A host name, which may start with *. for a wildcard, a colon and a port number.
ENDPOINT = re.compile(r"^(?:\*\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+:[0-9]{1,5}$")


@dataclass(frozen=True)
class HardenRunnerJob:
    """A job with a Harden-Runner step, with the step's settings (its with: mapping)."""

    workflow: str
    job_id: str
    settings: dict[str, Any]


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


def harden_runner_jobs(root: Path) -> Iterator[HardenRunnerJob]:
    """Each job in the workflows that has a Harden-Runner step. A job that calls a reusable workflow has no steps."""
    for path in workflow_files(root):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith(ACTION):
                    yield HardenRunnerJob(path.name, str(job_id), dict(step.get("with") or {}))
                    break


def endpoint_problems(endpoints: str) -> list[str]:
    """The problems with a list of allowed endpoints, as the action receives it."""
    if "\n" in endpoints.strip():
        return ["the allowed endpoints are on separate lines; write them as a folded block (allowed-endpoints: >)"]
    listed = endpoints.split()
    problems = [f"allowed endpoint {endpoint!r} is not written as host:port" for endpoint in listed if not ENDPOINT.match(endpoint)]
    seen: set[str] = set()
    for endpoint in listed:
        if endpoint in seen:
            problems.append(f"allowed endpoint {endpoint!r} is listed twice")
        seen.add(endpoint)
    if listed != sorted(listed):
        problems.append("the allowed endpoints are not in alphabetical order")
    return problems


def job_problems(job: HardenRunnerJob) -> list[str]:
    policy = str(job.settings.get("egress-policy", "block"))
    endpoints = str(job.settings.get("allowed-endpoints") or "")
    if policy == "audit":
        return [] if job.workflow == AUDIT_ALLOWED else ["Harden-Runner is in audit mode, not block mode"]
    if policy != "block":
        return [f"Harden-Runner has egress-policy {policy!r}, which is neither audit nor block"]
    if not endpoints.strip():
        return ["Harden-Runner is in block mode with no allowed endpoints"]
    return endpoint_problems(endpoints)


def check_repository(root: Path) -> list[Problem]:
    return [Problem(job.workflow, job.job_id, message) for job in harden_runner_jobs(root) for message in job_problems(job)]


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the pipeline's Harden-Runner steps are in block mode.")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository folder (default: this repository)")
    options = parser.parse_args(arguments)
    problems = check_repository(options.root)
    for problem in problems:
        print(problem)
    if problems:
        print(
            f'\n{len(problems)} problem(s) with Harden-Runner. The steps are in docs/package-updates.md, under "Connections from the pipeline".'
        )
        return 1
    jobs = len(list(harden_runner_jobs(options.root)))
    print(f"Harden-Runner: {jobs} job(s) checked, with no problem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
