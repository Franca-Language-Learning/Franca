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
5. checks that Caddy's user can reach tailscaled through the shared socket and may ask for a certificate, and that
   another user may not;
6. checks that no container publishes a port beyond the PC's loopback;
7. checks that the tailscale container runs as a user, with a read-only file system and no capabilities.

Headscale cannot issue certificates, so the certificate itself is tried at the installer rehearsal on the PC.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rehearsal import (
    HEADSCALE,
    ROOT,
    Checks,
    build_image,
    check_hardened,
    compose_command,
    copy_compose_file,
    free_port,
    headscale_config,
    sh,
    tear_down,
    write_env,
    write_secrets,
)

PROJECT = f"franca-tailnet-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-tailnet"
CADDY = "franca/caddy:rehearsal-tailnet"
TAILSCALE = "franca/tailscale:rehearsal"
# A Tailscale container in place of a phone. The image is named by digest, and Renovate updates it (see
# .github/renovate.json).
PHONE = "tailscale/tailscale:v1.104.7@sha256:72c1e19e0aedca96b8533bbb0b4368564410ff20b17e53b804eb6c1f04a31be4"  # renovate: image
LOGIN_SERVER = "http://headscale:8080"

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
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
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
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
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


def main() -> int:
    os.chdir(ROOT)
    build_image("app", APP, "1.0.0")
    build_image("caddy", CADDY)
    build_image("tailscale", TAILSCALE)
    checks = Checks()
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        copy_compose_file(bundle, OVERRIDE)
        (bundle / "headscale").mkdir()
        (bundle / "headscale" / "config.yaml").write_text(headscale_config(), encoding="utf-8")
        key_folder = write_secrets(bundle / "secrets")
        write_env(
            bundle / ".env",
            {
                "FRANCA_VERSION": "1.0.0",
                "FRANCA_APP_IMAGE": APP,
                "FRANCA_CADDY_IMAGE": CADDY,
                "FRANCA_TAILSCALE_IMAGE": TAILSCALE,
                "FRANCA_PORT": str(free_port()),
                "FRANCA_SECRETS_DIR": str(key_folder),
                "COMPOSE_PROFILES": "tailnet",
            },
        )
        compose = compose_command(bundle, PROJECT)

        def headscale(*arguments: str) -> str:
            return sh(*compose, "exec", "-T", "headscale", "headscale", *arguments).stdout

        def from_phone(port: int) -> subprocess.CompletedProcess[str]:
            # The pause keeps the input open, so that nc does not close the connection before the answer arrives.
            script = f"(printf '{PLAIN_REQUEST}'; sleep 5) | timeout 15 tailscale nc {franca_ip} {port}"
            return sh(*compose, "exec", "-T", "phone", "sh", "-c", script, check=False)

        try:
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "headscale")
            for image in (HEADSCALE, PHONE):
                digest = sh("docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image, check=False).stdout.strip()
                print(f"info: {image} is {digest}", flush=True)
            headscale("users", "create", "rehearsal")
            users = json.loads(headscale("users", "list", "--output", "json"))
            user_id = str(next(user["id"] for user in users if user["name"] == "rehearsal"))
            created = json.loads(
                headscale("preauthkeys", "create", "--user", user_id, "--reusable", "--expiration", "1h", "--output", "json")
            )
            # The key goes in the secret file, as the installer will write the owner's key on the PC.
            (key_folder / "tailscale_authkey").write_text(created["key"], encoding="utf-8")

            started = sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180", check=False)
            checks.check(started.returncode == 0, "the bundle starts with the tailnet profile, and its containers are healthy")
            nodes = json.loads(headscale("nodes", "list", "--output", "json"))
            names = {node.get("given_name") or node.get("name") for node in nodes}
            checks.check("franca" in names, "the PC joins the tailnet as franca")

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
            checks.check(
                "HTTP/1." in reply.stdout and "HTTPS" in reply.stdout,
                "port 443 on the tailnet reaches Caddy's HTTPS port, still encrypted",
            )
            if "HTTP/1." not in reply.stdout:
                print(f"info: the answer on port 443 was {reply.stdout[:300]!r}, errors {reply.stderr[:300]!r}", flush=True)
            # 9002 is containerboot's port for metrics and health, which are switched off.
            for port in (8080, 8000, 8443, 9002):
                closed = from_phone(port)
                checks.check(
                    closed.returncode != 0 and "HTTP/1." not in closed.stdout,
                    f"port {port} cannot be reached over the tailnet",
                )

            # Caddy reaches tailscaled through the socket in the shared volume, as user 10002.
            def through_socket(user: str, *arguments: str) -> subprocess.CompletedProcess[str]:
                volume = f"{PROJECT}_tailscale-socket:/var/run/tailscale:ro"
                return sh(
                    "docker", "run", "--rm", "--user", user, "-v", volume, "--entrypoint", "tailscale", TAILSCALE, *arguments, check=False
                )

            status = through_socket("10002:10002", "status", "--json")
            checks.check(
                status.returncode == 0 and '"BackendState": "Running"' in status.stdout,
                "Caddy's user reaches tailscaled through the socket",
            )
            cert = ["cert", "--cert-file", "-", "--key-file", "-", "franca.rehearsal.ts.net"]
            allowed = through_socket("10002:10002", *cert)
            # Headscale issues no certificates, so the request fails, but for a reason other than access.
            checks.check(
                "access denied" not in (allowed.stdout + allowed.stderr).lower(),
                "Caddy's user may ask tailscaled for a certificate",
            )
            refused = through_socket("10005:10005", *cert)
            checks.check("access denied" in (refused.stdout + refused.stderr).lower(), "another user may not ask for a certificate")

            for service in ("app", "caddy", "tailscale"):
                container = sh(*compose, "ps", "--quiet", service).stdout.strip()
                bindings = json.loads(sh("docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container).stdout)
                hosts = {binding["HostIp"] for published in (bindings or {}).values() for binding in published}
                checks.check(hosts <= {"127.0.0.1"}, f"{service} publishes no port beyond the PC's loopback")

            settings = check_hardened(checks, compose, "tailscale", "tailscale")
            checks.check(not settings["HostConfig"]["Devices"], "tailscale has no devices such as /dev/net/tun")
        finally:
            tear_down(compose, show_logs=bool(checks.failures))
    return checks.exit_code()


if __name__ == "__main__":
    sys.exit(main())
