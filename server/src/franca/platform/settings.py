"""Settings read from the environment when the service starts.

The container image sets FRANCA_VERSION at build time. Secrets are not read here: they come from files that
Docker mounts under /run/secrets, read by the module that needs them.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    version: str
    environment: str
    database_path: str


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    return Settings(
        version=env.get("FRANCA_VERSION", "0.1.0-dev"),
        environment=env.get("FRANCA_ENVIRONMENT", "development"),
        database_path=env.get("FRANCA_DATABASE_PATH", "franca.db"),
    )
