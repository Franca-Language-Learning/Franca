"""A rehearsal of the backup with real containers (story E01-008). Run from the repository root:
    python3 infra/tests/rehearse_backup.py

It needs Docker with Compose and builds the images itself. A temporary folder stands in for disk J:.

The rehearsal:
1. starts the app, the socket proxy and the updater, and writes a row to the database;
2. runs a backup in the backup container, then the monthly restore test. In the restore test the updater has to start
   the app on the restored copy in a one-off container, and the app's health check has to answer there. With the
   updates profile off, the restore test leaves out the app check and says so;
3. checks that the backup folder has an encrypted restic repository and no readable copy of the database;
4. deletes the row, stops the app, restores the latest backup and starts the app again; the row has to be back, and
   the database from before the restore has to be kept beside it;
5. checks that a restore is refused while the app is running.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rehearsal import (
    ROOT,
    Checks,
    build_image,
    compose_command,
    copy_compose_file,
    docker_group,
    free_port,
    sh,
    tear_down,
    write_env,
    write_secrets,
)

PROJECT = f"franca-backup-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-backup"
CADDY = "franca/caddy:rehearsal-backup"
BACKUP = "franca/backup:rehearsal"
UPDATER = "franca/updater:rehearsal-backup"


def main() -> int:
    os.chdir(ROOT)
    build_image("app", APP, "1.0.0")
    build_image("caddy", CADDY)
    build_image("backup", BACKUP)
    build_image("updater", UPDATER)
    checks = Checks()
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        # The updater's container runs as user 10003 and reads the bundle folder.
        bundle.chmod(0o755)
        copy_compose_file(bundle)
        key_folder = write_secrets(bundle / "secrets")
        backups = bundle / "disk-j"
        backups.mkdir()
        backups.chmod(0o777)  # the backup container's user (10001) writes here, as it will on disk J:
        (backups / ".franca-backup-disk").write_text("Franca backups\n", encoding="utf-8")  # the installer puts this here
        port = free_port()
        write_env(
            bundle / ".env",
            {
                "FRANCA_VERSION": "1.0.0",
                "FRANCA_APP_IMAGE": APP,
                "FRANCA_CADDY_IMAGE": CADDY,
                "FRANCA_BACKUP_IMAGE": BACKUP,
                "FRANCA_UPDATER_IMAGE": UPDATER,
                "FRANCA_PORT": str(port),
                "FRANCA_SECRETS_DIR": str(key_folder),
                "FRANCA_BACKUP_DIR": str(backups),
                "FRANCA_BUNDLE_DIR": str(bundle),
                "FRANCA_DOCKER_GID": docker_group(),
                # The updater runs docker compose for this bundle, under the same project name.
                "COMPOSE_PROJECT_NAME": PROJECT,
                "COMPOSE_PROFILES": "backups,updates",
            },
        )
        (bundle / ".env").chmod(0o644)
        compose = compose_command(bundle, PROJECT)

        def in_app(script: str) -> str:
            return sh(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script).stdout.strip()

        def in_backup(command: str) -> subprocess.CompletedProcess[str]:
            return sh(*compose, "run", "--rm", "--no-deps", "backup", "python", "/app/franca_backup.py", command, check=False)

        def in_backup_shell(script: str) -> subprocess.CompletedProcess[str]:
            # The repository's files belong to the backup container's user, so they are looked at from inside it.
            return sh(*compose, "run", "--rm", "--no-deps", "--entrypoint", "sh", "backup", "-c", script, check=False)

        count = (
            "import sqlite3; print(sqlite3.connect('/data/franca.db').execute('SELECT count(*) FROM identity_invitation').fetchone()[0])"
        )
        try:
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "app", "caddy", "socket-proxy", "updater")
            in_app(
                "import sqlite3; c = sqlite3.connect('/data/franca.db'); "
                'c.execute("INSERT INTO identity_invitation (email_norm, created_at, expires_at) '
                "VALUES ('kept@example.org', '2026-12-01T09:00:00.000Z', '2026-12-08T09:00:00.000Z')\"); c.commit()"
            )
            checks.check(in_app(count) == "1", "a row is written while the app runs")

            backed_up = in_backup("backup")
            checks.check(backed_up.returncode == 0, "the backup runs")
            tested = in_backup("restore-test")
            checks.check(tested.returncode == 0, "the restore test passes")
            report = json.loads(tested.stdout.strip().splitlines()[-1]) if tested.stdout.strip() else {}
            if tested.returncode != 0:
                print(f"info: {report}", flush=True)
            checks.check(bool(report.get("schema")), "the restore test reads the schema version of the restored database")
            checks.check(
                report.get("appVersion") == "1.0.0",
                "in the restore test, the app starts on the restored copy in a one-off container and its health check answers",
            )
            started = sh(*compose, "logs", "--no-color", "updater", check=False).stdout
            checks.check("restore-check-not-run" not in started, "the updater starts the one-off container without an error")
            left = in_backup_shell("ls -A /restore-test")
            checks.check(left.returncode == 0 and not left.stdout.strip(), "the restored copy is removed after the app check")
            without_updates = sh(
                *compose, "run", "--rm", "--no-deps", "-e", "FRANCA_PROFILES=backups", "backup", "python", "/app/franca_backup.py", "restore-test",
                check=False,
            )  # fmt: skip
            checks.check(
                without_updates.returncode == 0 and "updates profile, which is off" in without_updates.stdout,
                "with the updates profile off, the restore test passes without the app check and says so",
            )

            look = in_backup_shell("test -f /backups/restic/config && echo repository")
            checks.check("repository" in look.stdout, "the backup folder has a restic repository")
            plain = in_backup_shell("grep -rl 'SQLite format 3' /backups || true")
            checks.check(not plain.stdout.strip(), "no readable copy of the database is in the backup folder (it is encrypted)")

            refused = in_backup("restore-latest")
            checks.check(refused.returncode != 0 and "refused" in refused.stdout, "a restore is refused while the app is running")

            in_app("import sqlite3; c = sqlite3.connect('/data/franca.db'); c.execute('DELETE FROM identity_invitation'); c.commit()")
            checks.check(in_app(count) == "0", "the row is deleted")
            sh(*compose, "stop", "app")
            restored = in_backup("restore-latest")
            checks.check(restored.returncode == 0, "the latest backup is restored with the app stopped")
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "app")
            checks.check(in_app(count) == "1", "after the restore, the row is back")
            kept = in_app("import pathlib; print(len(list(pathlib.Path('/data').glob('franca-before-restore-*.db'))))")
            checks.check(kept == "1", "the database from before the restore is kept beside it")
        finally:
            tear_down(compose, show_logs=bool(checks.failures))
            # The files written by the backup container's user are removed by root in a container, so the temporary
            # folder can be removed.
            sh("docker", "run", "--rm", "--user", "0", "--entrypoint", "rm", "-v", f"{backups}:/b", BACKUP, "-rf", "/b/restic", check=False)
    return checks.exit_code()


if __name__ == "__main__":
    sys.exit(main())
