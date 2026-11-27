#!/bin/sh
# Start script of the status container (stories E01-010 and E01-012).
#
# Gatus reads settings from environment variables only, and secrets are files here, so the alert topic and the push
# token are read from /run/secrets and passed to Gatus as variables. Gatus puts the variables into its configuration
# before it reads the YAML, so each value is checked against a strict pattern first; a value with other characters
# could change the configuration.
#
# When the healthchecks_ping_url secret has an address, a heartbeat is sent to it every few minutes while Gatus
# answers. healthchecks.io sends an alert when the heartbeats stop, for example when the PC is off. Anyone who has the
# address can send heartbeats for the owner's check, so it is a secret. It is not passed to Gatus, it is not written to
# the log, and it is given to curl on standard input, so it is in no process's command line. When a heartbeat setting
# is not valid, the heartbeat is switched off and a message is written to the log. Gatus and its alerts go on.
set -eu

fail() {
    echo "franca-status: $*" >&2
    exit 1
}

# Reads a secret file without its line ending. If the file is missing or empty, the container is stopped with a message.
read_secret() {
    [ -s "/run/secrets/$1" ] || fail "the secret $1 is missing or empty"
    tr -d '\r\n' < "/run/secrets/$1"
}

# Reads a secret file that may be missing or empty, without its line ending.
read_optional_secret() {
    if [ -s "/run/secrets/$1" ]; then
        tr -d '\r\n' < "/run/secrets/$1"
    fi
}

newline='
'

# A value matches when it is one line and the whole line fits the pattern. grep checks each line on its own, so a
# value with a line break in it is refused first.
matches() {
    case "$1" in
        *"$newline"*) return 1 ;;
    esac
    printf '%s' "$1" | grep -Eqx "$2"
}

NTFY_TOPIC="$(read_secret ntfy_topic)"
STATUS_PUSH_TOKEN="$(read_secret status_push_token)"
matches "$NTFY_TOPIC" '[A-Za-z0-9_-]{16,64}' || fail "the ntfy topic has to be 16 to 64 letters, digits, - or _"
matches "$STATUS_PUSH_TOKEN" '[A-Za-z0-9_-]{32,128}' || fail "the push token has to be 32 to 128 letters, digits, - or _"
matches "$FRANCA_NTFY_URL" 'https?://[A-Za-z0-9.:_/-]+' || fail "FRANCA_NTFY_URL is not a plain web address"

FRANCA_TAILSCALE_NAME="${FRANCA_TAILSCALE_NAME:-tailscale-name-not-set.ts.net}"
matches "$FRANCA_TAILSCALE_NAME" '[a-z0-9.-]+' || fail "FRANCA_TAILSCALE_NAME is not a plain host name"
# The checks of HTTPS and Tailscale are switched on when the tailnet profile is on and the installer has written the
# PC's Tailscale name.
FRANCA_TAILNET_CHECKS=false
case ",${FRANCA_PROFILES:-}," in
    *,tailnet,*)
        if [ "$FRANCA_TAILSCALE_NAME" != tailscale-name-not-set.ts.net ]; then
            FRANCA_TAILNET_CHECKS=true
        fi
        ;;
esac

# Sends a heartbeat to the address in $1 every FRANCA_HEARTBEAT_SECONDS, while Gatus answers its own health check.
# printf is built into the shell, so the address reaches curl's standard input (-K -) without a command line. With -q
# first, curl reads no .curlrc file. curl's messages could name the address, so they are thrown away and a message
# without it is written instead.
heartbeat() {
    while :; do
        sleep "$FRANCA_HEARTBEAT_SECONDS"
        if wget -q -T 10 -O /dev/null http://127.0.0.1:8080/health 2>/dev/null; then
            if ! printf 'url = "%s"\n' "$1" | curl -q -fsS -m 10 -o /dev/null -K - 2>/dev/null; then
                echo "franca-status: the heartbeat to healthchecks.io could not be sent" >&2
            fi
        fi
    done
}

HEARTBEAT_URL="$(read_optional_secret healthchecks_ping_url)"
FRANCA_HEARTBEAT_SECONDS="${FRANCA_HEARTBEAT_SECONDS:-300}"
if [ -n "$HEARTBEAT_URL" ]; then
    # The rehearsal uses a stand-in on plain http; the installer accepts https://hc-ping.com addresses only.
    if ! matches "$HEARTBEAT_URL" 'https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]+)+'; then
        echo "franca-status: the heartbeat is off: the healthchecks.io ping address is not a plain web address" >&2
    # The owner's check on healthchecks.io expects a heartbeat every 5 minutes, so 300 seconds is the most allowed.
    elif ! matches "$FRANCA_HEARTBEAT_SECONDS" '([5-9]|[1-9][0-9]|[12][0-9]{2}|300)'; then
        echo "franca-status: the heartbeat is off: FRANCA_HEARTBEAT_SECONDS has to be a number of seconds from 5 to 300" >&2
    else
        heartbeat "$HEARTBEAT_URL" &
        echo "franca-status: a heartbeat is sent to healthchecks.io every $FRANCA_HEARTBEAT_SECONDS seconds"
    fi
fi
unset HEARTBEAT_URL

export NTFY_TOPIC STATUS_PUSH_TOKEN FRANCA_NTFY_URL FRANCA_TAILSCALE_NAME FRANCA_TAILNET_CHECKS
exec /usr/local/bin/gatus
