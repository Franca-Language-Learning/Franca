# Health monitoring (container "status"), story E01-010. Built from the repository root:
#   docker build -f infra/images/status.Dockerfile .
# Base images are named by tag and digest, and Renovate updates both. A tag without a digest is reported by
# tools/check_pins.py, and the pipeline fails.
#
# Gatus 5.38.0 is built from its source here, with newer versions of four of its libraries, in which known
# vulnerabilities are fixed: compress (GO-2026-6865), x/net (GO-2026-6860), brotli (GO-2026-6888) and go-jose
# (GHSA-mgcc-cww5-fp2q). Remove these when a Gatus release has these versions or newer.
# Gatus's own image has no shell, and the start script needs one, so the program is put on Alpine.
FROM golang:1.27.4-trixie@sha256:430985542100b871e108ccc00e8dcc5eef08ca14ee5825e98ebf563d8ffec4ee AS gatus
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
# The tag is checked against its commit, so a moved tag is noticed.
RUN git clone --quiet --depth 1 --branch v5.38.0 https://github.com/TwiN/gatus /src/gatus \
    && cd /src/gatus \
    && test "$(git rev-parse HEAD)" = d255d0cd4d69ce818574cfdb3a7e82407e6559d7 \
    && go get github.com/klauspost/compress@v1.20.2 golang.org/x/net@v0.62.0 \
        github.com/andybalholm/brotli@v1.2.7 github.com/go-jose/go-jose/v4@v4.1.6 \
    && go build -ldflags "-s -w" -o /out/gatus .

FROM alpine:3.23@sha256:469c9ea410b9215eaee7976ba6c0639039b444be8e5d638f7abbada189971eb2
# Security fixes from Alpine that came out after the base image was built are installed here.
RUN apk upgrade --no-cache && apk add --no-cache ca-certificates
RUN addgroup -g 10005 -S status && adduser -u 10005 -S -G status -H status \
    && install -d -o status -g status /data
COPY --from=gatus /out/gatus /usr/local/bin/gatus
COPY infra/status/gatus.yaml /etc/franca/gatus.yaml
COPY infra/status/entrypoint.sh /usr/local/bin/franca-status
ENV GATUS_CONFIG_PATH=/etc/franca/gatus.yaml FRANCA_NTFY_URL=https://ntfy.sh
USER 10005:10005
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]
ENTRYPOINT ["/usr/local/bin/franca-status"]
