"""Tests for tools/run_osv_scanner.py (story E01-013, re-check finding N2).

OSV-Scanner exits with 1 when it finds a known vulnerability, and it does so even when it has logged an error, for
example for a lockfile that it could not read. The script runs OSV-Scanner with only its errors logged, and the job
fails when OSV-Scanner stops with an error or logs one, so that partial results are not judged. The OSV-Scanner in
these tests is a made-up program.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "osv-scanner.yml"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_osv_scanner", ROOT / "tools" / "run_osv_scanner.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_osv_scanner"] = module
    spec.loader.exec_module(module)
    return module


runner = load_tool()


def fake_scanner(tmp_path: Path, exit_code: int = 0, errors: str = "") -> Path:
    """A made-up OSV-Scanner that writes its arguments to arguments.json, prints the errors on stderr and exits with
    the exit code."""
    program = tmp_path / "osv-scanner"
    program.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(tmp_path / 'arguments.json')!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"sys.stderr.write({errors!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    program.chmod(0o755)
    return program


def run(tmp_path: Path, program: Path, output_format: str = "json") -> int:
    return int(runner.main([str(program), output_format, str(tmp_path / f"results.{output_format}")]))


def test_the_json_scan_lists_the_packages_without_findings_too(tmp_path: Path) -> None:
    # With --all-packages, a lockfile in which OSV-Scanner found no packages is missing from the output, so that
    # tools/check_osv_results.py --lockfile can notice it.
    run(tmp_path, fake_scanner(tmp_path), "json")
    arguments = json.loads((tmp_path / "arguments.json").read_text(encoding="utf-8"))
    assert arguments == [
        "scan",
        "source",
        "--recursive",
        "--all-packages",
        "--verbosity",
        "error",
        "--format",
        "json",
        "--output-file",
        str(tmp_path / "results.json"),
        ".",
    ]


def test_the_scan_is_recursive_with_only_errors_logged(tmp_path: Path) -> None:
    run(tmp_path, fake_scanner(tmp_path), "sarif")
    arguments = json.loads((tmp_path / "arguments.json").read_text(encoding="utf-8"))
    assert arguments == [
        "scan",
        "source",
        "--recursive",
        "--verbosity",
        "error",
        "--format",
        "sarif",
        "--output-file",
        str(tmp_path / "results.sarif"),
        ".",
    ]


@pytest.mark.parametrize("exit_code", [0, 1], ids=["no vulnerabilities", "vulnerabilities found"])
def test_a_scan_that_finished_with_no_error_passes(tmp_path: Path, exit_code: int) -> None:
    assert run(tmp_path, fake_scanner(tmp_path, exit_code)) == 0


def test_an_error_logged_with_exit_code_1_fails(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    errors = "Error during extraction: (extracting as python/uvlock) could not parse uv.lock\n"
    assert run(tmp_path, fake_scanner(tmp_path, 1, errors)) == runner.EXIT_FAILED
    printed = capsys.readouterr().err
    assert "Error during extraction" in printed
    assert "OSV-Scanner logged an error" in printed


@pytest.mark.parametrize(
    ("exit_code", "meaning"),
    [
        (127, "an error was logged"),
        (128, "no lockfile was found"),
        (129, "a query to the OSV API failed"),
        (130, "an osv-scanner.toml file could not be read"),
        (2, "exit code 2"),
    ],
)
def test_an_exit_code_above_1_fails_and_is_explained(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, exit_code: int, meaning: str
) -> None:
    assert run(tmp_path, fake_scanner(tmp_path, exit_code)) == runner.EXIT_FAILED
    printed = capsys.readouterr().err
    assert f"exit code {exit_code}" in printed
    assert meaning in printed


def test_a_program_that_cannot_be_started_fails(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert run(tmp_path, tmp_path / "missing") == runner.EXIT_FAILED
    assert "could not be started" in capsys.readouterr().err


def test_in_the_pipeline_the_failure_is_an_error_annotation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    run(tmp_path, fake_scanner(tmp_path, 128))
    assert "::error title=OSV-Scanner::" in capsys.readouterr().out


def test_in_the_pipeline_the_error_lines_cannot_start_a_workflow_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The error lines can quote file names and parser messages from a pull request.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    run(tmp_path, fake_scanner(tmp_path, 127, "Error during extraction: bad file\n::add-mask::x\n"))
    lines = capsys.readouterr().out.splitlines()

    start = lines.index("Error during extraction: bad file") - 1
    token = lines[start].removeprefix("::stop-commands::")
    assert lines[start] == f"::stop-commands::{token}"
    assert len(token) >= 32
    assert lines[start + 2 : start + 4] == ["::add-mask::x", f"::{token}::"]
    assert lines[-1].startswith("::error title=OSV-Scanner::")


def test_outside_the_pipeline_the_error_lines_are_written_as_they_are(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    run(tmp_path, fake_scanner(tmp_path, 127, "Error during extraction: bad file\n"))
    printed = capsys.readouterr()
    assert printed.err.startswith("Error during extraction: bad file\n")
    assert "stop-commands" not in printed.out


def test_the_workflow_runs_osv_scanner_through_the_script() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"$osv_scanner" scan' not in text
    assert text.count("python3 -I tools/run_osv_scanner.py") == 3
