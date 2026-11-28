"""Runs OSV-Scanner on the checkout and fails when OSV-Scanner stops with an error or logs one (E01-013).

OSV-Scanner v2.7.1 exits with 0 when it finds no known vulnerability and with 1 when it finds one. Exit code 1 is
returned even when an error was logged, for example "Error during extraction" for a lockfile that could not be read
or for a query to osv.dev that failed, so the results can be partial. The higher exit codes are errors, and the
results are not complete:

  - 127: an error was logged and no vulnerability was found;
  - 128: no lockfile was found;
  - 129: a query to the OSV API failed (declared in v2.7.1, not returned yet);
  - 130: an osv-scanner.toml file could not be read.

These are in cmd/osv-scanner/internal/cmd/run.go of OSV-Scanner. With --format json or sarif, OSV-Scanner writes
its log lines on stderr, and an error line looks the same as an information line. For this reason OSV-Scanner is run
with --verbosity error, and any text on stderr is an error. The scan fails when OSV-Scanner exits with a code above 1
or writes to stderr, and then the results are not judged. Whether a finding fails the job is decided afterwards by
tools/check_osv_results.py.

The JSON run lists the packages without findings too (--all-packages), so that a lockfile in which no packages were
found can be noticed by tools/check_osv_results.py --lockfile. In GitHub Actions (GITHUB_ACTIONS=true), OSV-Scanner's error
lines are written to the log between ::stop-commands:: lines, because they can quote file names and parser messages
from a pull request, and a line in them could otherwise start a workflow command.

  python3 -I tools/run_osv_scanner.py <osv-scanner program> <json|sarif> <output file>

Exit codes: 0 when the scan finished with no error, whether or not vulnerabilities were found, and 1 when it did not.
Only the Python standard library is needed, and the code is kept to syntax that Python 3.10 reads, because the script
is run with the runner's own Python.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from collections.abc import Sequence

EXIT_FAILED = 1
EXIT_MEANINGS = {
    127: "an error was logged",
    128: "no lockfile was found",
    129: "a query to the OSV API failed",
    130: "an osv-scanner.toml file could not be read",
}


def scan_command(program: str, output_format: str, output_file: str) -> list[str]:
    """The OSV-Scanner command for the checkout in the current folder, with its subfolders. The JSON output lists the
    packages without findings too, so that a lockfile in which no packages were found can be noticed."""
    listing = ["--all-packages"] if output_format == "json" else []
    return [
        program,
        "scan",
        "source",
        "--recursive",
        *listing,
        "--verbosity",
        "error",
        "--format",
        output_format,
        "--output-file",
        output_file,
        ".",
    ]


def _pass_on(errors: str) -> None:
    """Writes OSV-Scanner's error lines to the log. In GitHub Actions, they are written to stdout between
    ::stop-commands:: and the end token, so that the runner does not read workflow commands in them. The token is
    random, so the text cannot end the pause itself. stdout is also where the error annotation from _report is
    written, so the two stay in order."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        sys.stderr.write(errors)
        return
    token = secrets.token_hex(16)
    print(f"::stop-commands::{token}")
    print(errors.rstrip("\n"))
    print(f"::{token}::", flush=True)


def _report(message: str) -> int:
    print(f"run_osv_scanner: {message}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=OSV-Scanner::{message}")
    return EXIT_FAILED


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", help="the OSV-Scanner program, as installed by tools/install_program.py")
    parser.add_argument("format", choices=["json", "sarif"], help="the format of the output file")
    parser.add_argument("output_file", help="where the results are written")
    options = parser.parse_args(arguments)
    try:
        scan = subprocess.run(
            scan_command(options.program, options.format, options.output_file),
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError as error:
        return _report(f"OSV-Scanner could not be started: {error}")
    if scan.stderr:
        _pass_on(scan.stderr)
    if scan.returncode > 1 or scan.returncode < 0:
        meaning = EXIT_MEANINGS.get(scan.returncode, "an error")
        return _report(f"OSV-Scanner stopped with exit code {scan.returncode} ({meaning}). The error is above.")
    if scan.stderr.strip():
        return _report("OSV-Scanner logged an error, so the results may be partial and are not judged. The error is above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
