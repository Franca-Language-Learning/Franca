#!/usr/bin/env bash
# Starts the container bundle and checks it (story E01-005). Run from the repository root:
#   infra/tests/test-bundle.sh
# Needs Docker with Compose. The bundle is stopped and its volumes removed at the end.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export COMPOSE_PROJECT_NAME="franca-test-$$"
export FRANCA_PORT="${FRANCA_PORT:-18080}"
# Secrets for the test: an empty Google client secret (sign-in is then not configured) and a random session secret.
FRANCA_SECRETS_DIR="$(mktemp -d)"
export FRANCA_SECRETS_DIR
: > "$FRANCA_SECRETS_DIR/google_client_secret"
head -c 32 /dev/urandom | base64 > "$FRANCA_SECRETS_DIR/session_secret"
head -c 32 /dev/urandom | base64 > "$FRANCA_SECRETS_DIR/backup_password"
: > "$FRANCA_SECRETS_DIR/tailscale_authkey"  # the tailnet is rehearsed separately, in rehearse_tailnet.py
: > "$FRANCA_SECRETS_DIR/ntfy_topic"  # the monitoring is rehearsed separately, in rehearse_status.py
: > "$FRANCA_SECRETS_DIR/status_push_token"
# Compose mounts secret files with their own permissions, so the app's user (10001) has to be able to read them.
chmod 0644 "$FRANCA_SECRETS_DIR"/*
compose=(docker compose -f infra/compose.yaml)
failures=0

fail() { echo "FAIL: $*"; failures=$((failures + 1)); }
pass() { echo "ok:   $*"; }
cleanup() {
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$FRANCA_SECRETS_DIR"
}
trap cleanup EXIT

if ! "${compose[@]}" up --detach --build --wait --wait-timeout 120; then
    "${compose[@]}" logs --no-color | tail -80
    echo "The bundle did not start."
    exit 1
fi

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

if [[ "$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/me")" == "401" ]]; then pass "the API refuses /me without a session"; else fail "the API does not refuse /me without a session"; fi
if [[ "$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/auth/google/start")" == "503" ]]; then pass "sign-in says it is not configured without a client secret"; else fail "sign-in without a client secret does not answer 503"; fi

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

# The updater image (story E01-007) is in the "updates" profile, so it is built and checked on its own here.
if build_log="$("${compose[@]}" --profile updates build updater 2>&1)"; then pass "the updater image builds"; else echo "$build_log" | tail -40; fail "the updater image does not build"; fi
updater_image="franca/updater:${FRANCA_VERSION:-0.1.0-dev}"
if docker run --rm --entrypoint sh "$updater_image" -c 'docker --version && docker compose version && cosign version' >/dev/null 2>&1; then
    pass "the updater image has docker, compose and cosign"
else
    fail "the updater image lacks docker, compose or cosign"
fi
if [[ "$(docker inspect --format '{{.Config.User}}' "$updater_image")" == "10003:10003" ]]; then pass "the updater runs as user 10003"; else fail "the updater does not run as user 10003"; fi

# The backup image (story E01-008) is in the "backups" profile, so it is built and checked on its own here.
if build_log="$("${compose[@]}" --profile backups build backup 2>&1)"; then pass "the backup image builds"; else echo "$build_log" | tail -40; fail "the backup image does not build"; fi
backup_image="franca/backup:${FRANCA_VERSION:-0.1.0-dev}"
if docker run --rm --entrypoint restic "$backup_image" version >/dev/null 2>&1; then pass "the backup image has restic"; else fail "the backup image lacks restic"; fi
if [[ "$(docker inspect --format '{{.Config.User}}' "$backup_image")" == "10001:10001" ]]; then pass "the backup runs as the app's user"; else fail "the backup does not run as user 10001"; fi

# The tailscale image (story E01-009) is in the "tailnet" profile, so it is built and checked on its own here. The
# tailnet itself is rehearsed in rehearse_tailnet.py.
if build_log="$("${compose[@]}" --profile tailnet build tailscale 2>&1)"; then pass "the tailscale image builds"; else echo "$build_log" | tail -40; fail "the tailscale image does not build"; fi
tailscale_image="franca/tailscale:${FRANCA_VERSION:-0.1.0-dev}"
if docker run --rm --entrypoint tailscale "$tailscale_image" version >/dev/null 2>&1; then pass "the tailscale image has tailscale"; else fail "the tailscale image lacks tailscale"; fi
if [[ "$(docker inspect --format '{{.Config.User}}' "$tailscale_image")" == "10004:10004" ]]; then pass "tailscale runs as user 10004"; else fail "tailscale does not run as user 10004"; fi

# The status image (story E01-010) is in the "monitoring" profile, so it is built and checked on its own here. The
# monitoring itself is rehearsed in rehearse_status.py.
if build_log="$("${compose[@]}" --profile monitoring build status 2>&1)"; then pass "the status image builds"; else echo "$build_log" | tail -40; fail "the status image does not build"; fi
status_image="franca/status:${FRANCA_VERSION:-0.1.0-dev}"
if docker run --rm --entrypoint test "$status_image" -x /usr/local/bin/gatus; then pass "the status image has Gatus"; else fail "the status image lacks Gatus"; fi
if [[ "$(docker inspect --format '{{.Config.User}}' "$status_image")" == "10005:10005" ]]; then pass "the status container runs as user 10005"; else fail "the status container does not run as user 10005"; fi

if [[ "$failures" -ne 0 ]]; then
    "${compose[@]}" logs --no-color | tail -50
    echo "$failures check(s) failed."
    exit 1
fi
echo "All bundle checks passed."
