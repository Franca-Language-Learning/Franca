# The backup (container "backup"), story E01-008. Built from the repository root:
#   docker build -f infra/images/backup.Dockerfile .
# Base images are named by tag and digest, and Renovate updates both. A tag without a digest is reported by
# tools/check_pins.py, and the pipeline fails.

# restic is built from its 0.19.1 release with Go 1.27.4 and newer versions of five of its libraries (compress, x/net
# x/text, grpc and go-jose), because the published binary has versions with known vulnerabilities. Remove this stage
# when a restic release has these versions or newer.
FROM golang:1.27.4-trixie@sha256:430985542100b871e108ccc00e8dcc5eef08ca14ee5825e98ebf563d8ffec4ee AS restic
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
# The tag is checked against its commit, so a moved tag is noticed.
RUN git clone --quiet --depth 1 --branch v0.19.1 https://github.com/restic/restic /src/restic \
    && cd /src/restic \
    && test "$(git rev-parse HEAD)" = 6aa3a516ce654808a1f28f9fa21e9b7c8e6e90bf \
    && go get github.com/klauspost/compress@v1.20.2 golang.org/x/net@v0.62.0 \
        google.golang.org/grpc@v1.83.2 github.com/go-jose/go-jose/v4@v4.1.6 \
    && go build -ldflags "-s -w -X main.version=0.19.1" -o /out/restic ./cmd/restic

FROM python:3.14.10-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b
ARG FRANCA_VERSION=0.1.0-dev
# Security fixes from Debian that came out after the base image was built are installed here.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY --from=restic /out/restic /usr/local/bin/restic
# The backup runs as the app's user (10001), so it can read and, for a restore, write the app's database files.
# /restore-test is shared with the updater and the one-off app container of the monthly restore test. A new volume
# takes the owner of the folder in the image that mounts it first, so the folder belongs to 10001 in each image.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin franca \
    && install -d -o franca -g franca /cache /status /backups \
    && install -d -o 10001 -g 10001 /restore-test
COPY infra/backup/franca_backup.py /app/franca_backup.py
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESTIC_REPOSITORY=/backups/restic \
    RESTIC_PASSWORD_FILE=/run/secrets/backup_password \
    RESTIC_CACHE_DIR=/cache/restic \
    FRANCA_VERSION=$FRANCA_VERSION
USER 10001:10001
# Healthy until the first backup is tried, then while the last successful backup is less than two days old.
HEALTHCHECK --interval=5m --timeout=10s --retries=1 CMD ["python", "/app/franca_backup.py", "health"]
CMD ["python", "/app/franca_backup.py", "serve"]
