# Files for running Franca on the PC

| File | What it is |
|---|---|
| `compose.yaml` | The container bundle. It has the `app` and `caddy` containers so far |
| `images/app.Dockerfile` | The image for the application service |
| `images/caddy.Dockerfile` | The image for the web server, with the built client |
| `caddy/Caddyfile` | The web server's configuration: the client, the `/api` forwarding and the security headers |
| `tests/test-bundle.sh` | Starts the bundle and checks it. The pipeline runs it on every pull request |

The containers run as users other than root, with read-only file systems, no Linux capabilities and a health check each. Data is kept in named volumes.

To start the bundle from the repository root:

```sh
docker compose -f infra/compose.yaml up -d --build --wait
```

Franca is then at http://127.0.0.1:8080, on this computer only. It becomes reachable from other devices over Tailscale in story E01-009.

The other containers are added in their own stories:

| Container | Story |
|---|---|
| `worker` | The first story with a background job (pack import, WP3) |
| `speech` | E09-011 and the later speech stories |
| `languagetool` | The answer-checking stories (WP4) |
| `backup` | E01-008 |
| `status` | E01-010 |
| `tailscale` | E01-009 |

The installer for Windows (story E01-011) and the updater (story E01-007) are built on this bundle.
