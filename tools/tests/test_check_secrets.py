"""Tests of the secrets part of scripts/check (story E01-013).

scripts/check runs  python3 -I tools/install_program.py gitleaks  and then gitleaks. In most tests python3 is replaced
by a stand-in on PATH that exits with one of install_program.py's exit codes, so each case can be run without a
download. The tests of merge commits run the real gitleaks over a temporary repository with a made-up secret.
"""

from __future__ import annotations

import os
import secrets
import shutil
import string
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_secrets_part(tmp_path: Path, install_exit_code: int, in_pipeline: bool = False) -> subprocess.CompletedProcess[str]:
    """Runs scripts/check secrets with a stand-in python3. On exit code 0, the stand-in prints the path of a stand-in
    gitleaks that adds its arguments to a file, one line for each run."""
    bin_folder = tmp_path / "bin"
    bin_folder.mkdir(parents=True)
    gitleaks = tmp_path / "gitleaks"
    gitleaks.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/gitleaks-arguments"\n', encoding="utf-8")
    gitleaks.chmod(0o755)
    output = f'echo "{gitleaks}"' if install_exit_code == 0 else 'echo "install_program: the reason" >&2'
    python = bin_folder / "python3"
    python.write_text(f"#!/bin/sh\n{output}\nexit {install_exit_code}\n", encoding="utf-8")
    python.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if key != "GITHUB_ACTIONS"}
    environment["PATH"] = f"{bin_folder}{os.pathsep}{environment['PATH']}"
    if in_pipeline:
        environment["GITHUB_ACTIONS"] = "true"
    return subprocess.run([ROOT / "scripts" / "check", "secrets"], capture_output=True, text=True, env=environment, check=False)


def test_gitleaks_is_run_with_the_findings_shown_and_the_secrets_redacted(tmp_path: Path) -> None:
    result = run_secrets_part(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    runs = (tmp_path / "gitleaks-arguments").read_text(encoding="utf-8").splitlines()
    assert len(runs) == 2
    for arguments in runs:
        assert arguments.startswith("git ")
        assert {"--verbose", "--redact"} <= set(arguments.split())
    assert "--log-opts=--diff-merges=remerge HEAD" in runs[0]
    assert "--log-opts=-m --min-parents=3 HEAD" in runs[1]


@pytest.mark.parametrize("in_pipeline", [False, True], ids=["on a computer", "in the pipeline"])
def test_a_changed_download_fails_the_check(tmp_path: Path, in_pipeline: bool) -> None:
    assert run_secrets_part(tmp_path, 3, in_pipeline).returncode != 0


def test_another_platform_skips_the_scan_with_a_message(tmp_path: Path) -> None:
    result = run_secrets_part(tmp_path, 4)
    assert result.returncode == 0
    assert "the secret scan runs in the pipeline" in result.stdout
    assert not (tmp_path / "gitleaks-arguments").exists()


def test_another_platform_fails_the_check_in_the_pipeline(tmp_path: Path) -> None:
    assert run_secrets_part(tmp_path, 4, in_pipeline=True).returncode != 0


def test_no_network_skips_the_scan_on_a_computer_and_fails_it_in_the_pipeline(tmp_path: Path) -> None:
    on_a_computer = run_secrets_part(tmp_path / "computer", 1)
    assert on_a_computer.returncode == 0
    assert "the secret scan runs in the pipeline" in on_a_computer.stdout
    assert run_secrets_part(tmp_path / "pipeline", 1, in_pipeline=True).returncode != 0


# The parts of this repository that the secrets part of scripts/check needs, copied into each temporary repository.
FILES_FOR_THE_SCAN = ("scripts/check", "tools/install_program.py", "tools/programs.txt")


def git(repo: Path, *args: str) -> str:
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=environment).stdout.strip()


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "--no-verify", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def made_up_github_token() -> str:
    """A value in the form of a GitHub token, made at random when the test runs. It is put together here, so that
    this file has nothing in the form of a token for the secret scan to find."""
    characters = string.ascii_letters + string.digits
    return "ghp" + "_" + "".join(secrets.choice(characters) for _ in range(36))


@pytest.fixture
def scanned_repo(tmp_path: Path) -> Path:
    """A new repository with the files of the secret scan in its first commit. The test is skipped on a computer
    where gitleaks cannot be used, and fails in the pipeline, as the secrets part of scripts/check does."""
    installed = subprocess.run(
        ["python3", "-I", ROOT / "tools" / "install_program.py", "gitleaks"], capture_output=True, text=True, check=False
    )
    if installed.returncode != 0:
        if os.environ.get("GITHUB_ACTIONS"):
            pytest.fail(f"gitleaks could not be used in the pipeline: {installed.stderr}")
        pytest.skip(f"gitleaks could not be used on this computer: {installed.stderr}")
    repo = tmp_path / "repo"
    for name in FILES_FOR_THE_SCAN:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, repo / name)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "--no-verify", "-m", "start")
    return repo


def run_scan(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([repo / "scripts" / "check", "secrets"], capture_output=True, text=True, check=False)


def test_a_secret_added_while_a_merge_conflict_is_resolved_is_found(scanned_repo: Path) -> None:
    commit_file(scanned_repo, "settings.txt", "colour = blue\n", "first setting")
    git(scanned_repo, "switch", "-q", "-c", "branch")
    commit_file(scanned_repo, "settings.txt", "colour = green\n", "green")
    git(scanned_repo, "switch", "-q", "main")
    commit_file(scanned_repo, "settings.txt", "colour = red\n", "red")
    assert subprocess.run(["git", "-C", scanned_repo, "merge", "-q", "branch"], capture_output=True, check=False).returncode != 0
    merge = commit_file(scanned_repo, "settings.txt", f"colour = red\ntoken = {made_up_github_token()}\n", "merge")
    result = run_scan(scanned_repo)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"Commit:      {merge}" in result.stdout


def test_a_secret_from_a_merged_branch_is_found_once_under_its_own_commit(scanned_repo: Path) -> None:
    git(scanned_repo, "switch", "-q", "-c", "branch")
    added = commit_file(scanned_repo, "settings.txt", f"token = {made_up_github_token()}\n", "token")
    git(scanned_repo, "switch", "-q", "main")
    git(scanned_repo, "merge", "-q", "--no-ff", "--no-verify", "-m", "merge", "branch")
    result = run_scan(scanned_repo)
    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.count("Commit:") == 1
    assert f"Commit:      {added}" in result.stdout


def test_a_secret_added_in_an_octopus_merge_is_found(scanned_repo: Path) -> None:
    for branch in ("first", "second"):
        git(scanned_repo, "switch", "-q", "-c", branch, "main")
        commit_file(scanned_repo, f"{branch}.txt", f"{branch}\n", branch)
    git(scanned_repo, "switch", "-q", "main")
    commit_file(scanned_repo, "main.txt", "main\n", "main")
    git(scanned_repo, "merge", "-q", "--no-commit", "first", "second")
    merge = commit_file(scanned_repo, "settings.txt", f"token = {made_up_github_token()}\n", "octopus merge")
    assert len(git(scanned_repo, "log", "-1", "--format=%P").split()) == 3
    result = run_scan(scanned_repo)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"Commit:      {merge}" in result.stdout
