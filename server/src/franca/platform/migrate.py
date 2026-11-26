"""Upgrades the database to the newest schema:  python -m franca.platform.migrate

The database is the file named in FRANCA_DATABASE_PATH. The updater runs this after taking a snapshot (story E01-007).
"""

from franca.platform.db import upgrade
from franca.platform.settings import load_settings


def main() -> None:
    settings = load_settings()
    upgrade(settings.database_path)
    print(f"The database at {settings.database_path} is up to date.")


if __name__ == "__main__":
    main()
