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
5. starts the socket proxy and checks that it runs as a user other than root and that its health check passes;
6. runs the updater's own container through the socket proxy: it can list the bundle's containers, its check of the
   Docker API passes, and the proxy blocks docker exec.
"""

import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rehearsal import ROOT, Checks, build_image, check_hardened, copy_compose_file, docker_group, free_port, sh, tear_down, write_secrets

sys.path.insert(0, str(ROOT / "infra" / "updater"))

import franca_updater as fu  # noqa: E402

PROJECT = f"franca-rehearsal-{os.getpid()}"
CADDY = "franca/caddy:rehearsal"
UPDATER = "franca/updater:rehearsal"


def app_image(version: str) -> str:
    return f"franca/app:rehearsal-{version}"


def build_images() -> None:
    for version in ("1.0.0", "1.1.0"):
        build_image("app", app_image(version), version)
    build_image("caddy", CADDY)
    # Version 1.2.0 changes the schema and the data, and then stops, as a broken release might.
    broken = f"""FROM {app_image("1.1.0")}
ENV FRANCA_VERSION=1.2.0
CMD ["python", "-c", "import sqlite3, sys; c = sqlite3.connect('/data/franca.db'); c.execute('ALTER TABLE rehearsal ADD COLUMN added_by_120 TEXT'); c.execute(\\"INSERT INTO rehearsal (note) VALUES ('written by 1.2.0')\\"); c.commit(); sys.exit(1)"]
"""
    sh("docker", "build", "--quiet", "-t", app_image("1.2.0"), "-", stdin=broken)
    build_image("updater", UPDATER)


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


def main() -> int:
    os.chdir(ROOT)
    build_images()
    checks = Checks()
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        # The updater's container runs as user 10003 and reads the bundle folder.
        bundle.chmod(0o755)
        copy_compose_file(bundle)
        # The tailnet and monitoring profiles are not used here, and with no push token nothing is reported.
        key_folder = write_secrets(bundle / "secrets")
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
                "FRANCA_DOCKER_GID": docker_group(),
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

            checks.check(run_updater("1.1.0") == "installed", "1.1.0 is installed")
            checks.check(probe() == "1.1.0", "the health check answers with 1.1.0")
            checks.check(rows(compose) == ["written by 1.0.0"], "the data written by 1.0.0 is kept")
            add_row(compose, "written by 1.1.0")

            checks.check(run_updater("1.2.0") == "rolled-back", "1.2.0 does not start and is rolled back")
            checks.check(probe() == "1.1.0", "after the rollback, the health check answers with 1.1.0")
            checks.check(
                rows(compose) == ["written by 1.0.0", "written by 1.1.0"],
                "the database is as it was before 1.2.0: the row written by 1.2.0 is gone",
            )
            checks.check(columns(compose) == ["note"], "the column added by 1.2.0 is gone")
            checks.check(env.read()["FRANCA_APP_IMAGE"] == app_image("1.1.0"), ".env names the 1.1.0 image again")

            checks.check(run_updater("1.0.0") == "up-to-date", "the older 1.0.0 is not installed")
            checks.check(probe() == "1.1.0", "1.1.0 is still running")

            started = compose.run(
                compose._compose("--profile", "updates", "up", "--detach", "--no-build", "--wait", "--wait-timeout", "60", "socket-proxy")
            )
            checks.check(started.returncode == 0, "the socket proxy starts and its health check passes")
            check_hardened(checks, compose._compose("--profile", "updates"), "socket-proxy", "the socket proxy")
            probed = through_proxy(
                compose, "cd /app && python -c 'import franca_updater as fu; print(fu.docker_api_probe(\"tcp://socket-proxy:2375\")())'"
            )
            checks.check(probed.stdout.strip() == "None", "the updater's check of the Docker API passes through the proxy")
            listed = through_proxy(compose, 'docker compose --project-directory "$FRANCA_BUNDLE_DIR" ps --quiet app')
            checks.check(listed.returncode == 0 and bool(listed.stdout.strip()), "the updater lists the app's container through the proxy")
            app_id = listed.stdout.strip().splitlines()[-1] if listed.stdout.strip() else "none"
            refused = through_proxy(compose, f"docker exec {app_id} true")
            checks.check(refused.returncode != 0, "the proxy blocks docker exec")
        finally:
            tear_down(compose._compose(), show_logs=bool(checks.failures))
    return checks.exit_code()


if __name__ == "__main__":
    sys.exit(main())
