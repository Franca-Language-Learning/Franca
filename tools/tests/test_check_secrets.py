"""Tests of the secrets part of scripts/check (story E01-013).

scripts/check runs  python3 -I tools/install_program.py gitleaks  and then gitleaks. Here python3 is replaced by a
stand-in on PATH that exits with one of install_program.py's exit codes, so each case can be run without a download.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_secrets_part(tmp_path: Path, install_exit_code: int, in_pipeline: bool = False) -> subprocess.CompletedProcess[str]:
    """Runs scripts/check secrets with a stand-in python3. On exit code 0, the stand-in prints the path of a stand-in
    gitleaks that writes its arguments to a file."""
    bin_folder = tmp_path / "bin"
    bin_folder.mkdir(parents=True)
    gitleaks = tmp_path / "gitleaks"
    gitleaks.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/gitleaks-arguments"\n', encoding="utf-8")
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
    arguments = (tmp_path / "gitleaks-arguments").read_text(encoding="utf-8").split()
    assert arguments[0] == "git"
    assert {"--verbose", "--redact", "--log-opts=HEAD"} <= set(arguments)


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
