"""Reads OSV-Scanner's JSON output and fails for a known vulnerability that has to be fixed before a merge (E01-013).

OSV-Scanner exits with 1 for any known vulnerability in the locked packages, whatever its severity and whether a fix
exists. In the OSV-Scanner jobs in .github/workflows/osv-scanner.yml, this script is run on the scanner's JSON output,
and the job fails when the script exits with 1.

A finding is one vulnerability in one package of one lockfile. OSV-Scanner puts the records that describe the same
vulnerability under different IDs (for example a GitHub advisory and a PyPI advisory) in one group, and a group is
one finding. A finding fails the job when it is rated high or critical and has a fixed version:

  - High or critical: the group's max_severity, which is the highest CVSS base score that OSV-Scanner works out from
    the CVSS vectors of the group's records (CVSS 2, 3 or 4), is 7.0 or more. When there is no score, the severity
    label that the database gives (database_specific.severity, as in the GitHub advisories) is HIGH or CRITICAL on at
    least one record of the group. A score is read before a label, so a score of 6.9 with the label HIGH does not
    fail the job.
  - A fixed version: at least one record of the group names a "fixed" version in a range for the same package (same
    ecosystem and name; Python names are compared in their normal form, as in PEP 503). Whether that fixed version is
    in the same range as the installed version is not checked, so a fix for an older release line counts too.

The other findings are listed and do not fail the job. A vulnerability that is ignored in osv-scanner.toml is left
out of the scanner's output, so it is not listed here either. In GitHub Actions (GITHUB_ACTIONS=true), a finding that
fails the job is also printed as an error annotation.

  python3 -I tools/check_osv_results.py osv-results.json

Exit codes: 0 when no finding fails the job, 1 when at least one does, and 2 when the file could not be read.
Only the Python standard library is needed, so the job needs no project environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HIGH_SCORE = 7.0
HIGH_LABELS = frozenset({"HIGH", "CRITICAL"})
EXIT_FAILS = 1
EXIT_UNREADABLE = 2
PYTHON_NAME_SEPARATORS = re.compile(r"[-_.]+")
NOT_PRINTABLE = re.compile(r"[^\x20-\x7e]+")


class UnreadableResults(Exception):
    """The file is missing, is not JSON, or is not in the form of OSV-Scanner's JSON output."""


@dataclass(frozen=True)
class Finding:
    """One vulnerability, under one or more IDs, in one package of one lockfile."""

    ids: tuple[str, ...]
    package: str
    version: str
    ecosystem: str
    source: str
    score: float | None
    label: str | None
    fixed_versions: tuple[str, ...]

    @property
    def is_high(self) -> bool:
        if self.score is not None:
            return self.score >= HIGH_SCORE
        return self.label in HIGH_LABELS

    @property
    def blocks_merge(self) -> bool:
        return self.is_high and bool(self.fixed_versions)

    def __str__(self) -> str:
        if self.score is not None:
            severity = f"CVSS {self.score:.1f}"
        elif self.label:
            severity = f"label {self.label}"
        else:
            severity = "no severity given"
        fix = f"fixed in {', '.join(self.fixed_versions)}" if self.fixed_versions else "no fixed version"
        aliases = f" ({', '.join(self.ids[1:])})" if len(self.ids) > 1 else ""
        return _printable(f"{self.ids[0]}{aliases} in {self.package} {self.version} ({self.ecosystem}, {self.source}): {severity}, {fix}")


def _printable(text: str) -> str:
    """The text on one line, with characters other than printable ASCII replaced by a space. The text comes from the
    OSV records, and a line break in it could otherwise start a workflow command in the job's log."""
    return NOT_PRINTABLE.sub(" ", text).strip()


def _package_key(ecosystem: str, name: str) -> tuple[str, str]:
    if ecosystem == "PyPI":
        return ecosystem, PYTHON_NAME_SEPARATORS.sub("-", name).lower()
    return ecosystem, name


def _fixed_versions(records: Sequence[dict[str, Any]], ecosystem: str, name: str) -> tuple[str, ...]:
    """The fixed versions that the records name for this package, in the order they are written, without repeats."""
    wanted = _package_key(ecosystem, name)
    found: dict[str, None] = {}
    for record in records:
        for affected in record.get("affected") or []:
            package = affected.get("package") or {}
            if _package_key(str(package.get("ecosystem", "")), str(package.get("name", ""))) != wanted:
                continue
            for version_range in affected.get("ranges") or []:
                for event in version_range.get("events") or []:
                    if "fixed" in event:
                        found[str(event["fixed"])] = None
    return tuple(found)


def _score(max_severity: Any) -> float | None:
    """The score as a number, or None when it is missing or empty. The script is run with the runner's own Python,
    which can be older than the project's, so the code is kept to syntax that Python 3.10 reads."""
    if not isinstance(max_severity, (str, int, float)):
        return None
    try:
        return float(max_severity)
    except ValueError:
        return None


def _label(records: Sequence[dict[str, Any]]) -> str | None:
    """The highest severity label of the records, as written by the database, in capitals."""
    order = ["LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"]
    labels = [str((record.get("database_specific") or {}).get("severity", "")).upper() for record in records]
    known = [label for label in labels if label in order]
    if known:
        return max(known, key=order.index)
    return next((label for label in labels if label), None)


def findings(output: dict[str, Any]) -> list[Finding]:
    """The findings in OSV-Scanner's JSON output, in the order they are written."""
    found = []
    for result in output.get("results") or []:
        source = str((result.get("source") or {}).get("path", ""))
        for entry in result.get("packages") or []:
            package = entry.get("package") or {}
            name, version, ecosystem = str(package.get("name", "")), str(package.get("version", "")), str(package.get("ecosystem", ""))
            records = {str(record.get("id", "")): record for record in entry.get("vulnerabilities") or []}
            groups = entry.get("groups") or [{"ids": [vuln_id]} for vuln_id in records]
            for group in groups:
                ids = tuple(str(vuln_id) for vuln_id in group.get("ids") or [])
                in_group = [records[vuln_id] for vuln_id in ids if vuln_id in records]
                found.append(
                    Finding(
                        ids=ids,
                        package=name,
                        version=version,
                        ecosystem=ecosystem,
                        source=source,
                        score=_score(group.get("max_severity")),
                        label=_label(in_group),
                        fixed_versions=_fixed_versions(in_group, ecosystem, name),
                    )
                )
    return found


def read_results(path: Path) -> dict[str, Any]:
    try:
        output = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UnreadableResults(f"{path} could not be read: {error}") from error
    if not isinstance(output, dict) or not isinstance(output.get("results", []), list):
        raise UnreadableResults(f"{path} could not be read: it is not in the form of OSV-Scanner's JSON output")
    return output


def _annotation(message: str) -> str:
    """A GitHub Actions error annotation. The characters that the runner reads as line breaks are escaped."""
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=Known vulnerability::{escaped}"


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="OSV-Scanner's output, written with --format json")
    options = parser.parse_args(arguments)
    try:
        found = findings(read_results(options.results))
    except UnreadableResults as error:
        print(f"check_osv_results: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    if not found:
        print("No known vulnerabilities in the scanned lockfiles.")
        return 0
    failing = [finding for finding in found if finding.blocks_merge]
    other = [finding for finding in found if not finding.blocks_merge]
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if failing:
        print(f"Known vulnerabilities rated high or critical, with a fixed version ({len(failing)}). The job fails because of these:")
        for finding in failing:
            print(f"  {finding}")
            if in_actions:
                print(_annotation(str(finding)))
    if other:
        print(f"Other known vulnerabilities ({len(other)}). The job does not fail because of these:")
        for finding in other:
            print(f"  {finding}")
    if failing:
        print("\nUpdate the packages to a fixed version. The steps are in docs/package-updates.md.")
        return EXIT_FAILS
    return 0


if __name__ == "__main__":
    sys.exit(main())
