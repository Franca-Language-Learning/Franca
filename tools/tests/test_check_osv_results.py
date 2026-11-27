"""Tests for tools/check_osv_results.py (story E01-013, re-check finding N2).

OSV-Scanner exits with 1 for any known vulnerability, so its exit code does not tell a finding that has to be fixed
before a merge from one that can wait. The script reads OSV-Scanner's JSON output, and the job fails for a finding
that is rated high or critical and has a fixed version, and for a known malicious package. The OSV records in these
tests are made up.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_osv_results", ROOT / "tools" / "check_osv_results.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_osv_results"] = module
    spec.loader.exec_module(module)
    return module


osv = load_tool()


def record(
    vuln_id: str,
    package: str = "example-package",
    ecosystem: str = "PyPI",
    fixed: str | None = "2.0.1",
    label: str | None = None,
    aliases: tuple[str, ...] = (),
    database_specific: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A made-up OSV record for one package, with a fixed version or none, and a severity label or none."""
    events: list[dict[str, str]] = [{"introduced": "0"}]
    events.append({"fixed": fixed} if fixed else {"last_affected": "2.0.0"})
    found: dict[str, Any] = {
        "id": vuln_id,
        "aliases": list(aliases),
        "summary": "A made-up vulnerability",
        "affected": [{"package": {"name": package, "ecosystem": ecosystem}, "ranges": [{"type": "ECOSYSTEM", "events": events}]}],
    }
    if label:
        found["database_specific"] = {"severity": label}
    if database_specific is not None:
        found["database_specific"] = database_specific
    return found


def scan(
    *records: dict[str, Any],
    max_severity: str = "",
    package: str = "example-package",
    version: str = "2.0.0",
    ecosystem: str = "PyPI",
    path: str = "/work/uv.lock",
    grouped: bool = True,
    group_aliases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """OSV-Scanner's JSON output for one package in one lockfile. The records are one group: one vulnerability under
    several IDs, with the highest CVSS score that OSV-Scanner worked out for it."""
    found: dict[str, Any] = {
        "package": {"name": package, "version": version, "ecosystem": ecosystem},
        "vulnerabilities": list(records),
    }
    if grouped:
        ids = [r["id"] for r in records]
        found["groups"] = [{"ids": ids, "aliases": [*ids, *group_aliases], "max_severity": max_severity}]
    return {"results": [{"source": {"path": path, "type": "lockfile"}, "packages": [found]}]}


def blocking(output: dict[str, Any]) -> list[str]:
    return [finding.ids[0] for finding in osv.findings(output) if finding.blocks_merge]


# --- Which findings fail the job


def test_a_cvss_score_of_7_with_a_fixed_version_fails_the_job() -> None:
    assert blocking(scan(record("GHSA-0001"), max_severity="7.0")) == ["GHSA-0001"]


def test_a_cvss_score_below_7_does_not_fail_the_job() -> None:
    assert blocking(scan(record("GHSA-0002"), max_severity="6.9")) == []


def test_a_high_finding_with_no_fixed_version_does_not_fail_the_job() -> None:
    assert blocking(scan(record("GHSA-0003", fixed=None), max_severity="9.8")) == []


@pytest.mark.parametrize("label", ["HIGH", "CRITICAL", "high"])
def test_with_no_cvss_score_a_high_or_critical_label_fails_the_job(label: str) -> None:
    assert blocking(scan(record("GHSA-0004", label=label))) == ["GHSA-0004"]


@pytest.mark.parametrize("label", ["MODERATE", "LOW", None])
def test_with_no_cvss_score_a_lower_label_or_no_label_does_not_fail_the_job(label: str | None) -> None:
    assert blocking(scan(record("GHSA-0005", label=label))) == []


def test_a_high_label_fails_the_job_whatever_the_cvss_score() -> None:
    # OSV-Scanner gives no score for a record with a CVSS vector it cannot read, so a lower score from another record
    # of the group can be the only one. The label is read as well.
    assert blocking(scan(record("GHSA-0006", label="HIGH"), max_severity="5.3")) == ["GHSA-0006"]


def test_a_finding_with_a_score_and_a_label_is_listed_with_both() -> None:
    (finding,) = osv.findings(scan(record("GHSA-0022", label="HIGH"), max_severity="5.3"))
    assert "GHSA-0022 in example-package 2.0.0 (PyPI, /work/uv.lock): CVSS 5.3, label HIGH, fixed in 2.0.1" == str(finding)


def test_a_null_label_is_no_label() -> None:
    (finding,) = osv.findings(scan(record("GHSA-0018", database_specific={"severity": None})))
    assert finding.label is None
    assert "no severity given" in str(finding)


# --- Known malicious packages


def test_a_malicious_package_fails_the_job_with_no_severity_and_no_fixed_version() -> None:
    assert blocking(scan(record("MAL-2026-0001", fixed=None))) == ["MAL-2026-0001"]


def test_a_finding_with_a_malicious_alias_fails_the_job() -> None:
    output = scan(record("GHSA-0019", fixed=None, label="LOW"), group_aliases=("MAL-2026-0002",))
    assert blocking(output) == ["GHSA-0019"]


def test_a_record_from_the_malicious_packages_data_fails_the_job() -> None:
    origins = {"malicious-packages-origins": [{"source": "made-up", "id": "x"}]}
    assert blocking(scan(record("GHSA-0020", fixed=None, database_specific=origins))) == ["GHSA-0020"]


def test_a_malicious_package_is_named_as_such_in_the_log(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(json.dumps(scan(record("MAL-2026-0003", fixed=None))), encoding="utf-8")

    assert osv.main([str(results)]) == 1
    printed = capsys.readouterr().out
    assert (
        "MAL-2026-0003 in example-package 2.0.0 (PyPI, /work/uv.lock): known malicious package, no severity given, no fixed version"
        in printed
    )
    assert "remove" in printed


def test_the_records_of_one_vulnerability_are_one_finding() -> None:
    # A GitHub advisory and a PyPI advisory for the same problem: the label is on one record, the fix on the other.
    records = [record("GHSA-0007", fixed=None, label="CRITICAL"), record("PYSEC-0007", fixed="2.0.1")]
    (finding,) = osv.findings(scan(*records))
    assert finding.ids == ("GHSA-0007", "PYSEC-0007")
    assert finding.blocks_merge


def test_a_fixed_version_for_another_package_is_not_counted() -> None:
    assert blocking(scan(record("GHSA-0008", package="other-package"), max_severity="8.1")) == []


@pytest.mark.parametrize("written", ["Example_Package", "example.package", "EXAMPLE-package"])
def test_python_package_names_are_compared_in_their_normal_form(written: str) -> None:
    assert blocking(scan(record("GHSA-0009", package=written), max_severity="8.1")) == ["GHSA-0009"]


def test_npm_package_names_are_compared_as_written() -> None:
    output = scan(record("GHSA-0010", package="Example-Package", ecosystem="npm"), max_severity="8.1", ecosystem="npm")
    assert blocking(output) == []


def test_vulnerabilities_without_groups_cannot_be_read(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(json.dumps(scan(record("GHSA-0011", label="HIGH"), grouped=False)), encoding="utf-8")

    assert osv.main([str(results)]) == osv.EXIT_UNREADABLE
    assert "no groups" in capsys.readouterr().err


def test_a_record_in_no_group_cannot_be_read(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    output = scan(record("GHSA-0012", label="LOW"), max_severity="3.0")
    output["results"][0]["packages"][0]["vulnerabilities"].append(record("GHSA-0021", label="CRITICAL"))
    results = tmp_path / "results.json"
    results.write_text(json.dumps(output), encoding="utf-8")

    assert osv.main([str(results)]) == osv.EXIT_UNREADABLE
    assert "GHSA-0021 is in no group" in capsys.readouterr().err


def test_no_results_means_no_findings() -> None:
    assert osv.findings({"results": []}) == []


# --- What is printed


def test_the_findings_are_listed_with_the_ones_that_fail_the_job_first(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    output = scan(record("GHSA-0013", label="LOW"))
    npm_record = record("GHSA-0014", package="left-pad", ecosystem="npm", fixed="1.4.2")
    npm_scan = scan(npm_record, max_severity="9.1", package="left-pad", version="1.4.0", ecosystem="npm", path="/work/pnpm-lock.yaml")
    output["results"] += npm_scan["results"]
    results = tmp_path / "results.json"
    results.write_text(json.dumps(output), encoding="utf-8")

    assert osv.main([str(results)]) == 1
    printed = capsys.readouterr().out
    assert "GHSA-0014 in left-pad 1.4.0 (npm, /work/pnpm-lock.yaml): CVSS 9.1, fixed in 1.4.2" in printed
    assert "GHSA-0013 in example-package 2.0.0 (PyPI, /work/uv.lock): label LOW, fixed in 2.0.1" in printed
    assert printed.index("GHSA-0014") < printed.index("GHSA-0013")


def test_the_command_exits_with_0_when_no_finding_fails_the_job(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(json.dumps(scan(record("GHSA-0015", fixed=None), max_severity="9.8")), encoding="utf-8")

    assert osv.main([str(results)]) == 0
    printed = capsys.readouterr().out
    assert "GHSA-0015" in printed
    assert "no fixed version" in printed


def test_the_command_says_so_when_there_are_no_findings(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"results": []}), encoding="utf-8")

    assert osv.main([str(results)]) == 0
    assert "No known vulnerabilities" in capsys.readouterr().out


def test_in_the_pipeline_a_finding_that_fails_the_job_is_an_error_annotation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    results = tmp_path / "results.json"
    results.write_text(json.dumps(scan(record("GHSA-0016"), max_severity="7.5")), encoding="utf-8")

    assert osv.main([str(results)]) == 1
    assert "::error title=Known vulnerability::GHSA-0016 in example-package 2.0.0" in capsys.readouterr().out


def test_text_from_the_records_cannot_start_a_workflow_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    output = scan(record("GHSA-0017\n::add-mask::x"), max_severity="7.5")
    results = tmp_path / "results.json"
    results.write_text(json.dumps(output), encoding="utf-8")

    osv.main([str(results)])
    assert all(not line.startswith("::add-mask") for line in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"results": {}}',
        "{}",
        '{"foo": 1}',
        '{"results": [1]}',
        '{"results": [{"packages": "abc"}]}',
        '{"results": [{"packages": [{"vulnerabilities": ["x"]}]}]}',
        '{"results": [{"packages": [{"vulnerabilities": [{"id": "x", "affected": "x"}], "groups": [{"ids": ["x"]}]}]}]}',
    ],
    ids=[
        "not JSON",
        "a list",
        "results not a list",
        "no results key",
        "another key",
        "a result that is a number",
        "packages that are a string",
        "a vulnerability that is a string",
        "affected that is a string",
    ],
)
def test_output_that_cannot_be_read_is_reported(capsys: pytest.CaptureFixture[str], tmp_path: Path, content: str) -> None:
    results = tmp_path / "results.json"
    results.write_text(content, encoding="utf-8")

    assert osv.main([str(results)]) == osv.EXIT_UNREADABLE
    assert "could not be read" in capsys.readouterr().err


def test_a_missing_results_file_is_reported(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert osv.main([str(tmp_path / "missing.json")]) == osv.EXIT_UNREADABLE
    assert "could not be read" in capsys.readouterr().err
