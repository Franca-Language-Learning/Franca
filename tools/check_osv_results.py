"""Reads OSV-Scanner's JSON output and fails for a known vulnerability that has to be fixed before a merge (E01-013).

OSV-Scanner exits with 1 for any known vulnerability in the locked packages, whatever its severity and whether a fix
exists. In the OSV-Scanner jobs in .github/workflows/osv-scanner.yml, this script is run on the scanner's JSON output,
and the job fails when the script exits with 1.

A finding is one vulnerability in one package of one lockfile. OSV-Scanner puts the records that describe the same
vulnerability under different IDs (for example a GitHub advisory and a PyPI advisory) in one group, and a group is
one finding. A finding fails the job when it is rated high or critical and has a fixed version:

  - High or critical: the group's max_severity is 7.0 or more, or at least one record of the group has the severity
    label HIGH or CRITICAL. max_severity is the highest CVSS base score of the group's records, worked out by
    OSV-Scanner from their CVSS vectors (CVSS 2, 3 or 4). The label is the one that the database gives
    (database_specific.severity, as in the GitHub advisories). The label is read when there is a lower score too,
    because OSV-Scanner gives no score for a record with a CVSS vector that it cannot parse, and the score of another
    record in the group can then be lower than the record's own rating.
  - A fixed version: at least one record of the group names a "fixed" version in a range for the same package (same
    ecosystem and name; Python names are compared in their normal form, as in PEP 503). Whether that fixed version is
    in the same range as the installed version is not checked, so a fix for an older release line counts too.

A known malicious package fails the job whatever its severity, and whether or not there is a fixed version. A finding
is a known malicious package when one of the group's IDs or aliases starts with MAL- (the OpenSSF malicious packages
data, which osv.dev serves), or when one of its records has database_specific.malicious-packages-origins.

The other findings are listed and do not fail the job. A vulnerability that is ignored in osv-scanner.toml is left
out of the scanner's output, so it is not listed here either. The rules for those entries are checked by
tools/check_osv_ignores.py. In GitHub Actions (GITHUB_ACTIONS=true), a finding that fails the job is also printed as
an error annotation.

  python3 -I tools/check_osv_results.py --lockfile uv.lock --lockfile pnpm-lock.yaml osv-results.json

Exit codes: 0 when no finding fails the job, 1 when at least one does, and 2 when the file could not be read. A file
that is not in the form of OSV-Scanner's JSON output, for example one with no "results" list or with a record that is
in no group, counts as a file that could not be read, so that it is not taken for a scan with no findings.

A lockfile given with --lockfile in which OSV-Scanner found no packages also counts as a file that could not be read,
because OSV-Scanner reads a lockfile in a format that it does not know as empty, with no error. For this check, the
output has to be written with --all-packages, so that a lockfile with packages and no findings is listed too.

Only the Python standard library is needed, so the job needs no project environment. The script is run with the
runner's own Python, which can be older than the project's, so the code is kept to syntax that Python 3.10 reads.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HIGH_SCORE = 7.0
HIGH_LABELS = frozenset({"HIGH", "CRITICAL"})
MALICIOUS_PREFIX = "MAL-"
MALICIOUS_ORIGINS = "malicious-packages-origins"
EXIT_FAILS = 1
EXIT_UNREADABLE = 2
PYTHON_NAME_SEPARATORS = re.compile(r"[-_.]+")
NOT_PRINTABLE = re.compile(r"[^\x20-\x7e]+")
NOT_OSV_OUTPUT = "it is not in the form of OSV-Scanner's JSON output"


class UnreadableResults(Exception):
    """The file is missing, is not JSON, or is not in the form of OSV-Scanner's JSON output."""


class LockfileNotRead(UnreadableResults):
    """A lockfile given with --lockfile is missing from the output, or has no packages in it."""


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
    is_malicious: bool = False

    @property
    def is_high(self) -> bool:
        return (self.score is not None and self.score >= HIGH_SCORE) or self.label in HIGH_LABELS

    @property
    def blocks_merge(self) -> bool:
        return self.is_malicious or (self.is_high and bool(self.fixed_versions))

    def __str__(self) -> str:
        details = ["known malicious package"] if self.is_malicious else []
        if self.score is not None:
            details.append(f"CVSS {self.score:.1f}")
        if self.label:
            details.append(f"label {self.label}")
        if self.score is None and not self.label:
            details.append("no severity given")
        details.append(f"fixed in {', '.join(self.fixed_versions)}" if self.fixed_versions else "no fixed version")
        aliases = f" ({', '.join(self.ids[1:])})" if len(self.ids) > 1 else ""
        where = f"{self.package} {self.version} ({self.ecosystem}, {self.source})"
        return _printable(f"{self.ids[0]}{aliases} in {where}: {', '.join(details)}")


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
    """The score as a number, or None when it is missing, empty, true or false, or not a finite number."""
    if isinstance(max_severity, bool) or not isinstance(max_severity, (str, int, float)):
        return None
    try:
        score = float(max_severity)
    except ValueError:
        return None
    return score if math.isfinite(score) else None


def _label(records: Sequence[dict[str, Any]]) -> str | None:
    """The highest severity label of the records, as written by the database, in capitals and without the spaces
    around it."""
    order = ["LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"]
    labels = []
    for record in records:
        severity = (record.get("database_specific") or {}).get("severity")
        if isinstance(severity, str) and severity.strip():
            labels.append(severity.strip().upper())
    known = [label for label in labels if label in order]
    if known:
        return max(known, key=order.index)
    return next((label for label in labels if label), None)


def _is_malicious(group: dict[str, Any], records: Sequence[dict[str, Any]]) -> bool:
    """Whether the group is a known malicious package: an ID or alias that starts with MAL-, or a record from the
    OpenSSF malicious packages data."""
    names = [str(name) for name in [*(group.get("ids") or []), *(group.get("aliases") or [])]]
    for record in records:
        names += [str(record.get("id", "")), *(str(alias) for alias in record.get("aliases") or [])]
    from_malicious_data = any(MALICIOUS_ORIGINS in (record.get("database_specific") or {}) for record in records)
    return from_malicious_data or any(name.startswith(MALICIOUS_PREFIX) for name in names)


def findings(output: dict[str, Any]) -> list[Finding]:
    """The findings in OSV-Scanner's JSON output, in the order they are written.

    Raises UnreadableResults for a package that has vulnerabilities and no groups, for a record that is in no group,
    for a group with no IDs and for a group ID that has no record. OSV-Scanner v2 builds the groups from the records,
    so any of these means that the format has changed, and the records would otherwise not be judged. Records with the
    same ID are all read."""
    found = []
    for result in output["results"]:
        source = str((result.get("source") or {}).get("path", ""))
        for entry in result.get("packages") or []:
            package = entry.get("package") or {}
            name, version, ecosystem = str(package.get("name", "")), str(package.get("version", "")), str(package.get("ecosystem", ""))
            records: dict[str, list[dict[str, Any]]] = {}
            for record in entry.get("vulnerabilities") or []:
                records.setdefault(str(record.get("id", "")), []).append(record)
            groups = entry.get("groups") or []
            if records and not groups:
                raise UnreadableResults(f"{name} in {source} has vulnerabilities and no groups")
            grouped = {str(vuln_id) for group in groups for vuln_id in group.get("ids") or []}
            for vuln_id in records:
                if vuln_id not in grouped:
                    raise UnreadableResults(f"{vuln_id} is in no group")
            for group in groups:
                ids = tuple(dict.fromkeys(str(vuln_id) for vuln_id in group.get("ids") or []))
                if not ids:
                    raise UnreadableResults(f"{name} in {source} has a group with no IDs")
                missing = [vuln_id for vuln_id in ids if vuln_id not in records]
                if missing:
                    raise UnreadableResults(f"{', '.join(missing)} is in a group and has no record")
                in_group = [record for vuln_id in ids for record in records[vuln_id]]
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
                        is_malicious=_is_malicious(group, in_group),
                    )
                )
    return found


def read_results(path: Path) -> dict[str, Any]:
    """The JSON output, with a "results" list. OSV-Scanner v2 writes "results": [] when there are no findings, so a
    file without the list is not read as a scan with no findings."""
    try:
        output = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as error:
        # json raises RecursionError for lists or objects nested too deep.
        raise UnreadableResults(str(error) or type(error).__name__) from error
    if not isinstance(output, dict) or not isinstance(output.get("results"), list):
        raise UnreadableResults(NOT_OSV_OUTPUT)
    return output


def check_lockfiles(output: dict[str, Any], lockfiles: Sequence[str]) -> None:
    """Raises LockfileNotRead for a lockfile that is not the source of a result with at least one package. A lockfile
    is matched by the end of the source path, so that uv.lock matches /work/uv.lock and not /work/old-uv.lock."""
    with_packages = [str((result.get("source") or {}).get("path", "")) for result in output["results"] if result.get("packages")]
    for lockfile in lockfiles:
        if not any(path == lockfile or path.endswith("/" + lockfile) for path in with_packages):
            raise LockfileNotRead(
                f"no packages were found in {lockfile}. OSV-Scanner reads a lockfile in a format that it does not know"
                " as empty, so the lockfile was probably not read. The results are not judged."
            )


def _annotation(message: str) -> str:
    """A GitHub Actions error annotation. The characters that the runner reads as line breaks are escaped."""
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=Known vulnerability::{escaped}"


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="OSV-Scanner's output, written with --format json and --all-packages")
    parser.add_argument(
        "--lockfile",
        action="append",
        default=[],
        help="a lockfile that has to have packages in the output, for example uv.lock (can be given more than once)",
    )
    options = parser.parse_args(arguments)
    try:
        output = read_results(options.results)
        check_lockfiles(output, options.lockfile)
        found = findings(output)
    except LockfileNotRead as error:
        print(f"check_osv_results: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except UnreadableResults as error:
        print(f"check_osv_results: {options.results} could not be read: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except (AttributeError, TypeError, RecursionError) as error:
        # A value of another type than OSV-Scanner writes, for example a string where a list of records belongs, or
        # a value nested so deep that it cannot be turned into text.
        print(f"check_osv_results: {options.results} could not be read: {NOT_OSV_OUTPUT} ({error})", file=sys.stderr)
        return EXIT_UNREADABLE
    if not found:
        print("No known vulnerabilities in the scanned lockfiles.")
        return 0
    failing = [finding for finding in found if finding.blocks_merge]
    other = [finding for finding in found if not finding.blocks_merge]
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if failing:
        print(
            f"Known vulnerabilities that fail the job ({len(failing)}). They are rated high or critical and have a fixed"
            " version, or they are known malicious packages:"
        )
        for finding in failing:
            print(f"  {finding}")
            if in_actions:
                print(_annotation(str(finding)))
    if other:
        print(f"Other known vulnerabilities ({len(other)}). The job does not fail because of these:")
        for finding in other:
            print(f"  {finding}")
    if failing:
        if any(not finding.is_malicious for finding in failing):
            print("\nUpdate the packages to a fixed version. The steps are in docs/package-updates.md.")
        if any(finding.is_malicious for finding in failing):
            print("\nA known malicious package has to be removed, or replaced with a version that is not affected.")
        return EXIT_FAILS
    return 0


if __name__ == "__main__":
    sys.exit(main())
