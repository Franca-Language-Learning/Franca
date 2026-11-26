# The web server (container "caddy"), story E01-005: serves the client and forwards /api to the app.
# Built from the repository root:  docker build -f infra/images/caddy.Dockerfile .
# Base images are named by tag here; Renovate adds and updates their digests.

FROM node:22.23.4-alpine AS client
RUN npm install --global pnpm@12.22.0
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY client/package.json client/
RUN pnpm install --frozen-lockfile --filter @franca/client
COPY contracts/ui contracts/ui
COPY client client
RUN pnpm --filter @franca/client build

# Caddy 2.11.9 is built here with newer versions of two of its libraries, which fix GO-2026-6865 (compress)
# and GO-2026-6860 (x/net). Remove this stage and the COPY of /usr/bin/caddy below when a Caddy release
# has these versions or newer.
FROM caddy:2.11.9-builder-alpine AS caddy
# No file capabilities on the binary: Caddy listens on port 8080 and the container runs with no capabilities, so a
# binary that asks for one cannot start.
ENV XCADDY_SETCAPS=0
RUN xcaddy build v2.11.9 \
        --output /usr/bin/caddy \
        --replace github.com/klauspost/compress=github.com/klauspost/compress@v1.20.2 \
        --replace golang.org/x/net=golang.org/x/net@v0.62.0

FROM caddy:2.11.9-alpine
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
# Security fixes from Alpine that came out after the base image was built are installed here.
RUN apk upgrade --no-cache
RUN addgroup -g 10002 -S caddyuser && adduser -u 10002 -S -G caddyuser -H caddyuser \
    && install -d -o caddyuser -g caddyuser /data /config
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=client /src/client/dist /srv/client
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10002:10002
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
