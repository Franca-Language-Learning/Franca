"""A rehearsal of health monitoring with real containers (story E01-010). Run from the repository root:
    python3 infra/tests/rehearse_status.py

It needs Docker with Compose and builds the images itself. A small web server that records what it is sent is used in
place of ntfy.sh and of healthchecks.io, so no alert or heartbeat leaves the computer.

The rehearsal:
1. starts the app, Caddy and the status container with the monitoring profile;
2. checks that Gatus reports the app, the web server, the sign-in page and the API behind the sign-in as healthy,
   and that the HTTPS and Tailscale checks are off while there is no Tailscale name;
3. checks that a report from a nightly job is accepted with the push token and refused without it;
4. reports a failed update and checks that an alert reaches the stand-in for ntfy, on the owner's topic;
5. stops the app and checks that an alert is sent after three failed checks;
6. checks that the start script refuses a topic that could change Gatus's configuration, and that a ping address
   that is not a plain web address turns the heartbeat off without stopping Gatus or showing the address;
7. checks that the status container runs as a user, with a read-only file system and no capabilities, and that its
   curl can use https;
8. checks that heartbeats reach the stand-in for healthchecks.io, that the ping address is not in the container's log
   or in its process list while a heartbeat is sent, that Gatus stays healthy while the stand-in cannot be reached and
   the heartbeats come back afterwards, and that the heartbeats stop when the status container stops (healthchecks.io
   then sends an alert).
"""

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from rehearsal import (
    ROOT,
    Checks,
    build_image,
    check_hardened,
    compose_command,
    copy_compose_file,
    free_port,
    random_secret,
    sh,
    tear_down,
    write_env,
    write_secrets,
)

sys.path.insert(0, str(ROOT / "infra" / "backup"))
import franca_backup  # noqa: E402 - the backup's own code sends the reports in this rehearsal

PROJECT = f"franca-status-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-status"
CADDY = "franca/caddy:rehearsal-status"
STATUS = "franca/status:rehearsal"
TOPIC = "franca-rehearsal-alerts"
# The ping address of the check on healthchecks.io has a random id, as the real one does.
PING_PATH = f"/ping/{os.urandom(16).hex()}"

# A web server that prints each POST it gets as a line of JSON, in place of ntfy.sh, and each GET under /ping/, in place
# of healthchecks.io. It answers a heartbeat after two seconds, so that curl can be seen in the process list. It answers
# other GET requests, so that the app image's health check, which the stand-in inherits, passes.
RECORDER = """
import http.server, json, sys, time
class Recorder(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/ping/"):
            print(json.dumps({"ping": self.path}), flush=True)
            time.sleep(2)
        self.send_response(200)
        self.end_headers()
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
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    networks: [internal]
"""


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


def container_health(container: str) -> str:
    """The health status that Docker reports for a container, such as healthy or starting."""
    return sh("docker", "inspect", "-f", "{{.State.Health.Status}}", container, check=False).stdout.strip()


def wait_for(condition: Any, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(5)
    return bool(condition())


def main() -> int:
    os.chdir(ROOT)
    build_image("app", APP, "1.0.0")
    build_image("caddy", CADDY)
    build_image("status", STATUS)
    checks = Checks()
    token = random_secret()
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        copy_compose_file(bundle, OVERRIDE)
        key_folder = write_secrets(
            bundle / "secrets", {"ntfy_topic": TOPIC, "status_push_token": token, "healthchecks_ping_url": f"http://ntfy:8000{PING_PATH}"}
        )
        port = free_port()
        write_env(
            bundle / ".env",
            {
                "FRANCA_VERSION": "1.0.0",
                "FRANCA_APP_IMAGE": APP,
                "FRANCA_CADDY_IMAGE": CADDY,
                "FRANCA_STATUS_IMAGE": STATUS,
                "FRANCA_PORT": str(free_port()),
                "FRANCA_STATUS_PORT": str(port),
                "FRANCA_SECRETS_DIR": str(key_folder),
                "FRANCA_NTFY_URL": "http://ntfy:8000",
                "FRANCA_HEARTBEAT_SECONDS": "5",
                "COMPOSE_PROFILES": "monitoring",
            },
        )
        compose = compose_command(bundle, PROJECT)
        base = f"http://127.0.0.1:{port}"

        def recorded() -> list[dict[str, str]]:
            lines = sh(*compose, "logs", "--no-color", "--no-log-prefix", "ntfy", check=False).stdout.splitlines()
            return [json.loads(line) for line in lines if line.startswith("{")]

        def alerts() -> list[dict[str, Any]]:
            sent = [entry for entry in recorded() if "body" in entry]
            return [json.loads(entry["body"]) for entry in sent if entry["body"].startswith("{")]

        def heartbeats() -> int:
            return sum(1 for entry in recorded() if entry.get("ping") == PING_PATH)

        def healthy(key: str) -> bool:
            results = statuses(base).get(key, [])
            return bool(results) and bool(results[-1].get("success"))

        try:
            started = sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", check=False)
            checks.check(started.returncode == 0, "the bundle starts with the monitoring profile, and its containers are healthy")
            if started.returncode != 0:
                print(started.returncode, started.stdout[-3000:], started.stderr[:1500], started.stderr[-3000:], sep="\n", flush=True)
                print(sh(*compose, "ps", "--all", check=False).stdout, flush=True)

            checks.check(wait_for(lambda: healthy("franca_app"), 90), "Gatus reports the app as healthy")
            checks.check(wait_for(lambda: healthy("franca_web-server"), 30), "Gatus reports the web server as healthy")
            checks.check(wait_for(lambda: healthy("franca_sign-in-page"), 30), "Gatus reports the sign-in page as healthy")
            checks.check(
                wait_for(lambda: healthy("franca_signed-in-api"), 30),
                "Gatus reports that the API behind the sign-in answers 401 without a session",
            )
            keys = set(statuses(base))
            checks.check(
                "franca_app" in keys and not keys & {"franca_https-on-the-tailscale-name", "franca_tailscale"},
                "the HTTPS and Tailscale checks are off while there is no Tailscale name",
            )

            # The reports are sent with the backup's own Monitor, from this computer to the dashboard's port.
            monitor = franca_backup.Monitor(base, key_folder / "status_push_token")
            monitor.report("nightly_backup", True, "The database was backed up")
            checks.check(wait_for(lambda: healthy("nightly_backup"), 20), "a report with the push token is accepted")
            checks.check(push(base, "nightly_backup", "wrong" * 8, "success=true") == 401, "a report with another token is refused")

            # The updater reports the socket proxy in the same way, every minute.
            monitor.report("franca_socket-proxy", True, "The Docker API answers through the socket proxy")
            checks.check(wait_for(lambda: healthy("franca_socket-proxy"), 20), "a report about the socket proxy is accepted")

            monitor.report("nightly_update", False, "rehearsal: the update was rolled back")
            checks.check(
                wait_for(lambda: any(a.get("topic") == TOPIC and "Update" in a.get("title", "") for a in alerts()), 60),
                "an alert about the failed update reaches ntfy on the owner's topic",
            )

            sh(*compose, "stop", "app")
            checks.check(
                wait_for(lambda: any("App" in a.get("title", "") for a in alerts()), 300),
                "an alert is sent when the app stops answering",
            )

            with tempfile.TemporaryDirectory() as bad:
                for name, value in (("ntfy_topic", "short"), ("status_push_token", token)):
                    (Path(bad) / name).write_text(value, encoding="utf-8")
                    (Path(bad) / name).chmod(0o644)
                Path(bad).chmod(0o755)
                secrets = f"{bad}:/run/secrets:ro"
                refused = sh("docker", "run", "--rm", "-v", secrets, STATUS, check=False)
                checks.check(
                    refused.returncode != 0 and "ntfy topic" in refused.stderr,
                    "the start script refuses a topic that is too short",
                )
                (Path(bad) / "ntfy_topic").write_text(TOPIC, encoding="utf-8")
                # A line break in a value from .env could add settings to Gatus's configuration.
                injected = "FRANCA_NTFY_URL=https://ntfy.sh\nweb:\n  port: 1"
                refused = sh("docker", "run", "--rm", "-v", secrets, "-e", injected, STATUS, check=False)
                checks.check(
                    refused.returncode != 0 and "FRANCA_NTFY_URL" in refused.stderr,
                    "the start script refuses a value with a line break in it",
                )
                (Path(bad) / "healthchecks_ping_url").write_text("https://hc-ping.com/abc?x=$(id)", encoding="utf-8")
                (Path(bad) / "healthchecks_ping_url").chmod(0o644)
                name = f"{PROJECT}-bad-ping"
                sh("docker", "run", "--detach", "--name", name, "-v", secrets, STATUS)
                try:
                    healthy_without_heartbeat = wait_for(lambda: container_health(name) == "healthy", 90)
                    logged = sh("docker", "logs", name, check=False)
                    checks.check(
                        healthy_without_heartbeat
                        and "the heartbeat is off" in logged.stderr
                        and "abc" not in logged.stdout + logged.stderr,
                        "a ping address that is not a plain web address turns the heartbeat off, Gatus keeps running, and the address is not shown",
                    )
                finally:
                    sh("docker", "rm", "--force", name, check=False)

            check_hardened(checks, compose, "status", "the status container")
            https = sh("docker", "run", "--rm", "--entrypoint", "sh", STATUS, "-c", "curl --version | grep -q https", check=False)
            checks.check(https.returncode == 0, "curl in the status image can use https")

            checks.check(wait_for(lambda: heartbeats() >= 2, 60), "heartbeats reach the stand-in for healthchecks.io")
            log = sh(*compose, "logs", "--no-color", "status", check=False)
            checks.check(PING_PATH not in log.stdout + log.stderr, "the ping address is not in the status container's log")

            # The process list is read many times while heartbeats are sent. The stand-in answers after two seconds, so
            # curl is running at some of these moments.
            status_id = sh(*compose, "ps", "--quiet", "status").stdout.strip()
            seen_curl, seen_address = False, False
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (seen_curl and seen_address):
                # docker top needs the pid column to pick the container's processes from the list.
                listed = sh("docker", "top", status_id, "-o", "pid,args", check=False).stdout
                seen_curl = seen_curl or "curl" in listed
                seen_address = seen_address or PING_PATH in listed
                time.sleep(0.3)
            checks.check(seen_curl, "curl is seen in the status container's process list while a heartbeat is sent")
            checks.check(not seen_address, "while a heartbeat is sent, the ping address is not in the process list")

            sh(*compose, "stop", "ntfy")
            time.sleep(15)
            during = sh(*compose, "logs", "--no-color", "status", check=False)
            status_health = container_health(status_id)
            checks.check(
                status_health == "healthy"
                and "the heartbeat to healthchecks.io could not be sent" in during.stderr + during.stdout
                and PING_PATH not in during.stderr + during.stdout,
                "while healthchecks.io cannot be reached, Gatus stays healthy and the failed heartbeat is logged without the address",
            )
            sh(*compose, "start", "ntfy")
            before = heartbeats()
            checks.check(wait_for(lambda: heartbeats() > before, 60), "the heartbeats come back when healthchecks.io can be reached again")

            sh(*compose, "stop", "status")
            stopped_at = heartbeats()
            time.sleep(15)
            checks.check(heartbeats() == stopped_at, "no heartbeat is sent while the status container is stopped")
        finally:
            tear_down(compose, show_logs=bool(checks.failures))
    return checks.exit_code()


if __name__ == "__main__":
    sys.exit(main())
