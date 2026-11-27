"""Helpers for the rehearsals in this folder (rehearse_*.py), which try parts of Franca with real containers.

In each rehearsal, the images are built, a bundle folder is written in a temporary folder (compose.yaml, the secret
files and .env), the containers are started, "ok" or "FAIL" is printed for each check, and the containers and volumes
are removed at the end. The rehearsals are run from the repository root with Python 3.14 and the standard library only,
in the Container bundle job of the pipeline. The helpers have unit tests in test_rehearsal.py.
"""

import json
import os
import socket
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# The secret files that infra/compose.yaml names. Compose needs each file to exist, even for a profile that is off.
SECRET_NAMES = (
    "google_client_secret",
    "session_secret",
    "backup_password",
    "tailscale_authkey",
    "ntfy_topic",
    "status_push_token",
    "healthchecks_ping_url",
)
# An open-source Tailscale control server, used in place of Tailscale's own, so no account is needed. The image is named
# by digest, and Renovate updates it (see .github/renovate.json).
HEADSCALE = "headscale/headscale:0.29.7@sha256:11f81665e842809db9fe3006a38c56a66e968baa5abd4bac498e86445572b970"  # renovate: image
# Settings of the Tailscale containers in a rehearsal, so that nothing is sent to Tailscale's servers. Logs are not
# uploaded to log.tailscale.com, the relay (DERP) in Headscale is reached over plain HTTP, because Headscale has no
# certificate in the rehearsal, and the router is not asked to open a port. The bundle's own settings in
# infra/compose.yaml are not changed, because on the PC the container is a device in the owner's tailnet at Tailscale.
TAILSCALE_REHEARSAL_ENVIRONMENT = {
    "TS_NO_LOGS_NO_SUPPORT": "true",
    "TS_DEBUG_USE_DERP_HTTP": "true",
    "TS_DISABLE_PORTMAPPER": "true",
}
# Global options of Caddy in a rehearsal: certificates come from Caddy's own local authority, not from Let's Encrypt or
# another public authority, and Caddy does not try to add that authority to the system's trusted certificates.
CADDY_REHEARSAL_OPTIONS = ("local_certs", "skip_install_trust")


def sh(*command: str, check: bool = True, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Runs a command and returns its result. With check, the output of a failed command is printed and the rehearsal
    ends."""
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, check=False)  # noqa: S603
    if check and result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"Command failed: {' '.join(command[:8])}")
    return result


def free_port() -> int:
    """Returns a TCP port on the loopback address that no program is listening on at the moment."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class Checks:
    """The results of a rehearsal's checks. Each one is printed as it is made, and the failures are kept."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        print(("ok:   " if condition else "FAIL: ") + message, flush=True)
        if not condition:
            self.failures.append(message)

    def exit_code(self) -> int:
        """Prints whether the rehearsal passed, and returns the exit code for the script: 0 or 1."""
        if self.failures:
            print(f"\nThe rehearsal failed: {len(self.failures)} check(s).")
            return 1
        print("\nThe rehearsal passed.")
        return 0


def build_image(service: str, tag: str, version: str | None = None) -> None:
    """Builds infra/images/<service>.Dockerfile from the repository root. When version is given, it is passed to the build
    as FRANCA_VERSION."""
    arguments = ["--build-arg", f"FRANCA_VERSION={version}"] if version else []
    sh("docker", "build", "--quiet", "-f", f"infra/images/{service}.Dockerfile", *arguments, "-t", tag, str(ROOT))


def random_secret() -> str:
    return os.urandom(32).hex()


def write_secrets(folder: Path, values: Mapping[str, str] | None = None) -> Path:
    """Writes a file for each secret in compose.yaml and returns the folder. A secret in values is written as given.
    Otherwise the session secret and the backup password are random, and the other secrets are empty. A secret file is
    mounted in a container with the permissions it has on the host, and each container reads it as its own user, so the
    files can be read by all users."""
    given = {"session_secret": random_secret(), "backup_password": random_secret()} | dict(values or {})
    folder.mkdir(exist_ok=True)
    for name in SECRET_NAMES:
        path = folder / name
        path.write_text(given.get(name, ""), encoding="utf-8")
        path.chmod(0o644)
    return folder


def write_env(path: Path, values: Mapping[str, str]) -> None:
    """Writes the bundle's .env file, one KEY=value line for each value."""
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def copy_compose_file(bundle: Path, override: str | None = None) -> None:
    """Puts infra/compose.yaml in the bundle folder, with compose.override.yaml beside it when there is an override."""
    (bundle / "compose.yaml").write_text((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    if override is not None:
        (bundle / "compose.override.yaml").write_text(override, encoding="utf-8")


def compose_command(bundle: Path, project: str | None = None) -> list[str]:
    """Returns the docker compose command for the bundle folder. With project, the command has a project name of its own,
    so it does not touch another bundle."""
    command = ["docker", "compose", "--project-directory", str(bundle)]
    return command + ["--project-name", project] if project else command


def tear_down(compose: Sequence[str], show_logs: bool, tail: int = 60) -> None:
    """Stops the bundle and removes its volumes. With show_logs, the end of each container's log is printed first."""
    if show_logs:
        print(sh(*compose, "logs", "--no-color", "--tail", str(tail), check=False).stdout)
    sh(*compose, "down", "--volumes", "--remove-orphans", check=False)


def services_not_healthy(listed: Sequence[str], services: Sequence[str]) -> list[str]:
    """The services that are not running with a passing health check, each with what is wrong. listed has one line per
    container, as `docker compose ps --format "{{.Service}} {{.State}} {{.Health}}"` writes it. A container with no
    health check has an empty health field, and counts as a problem."""
    states = {fields[0]: fields[1:] for fields in (line.split() for line in listed) if fields}
    problems: list[str] = []
    for service in services:
        state = states.get(service)
        if state is None:
            problems.append(f"{service}: not started")
        elif state[:1] != ["running"]:
            problems.append(f"{service}: {' '.join(state)}")
        elif state[1:] == []:
            problems.append(f"{service}: running, with no health check")
        elif state[1:] != ["healthy"]:
            problems.append(f"{service}: running, {' '.join(state[1:])}")
    return problems


def docker_group(socket: Path = Path("/var/run/docker.sock")) -> str:
    """The number of the group that owns Docker's socket, for FRANCA_DOCKER_GID in .env. The socket proxy runs in this
    group, as a user other than root."""
    return str(socket.stat().st_gid)


def check_hardened(checks: Checks, compose: Sequence[str], service: str, name: str) -> dict[str, Any]:
    """Checks that a service's container runs as a user other than root, with a read-only file system and no
    capabilities. Returns the container's settings as docker inspect shows them, for further checks."""
    container = sh(*compose, "ps", "--quiet", service).stdout.strip()
    settings: dict[str, Any] = json.loads(sh("docker", "inspect", container).stdout)[0]
    user = settings["Config"]["User"]
    checks.check(bool(user) and not user.startswith(("0", "root")), f"{name} runs as user {user}")
    checks.check(settings["HostConfig"]["ReadonlyRootfs"] is True, f"{name} has a read-only file system")
    checks.check(settings["HostConfig"]["CapDrop"] == ["ALL"], f"{name} drops all capabilities")
    return settings


def environment_lines(values: Mapping[str, str], indent: int) -> str:
    """The values as lines of a YAML mapping, KEY: "value", indented by the given number of spaces, for the environment
    of a service in a Compose override."""
    return "".join(f"{' ' * indent}{key}: {json.dumps(value)}\n" for key, value in values.items())


def rehearsal_caddyfile() -> str:
    """The bundle's Caddyfile (infra/caddy/Caddyfile) with CADDY_REHEARSAL_OPTIONS at the start of its global options."""
    lines = (ROOT / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index("{\n") + 1
    return "".join(lines[:start] + [f"\t{option}\n" for option in CADDY_REHEARSAL_OPTIONS] + lines[start:])


def write_rehearsal_caddyfile(folder: Path) -> Path:
    """Writes rehearsal_caddyfile() to Caddyfile in the folder and returns its path. Caddy runs as its own user, so the
    file can be read by all users."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "Caddyfile"
    path.write_text(rehearsal_caddyfile(), encoding="utf-8")
    path.chmod(0o644)
    return path


def headscale_config(base_domain: str | None = None) -> str:
    """Headscale's settings for a rehearsal. With a base domain, MagicDNS is on and the devices get names under it.

    Headscale runs its own relay (DERP) and STUN server, and the devices are given a relay map with that relay only, not
    Tailscale's public relays. Headscale does not check GitHub for a newer version, and does not ask the devices to send
    their logs to Tailscale."""
    dns = f"  magic_dns: true\n  base_domain: {base_domain}\n" if base_domain else "  magic_dns: false\n"
    return f"""\
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
    enabled: true
    region_id: 999
    region_code: headscale
    region_name: Headscale
    stun_listen_addr: 0.0.0.0:3478
    private_key_path: /var/lib/headscale/derp_server_private.key
    automatically_add_embedded_derp_region: true
  urls: []
  paths: []
  auto_update_enabled: false
disable_check_updates: true
logtail:
  enabled: false
database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
dns:
{dns}  override_local_dns: false
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
"""
