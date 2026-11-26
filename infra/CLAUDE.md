# Infrastructure

- `compose.yaml`, the image files and the Caddy configuration are in this folder (story E01-005). The updater and the backup settings will be added in stories E01-007 and E01-008.
- Containers run as non-root with read-only file systems and health checks. Base images are named by tag, and Renovate adds their digests.
- Secrets are files mounted under /run/secrets, never environment variables in Compose files and never committed.
