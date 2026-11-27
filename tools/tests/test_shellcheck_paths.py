"""Test that scripts/check runs shellcheck on each shell script in the repository.

The shell scripts are named in the shellcheck line of scripts/check by folder patterns. A script in a folder that no
pattern names is not checked, in the pipeline or locally, so this test compares the patterns with the shell scripts
that are tracked by Git.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# A #! line for sh, bash or dash, directly or through env (with or without -S).
SHELL_LINE = rb"#!\s*\S*(?:/|env(?: -S)? )(?:ba|da)?sh\b"


def shellcheck_patterns() -> list[str]:
    """The paths on the shellcheck line of scripts/check. They are relative to server/, where the line is run."""
    text = (ROOT / "scripts" / "check").read_text(encoding="utf-8")
    (line,) = re.findall(r"^\s*uv run shellcheck (.+)$", text, flags=re.MULTILINE)
    return shlex.split(line)


def shell_scripts() -> set[str]:
    """Tracked files that end in .sh or start with a #! line for sh, bash or dash."""
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    found = set()
    for name in filter(None, tracked):
        path = ROOT / name
        if not path.is_file():
            continue
        with path.open("rb") as file:
            first_line = file.readline()
        if name.endswith(".sh") or re.match(SHELL_LINE, first_line):
            found.add(name)
    return found


def test_a_shell_script_is_found_by_its_first_line() -> None:
    for line in [b"#!/bin/sh", b"#!/usr/bin/env bash", b"#!/usr/bin/env -S bash -e", b"#!/bin/dash", b"#! /bin/bash"]:
        assert re.match(SHELL_LINE, line), line
    for line in [b"#!/usr/bin/env python3", b"#!/usr/bin/env zsh"]:
        assert not re.match(SHELL_LINE, line), line


def test_the_shellcheck_line_is_found() -> None:
    assert shellcheck_patterns()


def test_each_shell_script_is_shellchecked() -> None:
    server = ROOT / "server"
    checked = {
        path.resolve().relative_to(ROOT).as_posix()
        for pattern in shellcheck_patterns()
        for path in server.glob(pattern)
        if path.is_file() and not (path.name.startswith(".") and Path(pattern).name.startswith("*"))
    }
    assert shell_scripts() - checked == set()
