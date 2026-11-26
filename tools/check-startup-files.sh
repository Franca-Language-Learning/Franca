#!/usr/bin/env bash
# Checks a Python environment for files that Python runs at start-up (story E01-004).
#
# Python runs every .pth file in site-packages, and sitecustomize.py and usercustomize.py, each time it starts.
# A package that installs one can run code without being imported.
# This check is a shell script so that running it does not start Python.
#
# Usage:  tools/check-startup-files.sh <environment folder>      (for example .venv)
# Exit codes: 0 nothing unexpected, 1 unexpected start-up files found, 2 the folder is not an environment.
#
# Allowed .pth files, and the _virtualenv.py module, are listed by name and SHA-256 in tools/startup-files-allowed.txt. To allow a new one,
# read it first, then add its name and hash there in a reviewed change.

set -euo pipefail

env_dir="${1:?usage: check-startup-files.sh <environment folder>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
allowed_file="${STARTUP_FILES_ALLOWED:-$here/startup-files-allowed.txt}"

shopt -s nullglob
sites=()
for candidate in "$env_dir"/lib/python3*/site-packages "$env_dir"/Lib/site-packages; do
    [ -d "$candidate" ] && sites+=("$candidate")
done
if [ ${#sites[@]} -eq 0 ]; then
    echo "No site-packages folder under $env_dir" >&2
    exit 2
fi

declare -A allowed=()
if [ -f "$allowed_file" ]; then
    while read -r name hash _; do
        case "$name" in ''|'#'*) continue ;; esac
        allowed["$name"]="$hash"
    done < "$allowed_file"
fi

found=0
for site in "${sites[@]}"; do
    for file in "$site"/*.pth; do
        name="$(basename "$file")"
        hash="$(sha256sum "$file" | cut -d' ' -f1)"
        if [ "${allowed[$name]:-}" != "$hash" ]; then
            echo "Unexpected start-up file: $file"
            found=1
        fi
    done
    # sitecustomize.py and usercustomize.py are never allowed. _virtualenv.py is the module that uv's
    # _virtualenv.pth imports, so it is checked against its hash too.
    for name in sitecustomize.py usercustomize.py _virtualenv.py; do
        file="$site/$name"
        [ -e "$file" ] || continue
        hash="$(sha256sum "$file" | cut -d' ' -f1)"
        if [ "${allowed[$name]:-}" != "$hash" ]; then
            echo "Unexpected start-up file: $file"
            found=1
        fi
    done
done

if [ "$found" -ne 0 ]; then
    echo "Python would run these files each time it starts. Find which package installed them before going on."
    exit 1
fi
echo "No unexpected start-up files in $env_dir"
