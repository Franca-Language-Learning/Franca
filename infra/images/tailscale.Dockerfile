# The private network (container "tailscale"), story E01-009. Built from the repository root:
#   docker build -f infra/images/tailscale.Dockerfile .
# The base image is named by tag here; Renovate adds and updates its digest.
#
# Tailscale's own image, with a user other than root, the folders it writes to, and the forwarding of port 443 to
# Caddy. Tailscale runs with userspace networking, which needs no capabilities and no /dev/net/tun.

FROM tailscale/tailscale:v1.104.7
# Security fixes from Alpine that came out after the base image was built are installed here.
RUN apk upgrade --no-cache
RUN addgroup -g 10004 -S tailscale && adduser -u 10004 -S -G tailscale -H tailscale \
    && install -d -o tailscale -g tailscale /var/lib/tailscale /var/run/tailscale
COPY infra/tailscale/serve.json /etc/franca/serve.json
ENV TS_SERVE_CONFIG=/etc/franca/serve.json
USER 10004:10004
# Healthy once the node is signed in to the tailnet.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["sh", "-c", "tailscale status --peers=false --json | grep -q '\"BackendState\": \"Running\"'"]
