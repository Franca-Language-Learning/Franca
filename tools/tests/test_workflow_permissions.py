"""Tests of the permissions given to the jobs in .github/workflows (story E01-013).

A job with the id-token permission can ask GitHub for a token that proves it ran in this repository, and that token
is what cosign signs the release images with. For this reason the permission is given to the release jobs only. Those
jobs run in the protected "release" environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


def jobs() -> list[tuple[str, str, dict[str, Any]]]:
    """Each job in the workflows, as (workflow file name, job id, job)."""
    found = []
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        found += [(path.name, job_id, job) for job_id, job in workflow["jobs"].items()]
    return found


def has_id_token(job: dict[str, Any]) -> bool:
    """True when the job can ask for an OIDC token: id-token: write, or permissions: write-all."""
    permissions = job.get("permissions") or {}
    if isinstance(permissions, str):
        return permissions == "write-all"
    return bool(permissions.get("id-token") == "write")


def test_the_workflows_are_found() -> None:
    assert {"ci.yml", "release.yml", "scorecard.yml"} <= {path.name for path in WORKFLOWS}


def test_no_workflow_gives_permissions_to_all_its_jobs() -> None:
    for path in WORKFLOWS:
        assert yaml.safe_load(path.read_text(encoding="utf-8")).get("permissions") == {}, path.name


def test_only_the_release_jobs_have_the_id_token_permission() -> None:
    with_id_token = {(name, job_id) for name, job_id, job in jobs() if has_id_token(job)}
    assert with_id_token == {("release.yml", "images"), ("release.yml", "release")}


def test_the_jobs_with_the_id_token_permission_run_in_the_release_environment() -> None:
    for name, job_id, job in jobs():
        if has_id_token(job):
            assert job.get("environment") == "release", f"{name} {job_id}"


def test_the_id_token_check_reads_each_form_of_permissions() -> None:
    assert has_id_token({"permissions": {"id-token": "write"}})
    assert has_id_token({"permissions": "write-all"})
    assert not has_id_token({"permissions": {"id-token": "none"}})
    assert not has_id_token({"permissions": "read-all"})
    assert not has_id_token({})
