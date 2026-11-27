# The updater (container "updater"), story E01-007. Built from the repository root:
#   docker build -f infra/images/updater.Dockerfile .
# Base images are named by tag and digest, and Renovate updates both. A tag without a digest is reported by
# tools/check_pins.py, and the pipeline fails.

FROM docker:29.10.0-cli@sha256:34507eb5069d8be82c95dd3b6987d4250fd5fee49b82e2509b7d7a7030740d6d AS docker-cli

# The published compose and cosign binaries were built with Go 1.27.1 and older versions of the compress library,
# which have known vulnerabilities (GO-2026-6603 and others; GO-2026-6865). They are built here from the same
# releases with Go 1.27.4 and compress 1.20.2. Remove this stage when the published binaries have these versions.
FROM golang:1.27.4-trixie@sha256:430985542100b871e108ccc00e8dcc5eef08ca14ee5825e98ebf563d8ffec4ee AS tools
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
# Each tag is checked against its commit, so a moved tag is noticed.
RUN git clone --quiet --depth 1 --branch v5.8.0 https://github.com/docker/compose /src/compose \
    && cd /src/compose \
    && test "$(git rev-parse HEAD)" = aee88dcde588d9dc7d8d2902f97b6b5502fdb771 \
    && go get github.com/klauspost/compress@v1.20.2 \
    && go build -ldflags "-s -w -X github.com/docker/compose/v5/internal.Version=v5.8.0" -o /out/docker-compose ./cmd
RUN git clone --quiet --depth 1 --branch v3.1.4 https://github.com/sigstore/cosign /src/cosign \
    && cd /src/cosign \
    && test "$(git rev-parse HEAD)" = 0e48502cf5ef34e2e60bbd3617aa19945712f705 \
    && go get github.com/klauspost/compress@v1.20.2 \
    && go build -ldflags "-s -w" -o /out/cosign ./cmd/cosign

FROM python:3.14.10-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b
ARG FRANCA_VERSION=0.1.0-dev
# Security fixes from Debian that came out after the base image was built are installed here.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=tools /out/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=tools /out/cosign /usr/local/bin/cosign
# /restore-test is shared with the backup and the one-off app container of the monthly restore test, which write
# there as user 10001. A new volume takes the owner of the folder in the image that mounts it first.
RUN useradd --uid 10003 --user-group --no-create-home --shell /usr/sbin/nologin updater \
    && install -d -o updater -g updater /status \
    && install -d -o 10001 -g 10001 /restore-test
COPY infra/updater/franca_updater.py /app/franca_updater.py
# The file system is read-only; cosign and docker keep their caches under HOME, which is a temporary folder.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRANCA_VERSION=$FRANCA_VERSION
USER 10003:10003
HEALTHCHECK --interval=60s --timeout=5s --retries=3 CMD ["python", "-c", "import os; os.kill(1, 0)"]
CMD ["python", "/app/franca_updater.py"]
