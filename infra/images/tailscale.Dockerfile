# The private network (container "tailscale"), story E01-009. Built from the repository root:
#   docker build -f infra/images/tailscale.Dockerfile .
# The base image is named by tag here; Renovate adds and updates its digest.
#
# This is Tailscale's image with a non-root user added. The folders Tailscale writes to are made for that user, and
# port 443 is forwarded to Caddy (serve.json). Tailscale runs with userspace networking, which needs no capabilities
# and no /dev/net/tun.

# The published binaries of Tailscale 1.104.7 have compress 1.20.0, which has a known vulnerability (GO-2026-6865).
# They are built here from the same release with compress 1.20.2, with the build tags and version stamps of Tailscale's
# own image (build_docker.sh). Remove this stage and the COPY below when a Tailscale release has compress 1.20.2.
FROM golang:1.27.4-trixie AS tailscale
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
# The tag is checked against its commit, so a moved tag is noticed.
RUN git clone --quiet --depth 1 --branch v1.104.7 https://github.com/tailscale/tailscale /src/tailscale \
    && cd /src/tailscale \
    && test "$(git rev-parse HEAD)" = cbc74fe48ef1b1649f69a4d9a602319427e25102 \
    && go get github.com/klauspost/compress@v1.20.2 \
    && go build -tags ts_kube,ts_package_container -o /out/ \
        -ldflags "-s -w -X tailscale.com/version.shortStamp=1.104.7 \
            -X tailscale.com/version.longStamp=1.104.7-tcbc74fe48 \
            -X tailscale.com/version.gitCommitStamp=cbc74fe48ef1b1649f69a4d9a602319427e25102" \
        ./cmd/tailscale ./cmd/tailscaled ./cmd/containerboot

FROM tailscale/tailscale:v1.104.7
COPY --from=tailscale /out/tailscale /out/tailscaled /out/containerboot /usr/local/bin/
# Security fixes from Alpine that came out after the base image was built are installed here.
RUN apk upgrade --no-cache
RUN addgroup -g 10004 -S tailscale && adduser -u 10004 -S -G tailscale -H tailscale \
    && install -d -o tailscale -g tailscale /var/lib/tailscale /var/run/tailscale
COPY infra/tailscale/serve.json /etc/franca/serve.json
ENV TS_SERVE_CONFIG=/etc/franca/serve.json
USER 10004:10004
# The container counts as healthy once the node is signed in to the tailnet.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["sh", "-c", "tailscale status --peers=false --json | grep -q '\"BackendState\": \"Running\"'"]
