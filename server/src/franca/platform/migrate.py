"""Upgrades the database to the newest schema:  python -m franca.platform.migrate

The database is the file named in FRANCA_DATABASE_PATH. This is run each time the app container starts, before the
service starts. When the updater installs a release, it takes a snapshot of the database first, so the database can be put
back if the new release does not start (infra/updater/franca_updater.py).
"""

from franca.platform.db import upgrade
from franca.platform.settings import load_settings


def main() -> None:
    settings = load_settings()
    upgrade(settings.database_path)
    print(f"The database at {settings.database_path} is up to date.")


if __name__ == "__main__":
    main()
