"""Checks the entries that ignore vulnerabilities in the osv-scanner.toml files of the repository (E01-013).

OSV-Scanner reads an osv-scanner.toml file next to a lockfile, and the findings that it ignores are left out of the
output, so they are not judged by the OSV scan in .github/workflows/osv-scanner.yml. The owner decided on these rules
for the entries:

  - A known malicious package cannot be ignored. An [[IgnoredVulns]] entry whose id starts with MAL- is refused,
    because a malicious package fails the OSV scan whatever its severity.
  - An entry that ignores something needs an end date in effectiveUntil, no more than 90 days after today. This
    applies to [[IgnoredVulns]] entries and to [[PackageOverrides]] entries with ignore = true or
    vulnerability.ignore = true. After the date, OSV-Scanner reports the findings again.

The older key ignoreUntil is refused too. OSV-Scanner v2.7.1 still reads it, but the warning about it is hidden by
--verbosity error, and the docs name effectiveUntil.

  uv run python -I tools/check_osv_ignores.py              the osv-scanner.toml files that git knows about
  uv run python -I tools/check_osv_ignores.py <file> ...   the files given

Exit codes: 0 when there are no problems, and 1 when there is at least one, or a file could not be read. The script
is run by scripts/check, with the project's Python, so tomllib (Python 3.11 and later) is available.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = "osv-scanner.toml"
MALICIOUS_PREFIX = "MAL-"
LONGEST_EXCEPTION = timedelta(days=90)


def _end_date_problems(entry: dict[str, Any], today: date) -> Iterator[str]:
    """The problems with the entry's end date: missing, not a date, or too far ahead."""
    if "ignoreUntil" in entry:
        yield "use effectiveUntil in place of ignoreUntil"
        return
    if "effectiveUntil" not in entry:
        yield "has no end date (effectiveUntil)"
        return
    until = entry["effectiveUntil"]
    if isinstance(until, datetime):
        until = until.date()
    if not isinstance(until, date):
        yield f"effectiveUntil = {until!r} is not a TOML date, such as 2027-01-31"
        return
    if until > today + LONGEST_EXCEPTION:
        yield f"effectiveUntil = {until.isoformat()} is more than 90 days after today ({today.isoformat()})"


def _entries(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """The entries under [[key]]. Raises ValueError when they are not a list of tables."""
    entries = config.get(key, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{key} is not a list of tables ([[{key}]])")
    return entries


def problems(text: str, path: str, today: date) -> Iterator[str]:
    """The problems with the ignore entries in one osv-scanner.toml file, one line each."""
    try:
        config = tomllib.loads(text)
        ignored_vulns = _entries(config, "IgnoredVulns")
        overrides = _entries(config, "PackageOverrides")
    except (tomllib.TOMLDecodeError, ValueError) as error:
        yield f"{path} could not be read: {error}"
        return
    for number, entry in enumerate(ignored_vulns, start=1):
        where = f"{path}: [[IgnoredVulns]] entry {number} ({entry.get('id', 'no id')})"
        if str(entry.get("id", "")).upper().startswith(MALICIOUS_PREFIX):
            yield f"{where}: a known malicious package cannot be ignored"
        for problem in _end_date_problems(entry, today):
            yield f"{where}: {problem}"
    for number, entry in enumerate(overrides, start=1):
        vulnerability = entry.get("vulnerability")
        ignores_vulnerabilities = isinstance(vulnerability, dict) and vulnerability.get("ignore") is True
        if entry.get("ignore") is True or ignores_vulnerabilities:
            where = f"{path}: [[PackageOverrides]] entry {number} ({entry.get('name', 'no name')})"
            for problem in _end_date_problems(entry, today):
                yield f"{where}: {problem}"


def config_files(root: Path) -> list[Path]:
    """The osv-scanner.toml files that git knows about, in the checkout at root."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [root / name for name in listed.split("\0") if name and Path(name).name == CONFIG_NAME]


def main(arguments: Sequence[str] | None = None, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="osv-scanner.toml files (default: the ones in git)")
    options = parser.parse_args(arguments)
    files: list[Path] = options.files or config_files(ROOT)
    today = today or date.today()
    found = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            found.append(f"{path} could not be read: {error}")
            continue
        found += problems(text, str(path), today)
    for problem in found:
        print(f"check_osv_ignores: {problem}", file=sys.stderr)
    if found:
        print("The rules for ignore entries are in docs/package-updates.md.", file=sys.stderr)
        return 1
    print(f"OSV-Scanner ignore entries: {len(files)} file(s) checked, no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
