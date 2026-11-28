"""Tests for tools/check_osv_ignores.py (story E01-013, owner decision on review round 2 of pull request #41).

An entry in an osv-scanner.toml file removes findings from OSV-Scanner's output before the OSV scan reads it. The
owner decided that a known malicious package (an ID that starts with MAL-) cannot be ignored, and that an entry that
ignores something needs an end date in effectiveUntil, no more than 90 days after today. The files in these tests are
made up.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 28)


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_osv_ignores", ROOT / "tools" / "check_osv_ignores.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_osv_ignores"] = module
    spec.loader.exec_module(module)
    return module


ignores = load_tool()


def problems(text: str) -> list[str]:
    return list(ignores.problems(text, "osv-scanner.toml", TODAY))


# --- [[IgnoredVulns]]


def test_an_entry_with_an_end_date_within_90_days_is_accepted() -> None:
    assert problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\neffectiveUntil = 2027-02-26\nreason = "Not used."\n') == []


def test_an_entry_that_ignores_a_malicious_package_is_refused() -> None:
    (problem,) = problems('[[IgnoredVulns]]\nid = "MAL-2026-0001"\neffectiveUntil = 2026-12-31\n')
    assert "MAL-2026-0001" in problem
    assert "malicious package cannot be ignored" in problem


def test_a_malicious_id_is_refused_whatever_its_case() -> None:
    assert problems('[[IgnoredVulns]]\nid = "mal-2026-0002"\neffectiveUntil = 2026-12-31\n')


def test_an_entry_with_no_end_date_is_refused() -> None:
    (problem,) = problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\n')
    assert "has no end date (effectiveUntil)" in problem


def test_an_end_date_more_than_90_days_ahead_is_refused() -> None:
    (problem,) = problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\neffectiveUntil = 2027-02-27\n')
    assert "2027-02-27 is more than 90 days after today (2026-11-28)" in problem


def test_an_end_date_with_a_time_is_read_as_its_date() -> None:
    assert problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\neffectiveUntil = 2027-01-31T00:00:00Z\n') == []


def test_an_end_date_that_is_not_a_date_is_refused() -> None:
    (problem,) = problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\neffectiveUntil = "2027-01-31"\n')
    assert "is not a TOML date" in problem


def test_the_old_key_ignore_until_is_refused() -> None:
    # OSV-Scanner v2.7.1 still reads ignoreUntil, with a warning that --verbosity error hides.
    (problem,) = problems('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\nignoreUntil = 2026-12-31\n')
    assert "use effectiveUntil in place of ignoreUntil" in problem


def test_each_problem_is_listed() -> None:
    text = '[[IgnoredVulns]]\nid = "MAL-2026-0003"\n\n[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\n'
    assert len(problems(text)) == 3


# --- [[PackageOverrides]]


@pytest.mark.parametrize("setting", ["ignore = true", "vulnerability.ignore = true"])
def test_a_package_override_that_ignores_needs_an_end_date(setting: str) -> None:
    (problem,) = problems(f'[[PackageOverrides]]\nname = "example-package"\necosystem = "PyPI"\n{setting}\n')
    assert "example-package" in problem
    assert "has no end date (effectiveUntil)" in problem


def test_a_package_override_that_ignores_with_an_end_date_is_accepted() -> None:
    text = '[[PackageOverrides]]\nname = "example-package"\nignore = true\neffectiveUntil = 2026-12-31\n'
    assert problems(text) == []


def test_a_package_override_that_does_not_ignore_needs_no_end_date() -> None:
    assert problems('[[PackageOverrides]]\nname = "example-package"\nlicense.override = ["MIT"]\n') == []


# --- Files that cannot be read


@pytest.mark.parametrize(
    "text",
    ["[[IgnoredVulns]\n", 'IgnoredVulns = "x"\n', "IgnoredVulns = [1]\n", "[PackageOverrides]\nname = 1\n"],
    ids=["not TOML", "a string", "a number in the list", "a table in place of a list"],
)
def test_a_file_that_cannot_be_read_is_refused(text: str) -> None:
    assert problems(text)


# --- The command


def test_the_command_lists_the_problems_and_exits_with_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    config = tmp_path / "osv-scanner.toml"
    config.write_text('[[IgnoredVulns]]\nid = "MAL-2026-0004"\neffectiveUntil = 2026-12-31\n', encoding="utf-8")

    assert ignores.main([str(config)], today=TODAY) == 1
    printed = capsys.readouterr().err
    assert f"check_osv_ignores: {config}: " in printed
    assert "MAL-2026-0004" in printed


def test_the_command_exits_with_0_when_there_are_no_problems(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    config = tmp_path / "osv-scanner.toml"
    config.write_text('[[IgnoredVulns]]\nid = "GHSA-aaaa-bbbb-cccc"\neffectiveUntil = 2026-12-31\n', encoding="utf-8")

    assert ignores.main([str(config)], today=TODAY) == 0
    assert "1 file(s) checked, no problems found" in capsys.readouterr().out


def test_a_missing_file_is_reported(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert ignores.main([str(tmp_path / "osv-scanner.toml")], today=TODAY) == 1
    assert "could not be read" in capsys.readouterr().err


def test_the_files_in_the_repository_pass() -> None:
    assert ignores.main([]) == 0


def test_the_files_are_found_by_name_in_the_repository() -> None:
    found = ignores.config_files(ROOT)
    assert all(path.name == "osv-scanner.toml" for path in found)


def test_scripts_check_runs_the_check() -> None:
    assert "../tools/check_osv_ignores.py" in (ROOT / "scripts" / "check").read_text(encoding="utf-8")
