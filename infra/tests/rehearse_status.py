"""A rehearsal of health monitoring with real containers (story E01-010). Run from the repository root:
    python3 infra/tests/rehearse_status.py

It needs Docker with Compose and builds the images itself. A small web server that records what it is sent is used in
place of ntfy.sh, so no alert leaves the computer.

The rehearsal:
1. starts the app, Caddy and the status container with the monitoring profile;
2. checks that Gatus reports the app and the web server as healthy, and that the HTTPS and Tailscale checks are off
   while there is no Tailscale name;
3. checks that a report from a nightly job is accepted with the push token and refused without it;
4. reports a failed update and checks that an alert reaches the stand-in for ntfy, on the owner's topic;
5. stops the app and checks that an alert is sent after three failed checks;
6. checks that the start script refuses a topic that could change Gatus's configuration;
7. checks that the status container runs as a user, with a read-only file system and no capabilities.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra" / "backup"))
import franca_backup  # noqa: E402 - the backup's own code sends the reports in this rehearsal

PROJECT = f"franca-status-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-status"
CADDY = "franca/caddy:rehearsal-status"
STATUS = "franca/status:rehearsal"
TOPIC = "franca-rehearsal-alerts"

# A web server that prints each request it gets as a line of JSON, in place of ntfy.sh.
RECORDER = """
import http.server, json, sys
class Recorder(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        print(json.dumps({"path": self.path, "body": body}), flush=True)
        self.send_response(200)
        self.end_headers()
http.server.HTTPServer(("0.0.0.0", 8000), Recorder).serve_forever()
"""

OVERRIDE = f"""\
services:
  ntfy:
    image: {APP}
    entrypoint: ["python", "-c", {json.dumps(RECORDER)}]
    # The app image's health check asks for the app's health page, which the stand-in does not have.
    healthcheck:
      disable: true
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    networks: [internal]
"""


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


def push(base: str, key: str, token: str, query: str) -> int:
    """Sends a nightly job's report to Gatus, as the updater and the backup do, and returns the HTTP status."""
    request = urllib.request.Request(  # noqa: S310 - a local address
        f"{base}/api/v1/endpoints/{key}/external?{query}", method="POST", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - a local address
            status: int = response.status
            return status
    except urllib.error.HTTPError as error:
        return error.code


def statuses(base: str) -> dict[str, list[dict[str, Any]]]:
    """The results Gatus has for each endpoint, by key, newest last."""
    try:
        with urllib.request.urlopen(f"{base}/api/v1/endpoints/statuses", timeout=10) as response:  # noqa: S310
            listed: list[dict[str, Any]] = json.loads(response.read())
    except OSError, ValueError:
        return {}
    return {entry["key"]: entry.get("results") or [] for entry in listed}


def wait_for(condition: Any, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(5)
    return bool(condition())


def main() -> int:
    os.chdir(ROOT)
    sh("docker", "build", "--quiet", "-f", "infra/images/app.Dockerfile", "--build-arg", "FRANCA_VERSION=1.0.0", "-t", APP, ".")
    sh("docker", "build", "--quiet", "-f", "infra/images/caddy.Dockerfile", "-t", CADDY, ".")
    sh("docker", "build", "--quiet", "-f", "infra/images/status.Dockerfile", "-t", STATUS, ".")
    failures: list[str] = []
    token = os.urandom(32).hex()
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        (bundle / "compose.yaml").write_text((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        (bundle / "compose.override.yaml").write_text(OVERRIDE, encoding="utf-8")
        key_folder = bundle / "secrets"
        key_folder.mkdir()
        values = {"session_secret": os.urandom(32).hex(), "backup_password": os.urandom(32).hex(), "ntfy_topic": TOPIC}
        values["status_push_token"] = token
        for name in ("google_client_secret", "session_secret", "backup_password", "tailscale_authkey", "ntfy_topic", "status_push_token"):
            (key_folder / name).write_text(values.get(name, ""), encoding="utf-8")
            (key_folder / name).chmod(0o644)
        port = free_port()
        (bundle / ".env").write_text(
            "\n".join(
                [
                    "FRANCA_VERSION=1.0.0",
                    f"FRANCA_APP_IMAGE={APP}",
                    f"FRANCA_CADDY_IMAGE={CADDY}",
                    f"FRANCA_STATUS_IMAGE={STATUS}",
                    f"FRANCA_PORT={free_port()}",
                    f"FRANCA_STATUS_PORT={port}",
                    f"FRANCA_SECRETS_DIR={key_folder}",
                    "FRANCA_NTFY_URL=http://ntfy:8000",
                    "COMPOSE_PROFILES=monitoring",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        compose = ["docker", "compose", "--project-directory", str(bundle), "--project-name", PROJECT]
        base = f"http://127.0.0.1:{port}"

        def alerts() -> list[dict[str, Any]]:
            lines = sh(*compose, "logs", "--no-color", "--no-log-prefix", "ntfy", check=False).stdout.splitlines()
            sent = [json.loads(line) for line in lines if line.startswith("{")]
            return [json.loads(entry["body"]) for entry in sent if entry["body"].startswith("{")]

        def healthy(key: str) -> bool:
            results = statuses(base).get(key, [])
            return bool(results) and bool(results[-1].get("success"))

        try:
            started = sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", check=False)
            check(started.returncode == 0, "the bundle starts with the monitoring profile, and its containers are healthy", failures)
            if started.returncode != 0:
                print(started.returncode, started.stdout[-3000:], started.stderr[:1500], started.stderr[-3000:], sep="\n", flush=True)
                print(sh(*compose, "ps", "--all", check=False).stdout, flush=True)

            check(wait_for(lambda: healthy("franca_app"), 90), "Gatus reports the app as healthy", failures)
            check(wait_for(lambda: healthy("franca_web-server"), 30), "Gatus reports the web server as healthy", failures)
            keys = set(statuses(base))
            check(
                "franca_app" in keys and not keys & {"franca_https-on-the-tailscale-name", "franca_tailscale"},
                "the HTTPS and Tailscale checks are off while there is no Tailscale name",
                failures,
            )

            # The reports are sent with the backup's own Monitor, from this computer to the dashboard's port.
            monitor = franca_backup.Monitor(base, key_folder / "status_push_token")
            monitor.report("nightly_backup", True, "The database was backed up")
            check(wait_for(lambda: healthy("nightly_backup"), 20), "a report with the push token is accepted", failures)
            check(push(base, "nightly_backup", "wrong" * 8, "success=true") == 401, "a report with another token is refused", failures)

            monitor.report("nightly_update", False, "rehearsal: the update was rolled back")
            check(
                wait_for(lambda: any(a.get("topic") == TOPIC and "Update" in a.get("title", "") for a in alerts()), 60),
                "an alert about the failed update reaches ntfy on the owner's topic",
                failures,
            )

            sh(*compose, "stop", "app")
            check(
                wait_for(lambda: any("App" in a.get("title", "") for a in alerts()), 300),
                "an alert is sent when the app stops answering",
                failures,
            )

            with tempfile.TemporaryDirectory() as bad:
                for name, value in (("ntfy_topic", "short"), ("status_push_token", token)):
                    (Path(bad) / name).write_text(value, encoding="utf-8")
                    (Path(bad) / name).chmod(0o644)
                Path(bad).chmod(0o755)
                secrets = f"{bad}:/run/secrets:ro"
                refused = sh("docker", "run", "--rm", "-v", secrets, STATUS, check=False)
                check(
                    refused.returncode != 0 and "ntfy topic" in refused.stderr,
                    "the start script refuses a topic that is too short",
                    failures,
                )
                (Path(bad) / "ntfy_topic").write_text(TOPIC, encoding="utf-8")
                # A line break in a value from .env could add settings to Gatus's configuration.
                injected = "FRANCA_NTFY_URL=https://ntfy.sh\nweb:\n  port: 1"
                refused = sh("docker", "run", "--rm", "-v", secrets, "-e", injected, STATUS, check=False)
                check(
                    refused.returncode != 0 and "FRANCA_NTFY_URL" in refused.stderr,
                    "the start script refuses a value with a line break in it",
                    failures,
                )

            container = sh(*compose, "ps", "--quiet", "status").stdout.strip()
            settings = json.loads(sh("docker", "inspect", container).stdout)[0]
            user = settings["Config"]["User"]
            check(bool(user) and not user.startswith(("0", "root")), f"the status container runs as user {user}", failures)
            check(settings["HostConfig"]["ReadonlyRootfs"] is True, "the status container has a read-only file system", failures)
            check(settings["HostConfig"]["CapDrop"] == ["ALL"], "the status container drops all capabilities", failures)
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
