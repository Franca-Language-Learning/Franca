"""A rehearsal of the Linux part of the installer with real containers (story E01-011). Run from the repository root:
    python3 infra/tests/rehearse_install.py

It needs Docker with Compose, sudo without a password and uv, and builds the images itself. The installer runs as root
with Python 3.13, the version in the Franca WSL system. Headscale is used in place of Tailscale's control server, and a
small web server in this script is used in place of ntfy.sh. The Windows part (Install-Franca.ps1) is tried on the
owner's PC.

The rehearsal:
1. starts Headscale and makes a sign-up key;
2. runs the installer with the owner's answers on its standard input and a local release;
3. checks that the bundle is running and healthy, that the PC's Tailscale name is in .env, that the used key is gone,
   that the secrets and the backup folder have the right owners and permissions, and that a test alert was sent;
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

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "franca"
NETWORK = f"franca-install-rehearsal-{os.getpid()}"
HEADSCALE_NAME = f"franca-install-headscale-{os.getpid()}"
HEADSCALE = "headscale/headscale:0.29.7@sha256:11f81665e842809db9fe3006a38c56a66e968baa5abd4bac498e86445572b970"  # renovate: image
IMAGES = {service: f"franca/{service}:rehearsal-install" for service in ("app", "caddy", "updater", "backup", "tailscale", "status")}

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
  magic_dns: true
  base_domain: rehearsal.ts.net
  override_local_dns: false
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
"""

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


def sh(*command: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False, input=input_text)  # noqa: S603
    if check and result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"Command failed: {' '.join(command[:8])}")
    return result


def check(condition: bool, message: str, failures: list[str]) -> None:
    print(("ok:   " if condition else "FAIL: ") + message, flush=True)
    if not condition:
        failures.append(message)


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
    users = json.loads(headscale("users", "list", "--output", "json") or "[]")
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
        sh(
            "docker",
            "build",
            "--quiet",
            "-f",
            f"infra/images/{service}.Dockerfile",
            "--build-arg",
            "FRANCA_VERSION=1.0.0",
            "-t",
            image,
            ".",
        )
    python = sh("uv", "run", "--no-project", "--python", "3.13", "python", "-c", "import sys; print(sys.executable)").stdout.strip()
    failures: list[str] = []
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
        (work / "headscale" / "config.yaml").write_text(HEADSCALE_CONFIG, encoding="utf-8")
        release = work / "release.json"
        release.write_text(json.dumps({"version": "1.0.0", "images": IMAGES}), encoding="utf-8")
        compose = ["docker", "compose", "--project-directory", str(bundle)]

        def run_installer(key: str) -> subprocess.CompletedProcess[str]:
            answers = {
                "owner_email": "owner@example.org",
                "google_client_id": "123-rehearsal.apps.googleusercontent.com",
                "google_client_secret": "rehearsal-client-secret",
                "tailscale_authkey": key,
                "backup_dir": str(disk / "franca-backups"),
            }
            command = [python, "installer/linux/franca_install.py", "--bundle-dir", str(bundle), "--compose-file", "infra/compose.yaml"]
            command += ["--release-file", str(release), "--skip-docker", "--ntfy-url", ntfy_url]
            # The installer's own folder has the updater's code beside it in the package; here it is found through PYTHONPATH.
            return sh("sudo", f"PYTHONPATH={ROOT / 'infra' / 'updater'}", *command, check=False, input_text=json.dumps(answers))

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
            check(installed.returncode == 0, "the installer finishes", failures)
            if installed.returncode != 0:
                print(installed.stdout[-3000:], installed.stderr[-3000:], sep="\n")
            shown = json.loads(installed.stdout.strip().splitlines()[-1]) if installed.stdout.strip() else {}
            check(shown.get("address") == "https://franca.rehearsal.ts.net", "the address on the tailnet is shown", failures)
            check(
                bool(shown.get("backup_password")) and bool(shown.get("ntfy_topic")),
                "the backup password and the topic are shown",
                failures,
            )

            env = sh("sudo", "cat", str(bundle / ".env")).stdout
            check("FRANCA_PUBLIC_URL=https://franca.rehearsal.ts.net" in env, ".env has the public address on the Tailscale name", failures)
            check("rehearsal-client-secret" not in env, ".env has no secret in it", failures)
            key_left = sh("sudo", "cat", str(bundle / "secrets" / "tailscale_authkey")).stdout
            check(key_left == "", "the used auth key is not kept", failures)
            modes = sh("sudo", "stat", "-c", "%n %a %u", str(bundle), str(bundle / "secrets"), str(disk / "franca-backups")).stdout
            check(f"{bundle} 755 10003" in modes, "the bundle folder belongs to the updater's user", failures)
            check(f"{bundle / 'secrets'} 700 0" in modes, "the secrets folder is root's alone", failures)
            check(f"{disk / 'franca-backups'} 755 10001" in modes, "the backup folder belongs to the backup's user", failures)
            check((disk / "franca-backups" / ".franca-backup-disk").exists(), "the backup folder has the disk marker", failures)

            states = [
                line.split() for line in sh("sudo", *compose, "ps", "--format", "{{.Service}} {{.State}} {{.Health}}").stdout.splitlines()
            ]
            unhealthy = [state for state in states if state[1:2] != ["running"] or state[2:] not in ([], ["healthy"])]
            check(not unhealthy and len(states) >= 8, f"the {len(states)} containers are running and healthy", failures)
            if unhealthy:
                print(f"info: {unhealthy}", flush=True)
            topic = shown.get("ntfy_topic", "")
            check(
                any(path == f"/{topic}" and "test alert" in body for path, body in AlertRecorder.received), "a test alert is sent", failures
            )

            again = run_installer(new_key())
            check(again.returncode == 0, "the installer can be run again", failures)
            shown_again = json.loads(again.stdout.strip().splitlines()[-1]) if again.stdout.strip() else {}
            check("backup_password" not in shown_again, "a second run keeps the backup password and does not show it", failures)
        finally:
            if failures:
                print(sh("sudo", *compose, "logs", "--no-color", "--tail", "40", check=False).stdout)
            sh("sudo", *compose, "down", "--volumes", "--remove-orphans", check=False)
            sh("docker", "rm", "--force", HEADSCALE_NAME, check=False)
            sh("docker", "network", "rm", NETWORK, check=False)
            sh("sudo", "rm", "-rf", str(bundle), str(disk / "franca-backups"), check=False)
    recorder.shutdown()
    if failures:
        print(f"\nThe rehearsal failed: {len(failures)} check(s).")
        return 1
    print("\nThe rehearsal passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
