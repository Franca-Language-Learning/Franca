# The application service (container "app"), story E01-005. Built from the repository root:
#   docker build -f infra/images/app.Dockerfile .
# Base images are named by tag here; Renovate adds and updates their digests.

FROM python:3.14.6-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY server/pyproject.toml server/
COPY tools/check-startup-files.sh tools/startup-files-allowed.txt tools/
RUN uv sync --locked --no-dev --package franca-server
# The build stops if a package installs a file that Python would run at start-up (stories E01-004 and E01-013).
RUN tools/check-startup-files.sh /app/.venv

FROM python:3.14.6-slim-trixie
ARG FRANCA_VERSION=0.1.0-dev
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin franca \
    && install -d -o franca -g franca /data
COPY --from=build /app/.venv /app/.venv
COPY server/src /app/src
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRANCA_VERSION=$FRANCA_VERSION \
    FRANCA_ENVIRONMENT=production \
    FRANCA_DATABASE_PATH=/data/franca.db
USER 10001:10001
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
# The database is brought up to date before the service starts. From story E01-007 the updater does this after
# taking a snapshot, and then there is nothing left to do in this step.
CMD ["sh", "-c", "python -m franca.platform.migrate && exec uvicorn franca.api:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
