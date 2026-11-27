"""A rehearsal of the Linux part of the installer with real containers (story E01-011). Run from the repository root:
    python3 infra/tests/rehearse_install.py

It needs Docker with Compose, sudo without a password and uv, and builds the images itself. The installer runs as root
with Python 3.13, the version in the Franca WSL system. Headscale is used in place of Tailscale's control server, and a
small web server in this script is used in place of ntfy.sh. The Windows part (Install-Franca.ps1) is tried on the
owner's PC.

The rehearsal:
1. starts Headscale and makes a sign-up key;
2. runs the installer with the owner's answers on its standard input and a local release;
3. checks that each service of the bundle is running and has a passing health check, that the socket proxy runs as a
   user other than root, that the PC's Tailscale name is in .env, that the used key is gone, that the secrets and the
   backup folder have the right owners and permissions, and that a test alert was sent;
4. runs the installer again with a new key and checks that the backup password is kept and not shown again.
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from rehearsal import (
    HEADSCALE,
    ROOT,
    Checks,
    build_image,
    check_hardened,
    compose_command,
    headscale_config,
    services_not_healthy,
    sh,
    tear_down,
)

PROJECT = f"franca-install-rehearsal-{os.getpid()}"
NETWORK = f"franca-install-rehearsal-{os.getpid()}"
HEADSCALE_NAME = f"franca-install-headscale-{os.getpid()}"
IMAGES = {service: f"franca/{service}:rehearsal-install" for service in ("app", "caddy", "updater", "backup", "tailscale", "status")}

# The bundle's tailscale container is pointed at Headscale, which runs outside the bundle on its own network.
OVERRIDE = f"""\
services:
  tailscale:
    environment:
      TS_EXTRA_ARGS: --login-server=http://headscale:8080
    networks: [internal, rehearsal]
  # Headscale issues no certificates, so the HTTPS check fails. Its alerts go nowhere, not to ntfy.sh.
  status:
    environment:
      FRANCA_NTFY_URL: http://127.0.0.1:9
networks:
  rehearsal:
    external: true
    name: {NETWORK}
"""


class AlertRecorder(http.server.BaseHTTPRequestHandler):
    """Stands in for ntfy.sh: keeps the path and body of each POST."""

    received: list[tuple[str, str]] = []

    def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
        length = int(self.headers.get("Content-Length", 0))
        AlertRecorder.received.append((self.path, self.rfile.read(length).decode()))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_arguments: object) -> None:
        pass


def headscale(*arguments: str) -> str:
    return sh("docker", "exec", HEADSCALE_NAME, "headscale", *arguments).stdout


def new_key() -> str:
    # Headscale lists no users as null.
    users = json.loads(headscale("users", "list", "--output", "json") or "null") or []
    if not any(user["name"] == "rehearsal" for user in users):
        headscale("users", "create", "rehearsal")
        users = json.loads(headscale("users", "list", "--output", "json"))
    user_id = str(next(user["id"] for user in users if user["name"] == "rehearsal"))
    created = json.loads(headscale("preauthkeys", "create", "--user", user_id, "--expiration", "1h", "--output", "json"))
    key: str = created["key"]
    return key


def main() -> int:
    os.chdir(ROOT)
    for service, image in IMAGES.items():
        build_image(service, image, "1.0.0")
    python = sh("uv", "run", "--no-project", "--python", "3.13", "python", "-c", "import sys; print(sys.executable)").stdout.strip()
    checks = Checks()
    recorder = http.server.HTTPServer(("127.0.0.1", 0), AlertRecorder)
    threading.Thread(target=recorder.serve_forever, daemon=True).start()
    ntfy_url = f"http://127.0.0.1:{recorder.server_address[1]}"
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        bundle = work / "opt-franca"
        disk = work / "disk-j"
        disk.mkdir()
        bundle.mkdir()
        (bundle / "compose.override.yaml").write_text(OVERRIDE, encoding="utf-8")
        (work / "headscale").mkdir()
        (work / "headscale" / "config.yaml").write_text(headscale_config(base_domain="rehearsal.ts.net"), encoding="utf-8")
        release = work / "release.json"
        release.write_text(json.dumps({"version": "1.0.0", "images": IMAGES}), encoding="utf-8")
        compose = ["sudo", *compose_command(bundle)]

        def run_installer(key: str) -> subprocess.CompletedProcess[str]:
            answers = {
                "owner_email": "owner@example.org",
                "google_client_id": "123-rehearsal.apps.googleusercontent.com",
                "google_client_secret": "rehearsal-client-secret",
                "tailscale_authkey": key,
                "backup_dir": str(disk / "franca-backups"),
            }
            command = [python, "installer/linux/franca_install.py", "--bundle-dir", str(bundle), "--compose-file", "infra/compose.yaml"]
            command += ["--release-file", str(release), "--skip-docker", "--ntfy-url", ntfy_url, "--project-name", PROJECT]
            # The installer's own folder has the updater's code beside it in the package; here it is found through PYTHONPATH.
            return sh("sudo", f"PYTHONPATH={ROOT / 'infra' / 'updater'}", *command, check=False, stdin=json.dumps(answers))

        try:
            sh("docker", "network", "create", NETWORK)
            sh(
                "docker", "run", "--detach", "--name", HEADSCALE_NAME, "--network", NETWORK, "--network-alias", "headscale",
                "--read-only", "--cap-drop", "ALL", "--tmpfs", "/var/lib/headscale", "--tmpfs", "/var/run/headscale",
                "-v", f"{work / 'headscale'}:/etc/headscale:ro", HEADSCALE, "serve",
            )  # fmt: skip
            for _ in range(30):
                if sh("docker", "exec", HEADSCALE_NAME, "headscale", "health", check=False).returncode == 0:
                    break
                sh("sleep", "2")

            installed = run_installer(new_key())
            checks.check(installed.returncode == 0, "the installer finishes")
            if installed.returncode != 0:
                print(installed.stdout[-3000:], installed.stderr[-3000:], sep="\n")
            shown = json.loads(installed.stdout.strip().splitlines()[-1]) if installed.stdout.strip() else {}
            checks.check(shown.get("address") == "https://franca.rehearsal.ts.net", "the address on the tailnet is shown")
            checks.check(
                bool(shown.get("backup_password")) and bool(shown.get("ntfy_topic")),
                "the backup password and the topic are shown",
            )

            env = sh("sudo", "cat", str(bundle / ".env")).stdout
            checks.check("FRANCA_PUBLIC_URL=https://franca.rehearsal.ts.net" in env, ".env has the public address on the Tailscale name")
            checks.check("rehearsal-client-secret" not in env, ".env has no secret in it")
            key_left = sh("sudo", "cat", str(bundle / "secrets" / "tailscale_authkey")).stdout
            checks.check(key_left == "", "the used auth key is not kept")
            modes = sh("sudo", "stat", "-c", "%n %a %u", str(bundle), str(bundle / "secrets"), str(disk / "franca-backups")).stdout
            checks.check(f"{bundle} 755 10003" in modes, "the bundle folder belongs to the updater's user")
            checks.check(f"{bundle / 'secrets'} 700 0" in modes, "the secrets folder is root's alone")
            checks.check(f"{disk / 'franca-backups'} 755 10001" in modes, "the backup folder belongs to the backup's user")
            checks.check((disk / "franca-backups" / ".franca-backup-disk").exists(), "the backup folder has the disk marker")

            services = sh(*compose, "config", "--services").stdout.split()
            listed = sh(*compose, "ps", "--format", "{{.Service}} {{.State}} {{.Health}}").stdout.splitlines()
            # A service with no health check counts as a failure here.
            problems = services_not_healthy(listed, services)
            checks.check(not problems, f"all {len(services)} services of the bundle are running, and their health checks pass")
            if problems:
                print(f"info: {problems}", flush=True)
            env_values = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
            checks.check(bool(env_values.get("FRANCA_DOCKER_GID", "").isdigit()), ".env names the group of Docker's socket")
            check_hardened(checks, compose, "socket-proxy", "the socket proxy")
            topic = shown.get("ntfy_topic", "")
            checks.check(any(path == f"/{topic}" and "test alert" in body for path, body in AlertRecorder.received), "a test alert is sent")

            again = run_installer(new_key())
            checks.check(again.returncode == 0, "the installer can be run again")
            shown_again = json.loads(again.stdout.strip().splitlines()[-1]) if again.stdout.strip() else {}
            checks.check("backup_password" not in shown_again, "a second run keeps the backup password and does not show it")
        finally:
            tear_down(compose, show_logs=bool(checks.failures), tail=40)
            sh("docker", "rm", "--force", HEADSCALE_NAME, check=False)
            sh("docker", "network", "rm", NETWORK, check=False)
            sh("sudo", "rm", "-rf", str(bundle), str(disk / "franca-backups"), check=False)
    recorder.shutdown()
    return checks.exit_code()


if __name__ == "__main__":
    sys.exit(main())
