# Infrastructure

- Docker Compose, Caddy, the updater and backups, built from stories E01-005 to E01-012.
- Containers run as non-root with read-only file systems and health checks. Images are referenced by digest.
- Secrets are files mounted under /run/secrets, never environment variables in Compose files and never committed.
