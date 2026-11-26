# Files for running Franca on the PC

Franca runs as a set of containers, which are small separate programs that Docker starts together. In this folder the set is called the bundle.

| File | What it is |
|---|---|
| `compose.yaml` | The container bundle: the `app` and `caddy` containers, and the `updater` and `socket-proxy` containers in the `updates` profile |
| `images/app.Dockerfile` | The image for the application service |
| `images/caddy.Dockerfile` | The image for the web server, with the built client |
| `images/updater.Dockerfile` | The image for the updater, with the docker command, its compose plugin and cosign |
| `updater/franca_updater.py` | The updater (story E01-007) |
| `caddy/Caddyfile` | The web server's configuration: the client, the `/api` forwarding and the security headers |
| `tests/test-bundle.sh` | Starts the bundle and checks it. The pipeline runs it on every pull request |
| `tests/rehearse_update.py` | A rehearsal of an update and a rollback with real containers. The pipeline runs it after the bundle check |

Secrets are files in a folder on the PC (`FRANCA_SECRETS_DIR`, by default `infra/secrets`): `google_client_secret` and `session_secret`. Docker passes them to the app container under `/run/secrets`, with the files' own permissions, so the app's user (number 10001) has to be able to read them. The installer writes them (story E01-011).

The containers run as users other than root, with read-only file systems, no Linux capabilities and a health check each. Data is kept in named volumes.

To start the bundle from the repository root:

```sh
docker compose -f infra/compose.yaml up -d --build --wait
```

Franca is then at http://127.0.0.1:8080, on this computer only. It becomes reachable from other devices over Tailscale in story E01-009.

## Updates

Each night at 02:30 UTC, the updater looks for a new release of Franca on GitHub and installs it. The time can be changed with `FRANCA_UPDATE_AT_UTC` in `.env`.

1. A release that is not newer than the installed version is not installed.
2. The signature of each image is checked with cosign. The signature has to come from the release workflow of Franca's repository, for that version's tag. If a check fails, the release is not installed and the running version is left as it is.
3. The images are downloaded and the app is stopped. A copy of the database is saved in the `snapshots` folder of the app's volume, and the last five copies are kept.
4. The references to the new images are written to `.env`, and the app and Caddy are started. The app brings the database up to date when it starts.
5. If the new version does not answer the health check within three minutes, the old version and the copy of the database are put back.

The result is in the `updater-status` volume, in `updater.json`. The health monitoring (story E01-010) will send an alert when an update fails or is rolled back.

The updater reaches Docker only through the socket proxy. Calls about containers, images, networks and volumes, and calls to start and stop containers, are let through the proxy. Exec, build, swarm, plugin, secret and system calls are blocked. There is no check on what a new container can reach, so someone who took control of the updater could still start a container with access to the PC. For that reason the updater's image is signed and checked in the same way as the app's images.

The installer switches the updater on with `COMPOSE_PROFILES=updates` in `.env`, and writes the path of the bundle folder to `FRANCA_BUNDLE_DIR`, so that the updater sees the bundle at the same path as Docker does. The updater runs as user 10003 and writes `.env`, so that user has to be able to write to the bundle folder. On the Windows PC, the folder has to be given as a path that Docker's Linux containers can use; the installer (story E01-011) chooses that path and is tested on the PC.

## Containers in later stories

The other containers will be added in later stories:

| Container | Story |
|---|---|
| `worker` | The first story with a background job (pack import, WP3) |
| `speech` | E09-011 and the later speech stories |
| `languagetool` | The answer-checking stories (WP4) |
| `backup` | E01-008 |
| `status` | E01-010 |
| `tailscale` | E01-009 |

The installer for Windows (story E01-011) will use this bundle.
