# The web server (container "caddy"), story E01-005: serves the client and forwards /api to the app.
# Built from the repository root:  docker build -f infra/images/caddy.Dockerfile .
# Base images are named by tag and digest, and Renovate updates both (a tag without a digest is reported by tools/check_pins.py, and the pipeline fails).

FROM node:22.23.4-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 AS client
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# pnpm is installed by Corepack from the version and hash in package.json (packageManager).
RUN corepack enable pnpm && corepack install
COPY client/package.json client/
RUN pnpm install --frozen-lockfile --filter @franca/client
COPY contracts/ui contracts/ui
COPY client client
RUN pnpm --filter @franca/client build

# Caddy 2.11.9 is built here with newer versions of two of its libraries, which fix GO-2026-6865 (compress)
# and GO-2026-6860 (x/net). Remove this stage and the COPY of /usr/bin/caddy below when a Caddy release
# has these versions or newer.
FROM caddy:2.11.9-builder-alpine@sha256:86e132d1d6db8850352b2dbc15f82a4cb25363ac305ee41e11405873e5931f37 AS caddy
RUN xcaddy build v2.11.9 \
        --output /usr/bin/caddy \
        --replace github.com/klauspost/compress=github.com/klauspost/compress@v1.20.2 \
        --replace golang.org/x/net=golang.org/x/net@v0.62.0 \
    # The builder gives the binary the capability to listen on low ports. Caddy listens on port 8080 and the
    # container runs with no capabilities, and a binary that asks for one cannot start there, so it is removed.
    && setcap -r /usr/bin/caddy \
    && test -z "$(getcap /usr/bin/caddy)"

FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
# Security fixes from Alpine that came out after the base image was built are installed here.
RUN apk upgrade --no-cache
RUN addgroup -g 10002 -S caddyuser && adduser -u 10002 -S -G caddyuser -H caddyuser \
    && install -d -o caddyuser -g caddyuser /data /config \
    # The tailscale container's socket folder is shared with Caddy (story E01-009). Whichever container starts first
    # makes the volume from its own folder, so the folder here belongs to the tailscale container's user too.
    && install -d -o 10004 -g 10004 /var/run/tailscale
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=client /src/client/dist /srv/client
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10002:10002
EXPOSE 8080 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
