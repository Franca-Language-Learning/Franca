#!/bin/sh
# Start script of the tailscale container (story E01-010).
#
# The health check port is opened on the container's address in the bundle's network, where the status container can
# reach it. Connections from the tailnet are passed to the container's loopback address, where nothing listens on
# that port, so the tailnet cannot reach it.
set -eu

address="$(hostname -i | awk '{print $1}')"
case "$address" in
    *:*) address="[$address]" ;;
esac
export TS_ENABLE_HEALTH_CHECK=true TS_LOCAL_ADDR_PORT="${address}:9002"
exec /usr/local/bin/containerboot
