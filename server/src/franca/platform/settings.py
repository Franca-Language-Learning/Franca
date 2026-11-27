"""Settings read from the environment when the service starts.

FRANCA_VERSION is given in the container image at build time. Secrets are read from files that Docker mounts under
/run/secrets; the variable names the file (for example FRANCA_GOOGLE_CLIENT_SECRET_FILE). For development, the
secret itself can be given in the variable without _FILE.
"""

import os
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GoogleSignIn:
    client_id: str
    client_secret: str


@dataclass(frozen=True, slots=True)
class Settings:
    version: str
    environment: str
    database_path: str
    # The address learners use, such as https://franca.example.ts.net. Sign-in redirects go back to it.
    public_url: str
    # The Google account with this e-mail address becomes the owner when it first signs in.
    owner_email: str | None
    google: GoogleSignIn | None
    # The secret for the short-lived cookie with the state of a sign-in with Google.
    session_secret: str | None

    @property
    def cookies_secure(self) -> bool:
        return self.public_url.startswith("https://")


def _secret(env: Mapping[str, str], name: str) -> str | None:
    file = env.get(f"{name}_FILE")
    if file:
        return Path(file).read_text(encoding="utf-8").strip() or None
    return env.get(name) or None


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env: Mapping[str, str] = os.environ if environ is None else environ
    client_id = env.get("FRANCA_GOOGLE_CLIENT_ID")
    client_secret = _secret(env, "FRANCA_GOOGLE_CLIENT_SECRET")
    return Settings(
        version=env.get("FRANCA_VERSION", "0.1.0-dev"),
        environment=env.get("FRANCA_ENVIRONMENT", "development"),
        database_path=env.get("FRANCA_DATABASE_PATH", "franca.db"),
        public_url=env.get("FRANCA_PUBLIC_URL", "http://localhost:8080").rstrip("/"),
        owner_email=unicodedata.normalize("NFC", (env.get("FRANCA_OWNER_EMAIL") or "").strip()).casefold() or None,
        google=GoogleSignIn(client_id, client_secret) if client_id and client_secret else None,
        session_secret=_secret(env, "FRANCA_SESSION_SECRET"),
    )
