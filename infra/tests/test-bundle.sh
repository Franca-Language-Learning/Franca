#!/usr/bin/env bash
# Starts the container bundle and checks it (story E01-005). Run from the repository root:
#   infra/tests/test-bundle.sh
# Needs Docker with Compose. The bundle is stopped and its volumes removed at the end.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export COMPOSE_PROJECT_NAME="franca-test-$$"
export FRANCA_PORT="${FRANCA_PORT:-18080}"
compose=(docker compose -f infra/compose.yaml)
failures=0

fail() { echo "FAIL: $*"; failures=$((failures + 1)); }
pass() { echo "ok:   $*"; }
cleanup() { "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${compose[@]}" up --detach --build --wait --wait-timeout 120

base="http://127.0.0.1:$FRANCA_PORT"
if curl -fsS "$base/api/v1/health" | grep -q '"status":"ok"'; then pass "the API answers through Caddy"; else fail "the API does not answer through Caddy"; fi
if curl -fsS "$base/" | grep -q '<div id="root">'; then pass "the client is served"; else fail "the client is not served"; fi
if curl -fsS "$base/some/client/route" | grep -q '<div id="root">'; then pass "client routes fall back to index.html"; else fail "client routes do not fall back to index.html"; fi
if curl -fsSI "$base/" | grep -qi '^x-content-type-options: nosniff'; then pass "the nosniff security header is sent"; else fail "the nosniff security header is missing"; fi

if "${compose[@]}" exec -T app python -c "import sqlite3; c = sqlite3.connect('/data/franca.db'); c.execute('SELECT count(*) FROM identity_learner')" ; then
    pass "the database in the app's volume has the schema"
else
    fail "the database in the app's volume has no schema"
fi

for service in app caddy; do
    id="$("${compose[@]}" ps --quiet "$service")"
    user="$(docker inspect --format '{{.Config.User}}' "$id")"
    readonly_fs="$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$id")"
    health="$(docker inspect --format '{{.State.Health.Status}}' "$id")"
    caps="$(docker inspect --format '{{.HostConfig.CapDrop}}' "$id")"
    if [[ -n "$user" && "$user" != "root" && "$user" != 0* ]]; then pass "$service runs as user $user"; else fail "$service runs as root"; fi
    if [[ "$readonly_fs" == "true" ]]; then pass "$service has a read-only file system"; else fail "$service has a writable file system"; fi
    if [[ "$health" == "healthy" ]]; then pass "$service is healthy"; else fail "$service health is $health"; fi
    if [[ "$caps" == *ALL* ]]; then pass "$service drops all capabilities"; else fail "$service keeps capabilities: $caps"; fi
done

if [[ "$failures" -ne 0 ]]; then
    "${compose[@]}" logs --no-color | tail -50
    echo "$failures check(s) failed."
    exit 1
fi
echo "All bundle checks passed."
