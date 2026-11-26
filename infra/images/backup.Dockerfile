# The backup (container "backup"), story E01-008. Built from the repository root:
#   docker build -f infra/images/backup.Dockerfile .
# Base images are named by tag here; Renovate adds and updates their digests.

# restic is built from its 0.19.1 release with Go 1.27.4 and compress 1.20.2, because the published binary was built
# with versions that have known vulnerabilities. Remove this stage when a restic release has these versions or newer.
FROM golang:1.27.4-trixie AS restic
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
RUN git clone --quiet --depth 1 --branch v0.19.1 https://github.com/restic/restic /src/restic \
    && cd /src/restic \
    && go get github.com/klauspost/compress@v1.20.2 \
    && go build -ldflags "-s -w -X main.version=0.19.1" -o /out/restic ./cmd/restic

FROM python:3.14.10-slim-trixie
ARG FRANCA_VERSION=0.1.0-dev
# Security fixes from Debian that came out after the base image was built are installed here.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY --from=restic /out/restic /usr/local/bin/restic
# The backup runs as the app's user (10001), so it can read and, for a restore, write the app's database files.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin franca \
    && install -d -o franca -g franca /cache /status /backups
COPY infra/backup/franca_backup.py /app/franca_backup.py
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESTIC_REPOSITORY=/backups/restic \
    RESTIC_PASSWORD_FILE=/run/secrets/backup_password \
    RESTIC_CACHE_DIR=/cache/restic \
    FRANCA_VERSION=$FRANCA_VERSION
USER 10001:10001
HEALTHCHECK --interval=60s --timeout=5s --retries=3 CMD ["python", "-c", "import os; os.kill(1, 0)"]
CMD ["python", "/app/franca_backup.py", "serve"]
