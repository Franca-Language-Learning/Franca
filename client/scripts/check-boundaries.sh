#!/usr/bin/env bash
# Checks the client's module boundaries with dependency-cruiser (story E01-003), then checks that the rules
# still find a known breach in architecture-fixtures/, so that a rule that stops working is noticed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
depcruise="$(pwd)/node_modules/.bin/depcruise"

"$depcruise" src --config .dependency-cruiser.cjs

set +e
output="$(cd architecture-fixtures && "$depcruise" src --config ../.dependency-cruiser.cjs 2>&1)"
status=$?
set -e
if [ "$status" -eq 0 ] || ! grep -q "feature-index-only: src/features/review/index.ts" <<<"$output"; then
    echo "The boundary rules did not find the breach in architecture-fixtures/:" >&2
    echo "$output" >&2
    exit 1
fi
echo "The boundary rules found the breach in architecture-fixtures/, as expected."
