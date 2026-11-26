"""A rehearsal of the backup with real containers (story E01-008). Run from the repository root:
    python3 infra/tests/rehearse_backup.py

It needs Docker with Compose and builds the images itself. A temporary folder stands in for disk J:.

The rehearsal:
1. starts the app and writes a row to the database;
2. runs a backup in the backup container, then the monthly restore test;
3. checks that the backup folder has an encrypted restic repository and no readable copy of the database;
4. deletes the row, stops the app, restores the latest backup and starts the app again; the row has to be back, and
   the database from before the restore has to be kept beside it;
5. checks that a restore is refused while the app is running.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = f"franca-backup-rehearsal-{os.getpid()}"
APP = "franca/app:rehearsal-backup"
CADDY = "franca/caddy:rehearsal-backup"
BACKUP = "franca/backup:rehearsal"


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
    sh("docker", "build", "--quiet", "-f", "infra/images/backup.Dockerfile", "-t", BACKUP, ".")
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        bundle = Path(folder)
        (bundle / "compose.yaml").write_text((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        secrets = bundle / "secrets"
        secrets.mkdir()
        for name in ("google_client_secret", "session_secret", "backup_password"):
            (secrets / name).write_text("" if name == "google_client_secret" else os.urandom(32).hex(), encoding="utf-8")
            (secrets / name).chmod(0o644)
        backups = bundle / "disk-j"
        backups.mkdir()
        backups.chmod(0o777)  # the backup container's user (10001) writes here, as it will on disk J:
        (backups / ".franca-backup-disk").write_text("Franca backups\n", encoding="utf-8")  # the installer puts this here
        port = free_port()
        (bundle / ".env").write_text(
            "\n".join(
                [
                    "FRANCA_VERSION=1.0.0",
                    f"FRANCA_APP_IMAGE={APP}",
                    f"FRANCA_CADDY_IMAGE={CADDY}",
                    f"FRANCA_BACKUP_IMAGE={BACKUP}",
                    f"FRANCA_PORT={port}",
                    f"FRANCA_SECRETS_DIR={secrets}",
                    f"FRANCA_BACKUP_DIR={backups}",
                    "COMPOSE_PROFILES=backups",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        compose = ["docker", "compose", "--project-directory", str(bundle), "--project-name", PROJECT]

        def in_app(script: str) -> str:
            return sh(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "app", "-c", script).stdout.strip()

        def in_backup(command: str) -> subprocess.CompletedProcess[str]:
            return sh(*compose, "run", "--rm", "--no-deps", "backup", "python", "/app/franca_backup.py", command, check=False)

        count = (
            "import sqlite3; print(sqlite3.connect('/data/franca.db').execute('SELECT count(*) FROM identity_invitation').fetchone()[0])"
        )
        try:
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "app", "caddy")
            in_app(
                "import sqlite3; c = sqlite3.connect('/data/franca.db'); "
                'c.execute("INSERT INTO identity_invitation (email_norm, created_at, expires_at) '
                "VALUES ('kept@example.org', '2026-12-01T09:00:00.000Z', '2026-12-08T09:00:00.000Z')\"); c.commit()"
            )
            check(in_app(count) == "1", "a row is written while the app runs", failures)

            backed_up = in_backup("backup")
            check(backed_up.returncode == 0, "the backup runs", failures)
            tested = in_backup("restore-test")
            check(tested.returncode == 0, "the restore test passes", failures)
            report = json.loads(tested.stdout.strip().splitlines()[-1]) if tested.stdout.strip() else {}
            check(bool(report.get("schema")), "the restore test reads the schema version of the restored database", failures)

            # The repository's files belong to the backup container's user, so they are looked at from inside it.
            look = sh(
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "sh",
                "backup",
                "-c",
                "test -f /backups/restic/config && echo repository",
                check=False,
            )
            check("repository" in look.stdout, "the backup folder has a restic repository", failures)
            plain = sh(
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "sh",
                "backup",
                "-c",
                "grep -rl 'SQLite format 3' /backups || true",
                check=False,
            )
            check(not plain.stdout.strip(), "no readable copy of the database is in the backup folder (it is encrypted)", failures)

            refused = in_backup("restore-latest")
            check(refused.returncode != 0 and "refused" in refused.stdout, "a restore is refused while the app is running", failures)

            in_app("import sqlite3; c = sqlite3.connect('/data/franca.db'); c.execute('DELETE FROM identity_invitation'); c.commit()")
            check(in_app(count) == "0", "the row is deleted", failures)
            sh(*compose, "stop", "app")
            restored = in_backup("restore-latest")
            check(restored.returncode == 0, "the latest backup is restored with the app stopped", failures)
            sh(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "120", "app")
            check(in_app(count) == "1", "after the restore, the row is back", failures)
            kept = in_app("import pathlib; print(len(list(pathlib.Path('/data').glob('franca-before-restore-*.db'))))")
            check(kept == "1", "the database from before the restore is kept beside it", failures)
        finally:
            if failures:
                print(sh(*compose, "logs", "--no-color", "--tail", "60", check=False).stdout)
            sh(*compose, "down", "--volumes", "--remove-orphans", check=False)
            # The files written by the backup container's user are removed by root in a container, so the temporary
            # folder can be removed.
            sh("docker", "run", "--rm", "--user", "0", "--entrypoint", "rm", "-v", f"{backups}:/b", BACKUP, "-rf", "/b/restic", check=False)
    if failures:
        print(f"\nThe rehearsal failed: {len(failures)} check(s).")
        return 1
    print("\nThe rehearsal passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
