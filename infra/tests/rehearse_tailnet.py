"""A rehearsal of the private network with real containers (story E01-009). Run from the repository root:
    python3 infra/tests/rehearse_tailnet.py

It needs Docker with Compose and builds the images itself. Headscale, an open-source Tailscale control server, is used
in place of Tailscale's own, so no account is needed. A second Tailscale container is used in place of a phone.

The rehearsal:
1. starts Headscale and makes a sign-up key;
2. starts the bundle with the tailnet profile; the tailscale container joins with the key and becomes healthy;
3. from the phone, connects to port 443 on the PC's tailnet address and checks that the connection reaches Caddy's
   HTTPS port, still encrypted;
4. checks that Caddy's plain HTTP port and the other ports cannot be reached over the tailnet;
5. checks that no container publishes a port beyond the PC's loopback;
6. checks that the tailscale container runs as a user, with a read-only file system and no capabilities.

Headscale cannot issue certificates, so the certificate itself is tried at the installer rehearsal on the PC.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = f"franca-tailnet-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-tailnet"
CADDY = "franca/caddy:rehearsal-tailnet"
TAILSCALE = "franca/tailscale:rehearsal"
HEADSCALE = "headscale/headscale:0.29.7"
PHONE = "tailscale/tailscale:v1.104.7"
LOGIN_SERVER = "http://headscale:8080"

HEADSCALE_CONFIG = """\
server_url: http://headscale:8080
listen_addr: 0.0.0.0:8080
metrics_listen_addr: 127.0.0.1:9090
grpc_listen_addr: 127.0.0.1:50443
noise:
  private_key_path: /var/lib/headscale/noise_private.key
prefixes:
  v4: 100.64.0.0/10
  v6: fd7a:115c:a1e0::/48
  allocation: sequential
derp:
  server:
    enabled: false
  urls:
    - https://controlplane.tailscale.com/derpmap/default
  auto_update_enabled: false
database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
dns:
  magic_dns: false
  override_local_dns: false
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
"""

# Headscale and the phone are added to the bundle for the rehearsal only. The tailscale container is pointed at
# Headscale in place of Tailscale's control server.
OVERRIDE = f"""\
services:
  tailscale:
    environment:
      TS_EXTRA_ARGS: --login-server={LOGIN_SERVER}
    depends_on:
      headscale:
        condition: service_healthy
  headscale:
    image: {HEADSCALE}
    command: serve
    read_only: true
    tmpfs: [/var/run/headscale, /var/lib/headscale]
    volumes:
      - ./headscale:/etc/headscale:ro
    healthcheck:
      test: [CMD, headscale, health]
      interval: 5s
      retries: 24
    networks: [internal]
  phone:
    image: {PHONE}
    profiles: [tailnet]
    depends_on:
      headscale:
        condition: service_healthy
    environment:
      TS_AUTHKEY: file:/run/secrets/tailscale_authkey
      TS_EXTRA_ARGS: --login-server={LOGIN_SERVER}
      TS_HOSTNAME: phone
      TS_USERSPACE: "true"
      TS_STATE_DIR: /var/lib/tailscale
    secrets: [tailscale_authkey]
    tmpfs: [/var/lib/tailscale]
    networks: [internal]
"""

PLAIN_REQUEST = "GET / HTTP/1.0\\r\\nHost: franca\\r\\n\\r\\n"


def sh(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if check and result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"Command failed: {' '.join(command[:8])}")
    return result


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def check(condition: bool, message: str, failures: list[str]) -> None:
    print(("ok:   " if condition else "FAIL: ") + message, flush=True)
    if not condition:
        failures.append(message)


def main() -> int:
    os.chdir(ROOT)
    sh("docker", "build", "--quiet", "-f", "infra/images/app.Dockerfile", "--build-arg", "FRANCA_VERSION=1.0.0", "-t", APP, ".")
    sh("docker", "build", "--quiet", "-f", "infra/images/caddy.Dockerfile", "-t", CADDY, ".")
    sh("docker", "build", "--quiet", "-f", "infra/images/tailscale.Dockerfile", "-t", TAILSCALE, ".")
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        (bundle / "compose.yaml").write_text((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        (bundle / "compose.override.yaml").write_text(OVERRIDE, encoding="utf-8")
        (bundle / "headscale").mkdir()
        (bundle / "headscale" / "config.yaml").write_text(HEADSCALE_CONFIG, encoding="utf-8")
        secrets = bundle / "secrets"
        secrets.mkdir()
        for name in ("google_client_secret", "session_secret", "backup_password", "tailscale_authkey"):
            empty = name in {"google_client_secret", "tailscale_authkey"}
            (secrets / name).write_text("" if empty else os.urandom(32).hex(), encoding="utf-8")
        (bundle / ".env").write_text(
            "\n".join(
                [
                    "FRANCA_VERSION=1.0.0",
                    f"FRANCA_APP_IMAGE={APP}",
                    f"FRANCA_CADDY_IMAGE={CADDY}",
                    f"FRANCA_TAILSCALE_IMAGE={TAILSCALE}",
                    f"FRANCA_PORT={free_port()}",
                    f"FRANCA_SECRETS_DIR={secrets}",
                    "COMPOSE_PROFILES=tailnet",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        compose = ["docker", "compose", "--project-directory", str(bundle), "--project-name", PROJECT]

        def headscale(*arguments: str) -> str:
            return sh(*compose, "exec", "-T", "headscale", "headscale", *arguments).stdout

        def from_phone(port: int) -> subprocess.CompletedProcess[str]:
            script = f"printf '{PLAIN_REQUEST}' | timeout 15 tailscale nc {franca_ip} {port}"
            return sh(*compose, "exec", "-T", "phone", "sh", "-c", script, check=False)

        try:
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "headscale")
            headscale("users", "create", "rehearsal")
            users = json.loads(headscale("users", "list", "--output", "json"))
            user_id = str(next(user["id"] for user in users if user["name"] == "rehearsal"))
            created = json.loads(
                headscale("preauthkeys", "create", "--user", user_id, "--reusable", "--expiration", "1h", "--output", "json")
            )
            # The key goes in the secret file, as the installer will write the owner's key on the PC.
            (secrets / "tailscale_authkey").write_text(created["key"], encoding="utf-8")
            for secret in secrets.iterdir():
                secret.chmod(0o644)

            started = sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180", check=False)
            check(started.returncode == 0, "the bundle starts with the tailnet profile, and its containers are healthy", failures)
            nodes = json.loads(headscale("nodes", "list", "--output", "json"))
            names = {node.get("given_name") or node.get("name") for node in nodes}
            check("franca" in names, "the PC joins the tailnet as franca", failures)

            franca_ip = sh(*compose, "exec", "-T", "tailscale", "tailscale", "ip", "-4").stdout.strip()
            # The phone needs a moment to learn about the PC after both have joined.
            reply = from_phone(443)
            for _ in range(10):
                if "HTTP/1." in reply.stdout:
                    break
                time.sleep(3)
                reply = from_phone(443)
            # Go's TLS server answers a plain HTTP request on an HTTPS port with an HTTP error, so this reply shows that
            # the connection reached Caddy's HTTPS port without being decrypted on the way.
            check(
                "HTTP/1." in reply.stdout and "HTTPS" in reply.stdout,
                "port 443 on the tailnet reaches Caddy's HTTPS port, still encrypted",
                failures,
            )
            for port in (8080, 8000, 8443):
                closed = from_phone(port)
                check("HTTP/1." not in closed.stdout, f"port {port} cannot be reached over the tailnet", failures)

            for service in ("app", "caddy", "tailscale"):
                container = sh(*compose, "ps", "--quiet", service).stdout.strip()
                bindings = json.loads(sh("docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container).stdout)
                hosts = {binding["HostIp"] for published in (bindings or {}).values() for binding in published}
                check(hosts <= {"127.0.0.1"}, f"{service} publishes no port beyond the PC's loopback", failures)

            container = sh(*compose, "ps", "--quiet", "tailscale").stdout.strip()
            settings = json.loads(sh("docker", "inspect", container).stdout)[0]
            user = settings["Config"]["User"]
            check(bool(user) and not user.startswith(("0", "root")), f"tailscale runs as user {user}", failures)
            check(settings["HostConfig"]["ReadonlyRootfs"] is True, "tailscale has a read-only file system", failures)
            check(settings["HostConfig"]["CapDrop"] == ["ALL"], "tailscale drops all capabilities", failures)
            check(not settings["HostConfig"]["Devices"], "tailscale has no devices such as /dev/net/tun", failures)
        finally:
            if failures:
                print(sh(*compose, "logs", "--no-color", "--tail", "60", check=False).stdout)
            sh(*compose, "down", "--volumes", "--remove-orphans", check=False)
    if failures:
        print(f"\nThe rehearsal failed: {len(failures)} check(s).")
        return 1
    print("\nThe rehearsal passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
