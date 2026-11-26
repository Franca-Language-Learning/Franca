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
| `images/backup.Dockerfile` | The image for the backup, with restic |
| `images/tailscale.Dockerfile` | The image for the private network: Tailscale's image with a user other than root and the forwarding to Caddy |
| `images/status.Dockerfile` | The image for the status container: Gatus on Alpine, with its start script |
| `status/gatus.yaml` | The checks, the reports from the nightly jobs and the alerts |
| `status/entrypoint.sh` | The start script, which passes the alert topic and the push token from the secret files to Gatus |
| `tailscale/entrypoint.sh` | The tailscale container's start script, which opens the health port on the bundle's network |
| `tailscale/serve.json` | The forwarding of port 443 on the tailnet to Caddy's HTTPS port |
| `backup/franca_backup.py` | The nightly backup and the monthly restore test (story E01-008) |
| `tests/rehearse_backup.py` | A rehearsal of a backup, a restore test and a restore with real containers. The pipeline runs it after the update rehearsal |
| `tests/rehearse_tailnet.py` | A rehearsal of the private network with real containers, with Headscale in place of Tailscale's control server. The pipeline runs it after the backup rehearsal |
| `tests/test_tailnet_config.py` | Checks of the private-network settings in these files. They run with the server's tests |
| `tests/rehearse_status.py` | A rehearsal of health monitoring with real containers, with a stand-in for ntfy. The pipeline runs it after the tailnet rehearsal |
| `tests/test_status_config.py` | Checks of the monitoring settings in these files. They run with the server's tests |
| `tests/rehearse_update.py` | A rehearsal of an update and a rollback with real containers. The pipeline runs it after the bundle check |

Secrets are files in a folder on the PC (`FRANCA_SECRETS_DIR`, by default `infra/secrets`): `google_client_secret` and `session_secret`. Docker passes them to the app container under `/run/secrets`, with the files' own permissions, so the app's user (number 10001) has to be able to read them. The installer writes them (story E01-011).

The containers run as users other than root, with read-only file systems, no Linux capabilities and a health check each. Data is kept in named volumes.

To start the bundle from the repository root:

```sh
docker compose -f infra/compose.yaml up -d --build --wait
```

Franca is then at http://127.0.0.1:8080, on this computer only. Other devices reach it over the tailnet, as described below.

## Updates

Each night at 02:30 UTC, the updater looks for a new release of Franca on GitHub and installs it. The time can be changed with `FRANCA_UPDATE_AT_UTC` in `.env`.

1. A release that is not newer than the installed version is not installed.
2. The signature of each image is checked with cosign. The signature has to come from the release workflow of Franca's repository, for that version's tag. If a check fails, the release is not installed and the running version is left as it is.
3. The images are downloaded and the app is stopped. A copy of the database is saved in the `snapshots` folder of the app's volume, and the last five copies are kept.
4. The references to the new images are written to `.env`, and the app and Caddy are started. The app brings the database up to date when it starts.
5. If the new version does not answer the health check within three minutes, the old version and the copy of the database are put back.

The result is in the `updater-status` volume, in `updater.json`. Health monitoring (story E01-010) sends an alert when an update fails or is rolled back.

The updater reaches Docker only through the socket proxy. Calls about containers, images, networks and volumes, and calls to start and stop containers, are let through the proxy. Exec, build, swarm, plugin, secret and system calls are blocked. There is no check on what a new container can reach, so someone who took control of the updater could still start a container with access to the PC. For that reason the updater's image is signed and checked in the same way as the app's images.

The installer switches the updater on with `COMPOSE_PROFILES=updates` in `.env`, and writes the path of the bundle folder to `FRANCA_BUNDLE_DIR`, so that the updater sees the bundle at the same path as Docker does. The updater runs as user 10003 and writes `.env`, so that user has to be able to write to the bundle folder. On the Windows PC, the folder has to be given as a path that Docker's Linux containers can use; the installer (story E01-011) chooses that path and is tested on the PC.

## Backups

At 03:30 UTC (an hour after the update check), a copy of the database is added to an encrypted restic repository in `FRANCA_BACKUP_DIR`. Until an off-site store is chosen, that folder is on a second disk in the PC (disk J:). The time can be changed with `FRANCA_BACKUP_AT_UTC`. Older backups are thinned out. These are kept:

- one a day for 14 days
- one a week for 8 weeks
- one a month for 12 months

Once a month the latest backup is restored into a scratch folder and checked, and all of the repository's data is read back.

The backup password is the `backup_password` secret. The installer writes it and shows it to the owner once, to keep in a password manager; without it the backups cannot be read. `docs/restoring-a-backup.md` has the steps for a restore. The backup and restore-test results are in the `backup-status` volume, in `backup.json` and `restore-test.json`.

The backup container runs as the app's user (10001), so the backup folder on disk J: has to be writable by that user. The installer puts a file called `.franca-backup-disk` in the backup folder. Without that file the disk counts as missing and no backup is made, so a backup never goes to an empty folder on another disk when disk J: is not connected. A night when the PC was off is made up when it is on again.

## Private network

Phones and laptops reach Franca over the owner's tailnet, the private network between the owner's devices in Tailscale. No port is opened on the PC or on the router, and Franca cannot be reached from the internet.

1. The `tailscale` container joins the tailnet as a device called `franca`, tagged `tag:franca`, with the auth key in the `tailscale_authkey` secret. The key file has to be readable by the container's user (10004). The key is needed once, and the installer can empty the file after the first start. The node's identity is kept in the `tailscale-state` volume, so a used or expired key is no problem at later starts.
2. Connections to port 443 on the PC's Tailscale name, such as `franca.tail1234.ts.net`, are passed to Caddy's port 8443 on the bundle's network. They stay encrypted on the way. A PROXY protocol header with the device's tailnet address is put in front of each connection. With that address, the limits on sign-in attempts can be kept per device.
3. Caddy serves HTTPS there with a certificate for the Tailscale name. tailscaled gets the certificate from Let's Encrypt and renews it, and Caddy asks tailscaled for it through the socket in the `tailscale-socket` volume. Through the socket, Caddy's user (10002) can fetch the certificate and read the status. Requests to change settings are refused. A user of the socket can also open connections to other devices in the tailnet as `franca`. The tailnet policy in `docs/private-network.md` has no rule for connections from `tag:franca`, so a compromised Caddy cannot reach the owner's devices.

The installer writes the Tailscale name to `FRANCA_TAILSCALE_NAME` in `.env`, writes `FRANCA_PUBLIC_URL` as `https://` followed by that name, and switches the private network on with the `tailnet` profile. The Google sign-in client and passkeys use the same name.

Tailscale runs with userspace networking, as user 10004, with a read-only file system and no capabilities. The socket is put in the shared volume itself (`TS_SOCKET`). Without that setting, containerboot puts it in `/tmp` and leaves only a symlink in the volume, which Caddy cannot follow. Nothing else on the PC or in the bundle can be reached over the tailnet, because no port other than 443 is open in the tailscale container.

The certificate's name is published in the public logs of issued certificates, as with all Let's Encrypt certificates. The name shows that a device called `franca` is in the tailnet. Knowing the name is not enough to get in.

When a release has a new tailscale image and the `tailnet` profile is on, the updater starts the new image after the app is healthy. If it does not start, the old image is put back and started again.

`docs/private-network.md` has the owner's steps in the Tailscale admin console.

## Health monitoring

The `status` container runs Gatus, an open-source health checker, in the `monitoring` profile. Alerts are sent to the owner's phone through ntfy, a free notification service, on a topic that only the owner knows.

| Check | How often | Alert |
|---|---|---|
| The app answers its health check | Every minute | After three failures in a row |
| The web server (Caddy) answers | Every minute | After three failures in a row |
| HTTPS on the Tailscale name works, and the certificate has more than 14 days left | Every minute, once the PC has a Tailscale name | After three failures in a row |
| The tailscale container is running and signed in to the tailnet | Every minute, once the PC has a Tailscale name | After three failures in a row |
| The last nightly update succeeded, less than 26 hours ago | Reported by the updater after each run and every hour | At once |
| The last nightly backup succeeded, less than 26 hours ago | Reported by the backup after each run and every hour | At once |
| The last restore test passed, less than 32 days ago | Reported by the backup after each run and every hour | At once |
| The updater and the backup are running | No report for two hours | At once |

A second message is sent when a problem is over. The age of the last success is worked out by the updater and the backup, because Gatus forgets the time of the last report when it restarts. Inside the bundle, the Tailscale name is an alias for Caddy, so the HTTPS check is made against Caddy's real certificate. The tailscale container's health port is opened on its address in the bundle's network. Connections from the tailnet arrive at the container's loopback address, where nothing listens on that port, so the port cannot be reached from the tailnet.

The updater and the backup report each run with the token in the `status_push_token` secret. While that file is empty, nothing is reported. The topic is in the `ntfy_topic` secret. Anyone who knows the topic can read the alerts, so the installer makes it long and random. The start script checks both values against a strict pattern before Gatus reads them, because Gatus inserts the values into its configuration before reading it, so an unexpected character could change the configuration.

The dashboard is at http://127.0.0.1:8081 on the PC (`FRANCA_STATUS_PORT`). The history of the checks is kept in the `status-data` volume. When a release has a new status image and the `monitoring` profile is on, the updater starts it after the app is healthy and waits for its health check, as for the tailscale image.

These are not watched yet. The socket proxy is used by the updater alone, so a fault there shows as a failed update. When the status container itself, Docker or the PC stops, no alert can be sent from the PC. An outside check for that is planned with story E01-012. The Tailscale check shows whether the container is running and signed in, and not whether the tailnet can reach it from outside.

`docs/health-alerts.md` has the owner's steps for the ntfy app.

## Containers in later stories

The other containers will be added in later stories:

| Container | Story |
|---|---|
| `worker` | The first story with a background job (pack import, WP3) |
| `speech` | E09-011 and the later speech stories |
| `languagetool` | The answer-checking stories (WP4) |

The installer for Windows (story E01-011) will use this bundle.
