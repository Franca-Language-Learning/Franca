#!/bin/sh
# Start script of the status container (story E01-010).
#
# Gatus reads settings from environment variables only, and secrets are files here, so the alert topic and the push
# token are read from /run/secrets and passed to Gatus as variables. Gatus puts the variables into its configuration
# before it reads the YAML, so each value is checked against a strict pattern first; a value with other characters
# could change the configuration.
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

export NTFY_TOPIC STATUS_PUSH_TOKEN FRANCA_NTFY_URL FRANCA_TAILSCALE_NAME FRANCA_TAILNET_CHECKS
exec /usr/local/bin/gatus
