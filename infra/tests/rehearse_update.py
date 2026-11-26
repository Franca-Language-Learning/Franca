"""A rehearsal of an update and a rollback against real containers (story E01-007). Run from the repository root:
    python3 infra/tests/rehearse_update.py

It needs Docker with Compose and builds the app and Caddy images itself. The updater's own code does the work, with
two stand-ins: the release comes from a list in this script in place of GitHub, and the signature check is skipped,
because local images have no signature. Everything else is real: compose stops and starts the containers, the
database snapshot is taken and put back in a one-off app container, and the health check goes through Caddy.

The rehearsal:
1. starts version 1.0.0 and writes a row to the database;
2. updates to 1.1.0, which has to answer the health check, and keeps the row;
3. tries 1.2.0, which adds a column to a table (as a migration would), writes a row and then fails to start. The
   updater has to go back to 1.1.0 and put back the database as it was before 1.2.0, so the row and the column are
   gone;
4. is offered 1.0.0 again, which is older and is not installed;
5. runs the updater's own container through the socket proxy: it can list the bundle's containers, and the proxy
   blocks docker exec.
"""

import os
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra" / "updater"))

import franca_updater as fu  # noqa: E402

PROJECT = f"franca-rehearsal-{os.getpid()}"
CADDY = "franca/caddy:rehearsal"
UPDATER = "franca/updater:rehearsal"


def app_image(version: str) -> str:
    return f"franca/app:rehearsal-{version}"


def sh(*command: str, stdin: str | None = None) -> str:
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"Command failed: {' '.join(command[:6])}")
    return result.stdout


def build_images() -> None:
    for version in ("1.0.0", "1.1.0"):
        sh(
            "docker",
            "build",
            "--quiet",
            "-f",
            "infra/images/app.Dockerfile",
            "--build-arg",
            f"FRANCA_VERSION={version}",
            "-t",
            app_image(version),
            ".",
        )
    sh("docker", "build", "--quiet", "-f", "infra/images/caddy.Dockerfile", "-t", CADDY, ".")
    # Version 1.2.0 changes the schema and the data, and then stops, as a broken release might.
    broken = f"""FROM {app_image("1.1.0")}
ENV FRANCA_VERSION=1.2.0
CMD ["python", "-c", "import sqlite3, sys; c = sqlite3.connect('/data/franca.db'); c.execute('ALTER TABLE rehearsal ADD COLUMN added_by_120 TEXT'); c.execute(\\"INSERT INTO rehearsal (note) VALUES ('written by 1.2.0')\\"); c.commit(); sys.exit(1)"]
"""
    sh("docker", "build", "--quiet", "-t", app_image("1.2.0"), "-", stdin=broken)
    sh("docker", "build", "--quiet", "-f", "infra/images/updater.Dockerfile", "-t", UPDATER, ".")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class LocalCompose(fu.Compose):
    """The images are built here, so pulling is checking that the image is there."""

    def pull(self, image: str) -> None:
        sh("docker", "image", "inspect", image)


class AcceptLocalImages:
    def verify(self, image: str, version: fu.Version) -> None:
        if not image.startswith("franca/"):
            raise fu.UpdateError(f"The rehearsal only installs its own images, not {image}")


class Offer(fu.GitHubReleases):
    def __init__(self, version: str) -> None:
        self.release = fu.Release(fu.Version.parse(version), {"app": app_image(version), "caddy": CADDY})

    def latest(self) -> fu.Release:
        return self.release


def rows(compose: fu.Compose) -> list[str]:
    script = "import sqlite3; print('|'.join(r[0] for r in sqlite3.connect('/data/franca.db').execute('SELECT note FROM rehearsal ORDER BY rowid')))"
    result = compose.run(compose._compose("run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script))
    return [row for row in result.stdout.strip().split("|") if row]


def columns(compose: fu.Compose) -> list[str]:
    script = "import sqlite3; print('|'.join(r[1] for r in sqlite3.connect('/data/franca.db').execute('PRAGMA table_info(rehearsal)')))"
    result = compose.run(compose._compose("run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script))
    return result.stdout.strip().split("|")


def through_proxy(compose: fu.Compose, script: str) -> subprocess.CompletedProcess[str]:
    """Runs a shell script in the updater's container, which reaches Docker only through the socket proxy."""
    return compose.run(compose._compose("--profile", "updates", "run", "--rm", "--no-deps", "--entrypoint", "sh", "updater", "-c", script))


def add_row(compose: fu.Compose, note: str) -> None:
    script = (
        "import sqlite3; c = sqlite3.connect('/data/franca.db'); c.execute('CREATE TABLE IF NOT EXISTS rehearsal (note TEXT)'); "
        f"c.execute('INSERT INTO rehearsal VALUES (?)', ({note!r},)); c.commit()"
    )
    compose.run_in_app(script)


def check(condition: bool, message: str, failures: list[str]) -> None:
    print(("ok:   " if condition else "FAIL: ") + message, flush=True)
    if not condition:
        failures.append(message)


def main() -> int:
    os.chdir(ROOT)
    build_images()
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        # The updater's container runs as user 10003 and reads the bundle folder.
        bundle.chmod(0o755)
        (bundle / "compose.yaml").write_text((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        key_folder = bundle / "secrets"
        key_folder.mkdir()
        (key_folder / "google_client_secret").write_text("", encoding="utf-8")
        (key_folder / "session_secret").write_text(os.urandom(32).hex(), encoding="utf-8")
        (key_folder / "backup_password").write_text(os.urandom(32).hex(), encoding="utf-8")
        (key_folder / "tailscale_authkey").write_text("", encoding="utf-8")  # the tailnet profile is not used here
        for secret in key_folder.iterdir():
            secret.chmod(0o644)
        port = free_port()
        env = fu.EnvFile(bundle / ".env")
        env.write(
            {
                "FRANCA_VERSION": "1.0.0",
                "FRANCA_APP_IMAGE": app_image("1.0.0"),
                "FRANCA_CADDY_IMAGE": CADDY,
                "FRANCA_PORT": str(port),
                "FRANCA_SECRETS_DIR": str(key_folder),
                "FRANCA_UPDATER_IMAGE": UPDATER,
                "FRANCA_BUNDLE_DIR": str(bundle),
                "COMPOSE_PROJECT_NAME": PROJECT,
            }
        )
        (bundle / ".env").chmod(0o644)
        compose = LocalCompose(bundle, project_name=PROJECT)

        def run_updater(offer: str) -> str:
            updater = fu.Updater(
                releases=Offer(offer),
                verifier=AcceptLocalImages(),
                env=env,
                compose=compose,
                database=fu.Database(compose),
                probe=fu.health_probe(f"http://127.0.0.1:{port}/api/v1/health"),
                status=fu.StatusFile(bundle / "status" / "updater.json"),
                health_timeout=90,
            )
            return updater.run_once(datetime.now(UTC))

        try:
            sh(*compose._compose("up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "app", "caddy"))
            add_row(compose, "written by 1.0.0")
            probe = fu.health_probe(f"http://127.0.0.1:{port}/api/v1/health")

            check(run_updater("1.1.0") == "installed", "1.1.0 is installed", failures)
            check(probe() == "1.1.0", "the health check answers with 1.1.0", failures)
            check(rows(compose) == ["written by 1.0.0"], "the data written by 1.0.0 is kept", failures)
            add_row(compose, "written by 1.1.0")

            check(run_updater("1.2.0") == "rolled-back", "1.2.0 does not start and is rolled back", failures)
            check(probe() == "1.1.0", "after the rollback, the health check answers with 1.1.0", failures)
            check(
                rows(compose) == ["written by 1.0.0", "written by 1.1.0"],
                "the database is as it was before 1.2.0: the row written by 1.2.0 is gone",
                failures,
            )
            check(columns(compose) == ["note"], "the column added by 1.2.0 is gone", failures)
            check(env.read()["FRANCA_APP_IMAGE"] == app_image("1.1.0"), ".env names the 1.1.0 image again", failures)

            check(run_updater("1.0.0") == "up-to-date", "the older 1.0.0 is not installed", failures)
            check(probe() == "1.1.0", "1.1.0 is still running", failures)

            sh(*compose._compose("--profile", "updates", "up", "--detach", "--no-build", "socket-proxy"))
            listed = through_proxy(compose, 'docker compose --project-directory "$FRANCA_BUNDLE_DIR" ps --quiet app')
            check(
                listed.returncode == 0 and bool(listed.stdout.strip()), "the updater lists the app's container through the proxy", failures
            )
            app_id = listed.stdout.strip().splitlines()[-1] if listed.stdout.strip() else "none"
            refused = through_proxy(compose, f"docker exec {app_id} true")
            check(refused.returncode != 0, "the proxy blocks docker exec", failures)
        finally:
            if failures:
                print(sh(*compose._compose("logs", "--no-color", "--tail", "60")))
            subprocess.run(compose._compose("down", "--volumes", "--remove-orphans"), capture_output=True, check=False)  # noqa: S603
    if failures:
        print(f"\nThe rehearsal failed: {len(failures)} check(s).")
        return 1
    print("\nThe rehearsal passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
