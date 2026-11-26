# The updater (container "updater"), story E01-007. Built from the repository root:
#   docker build -f infra/images/updater.Dockerfile .
# Base images are named by tag here; Renovate adds and updates their digests.

FROM docker:29.10.0-cli AS docker-cli
FROM docker/compose-bin:v5.8.0 AS compose
FROM ghcr.io/sigstore/cosign/cosign:v3.1.4 AS cosign

FROM python:3.14.10-slim-trixie
ARG FRANCA_VERSION=0.1.0-dev
# Security fixes from Debian that came out after the base image was built are installed here.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=compose /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=cosign /ko-app/cosign /usr/local/bin/cosign
RUN useradd --uid 10003 --user-group --no-create-home --shell /usr/sbin/nologin updater \
    && install -d -o updater -g updater /status
COPY infra/updater/franca_updater.py /app/franca_updater.py
# The file system is read-only; cosign and docker keep their caches under HOME, which is a temporary folder.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRANCA_VERSION=$FRANCA_VERSION
USER 10003:10003
HEALTHCHECK --interval=60s --timeout=5s --retries=3 CMD ["python", "-c", "import os; os.kill(1, 0)"]
CMD ["python", "/app/franca_updater.py"]
