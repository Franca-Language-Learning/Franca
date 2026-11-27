"""Helpers for the identity tests:

- a learner signed in with Google
- a sign-in session written straight to the database
- the API test client for Franca on its https address
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Connection

from conftest import FrancaTestClient
from franca import identity
from franca.api import create_app
from franca.api.dependencies import SESSION_COOKIE, cookie_name
from franca.platform import db, load_settings, utc_now

ORIGIN = "https://franca.example.ts.net"
OWNER_EMAIL = "owner@example.org"
# The session cookie's name over https, where the tests reach the app.
SESSION_COOKIE_NAME = cookie_name(SESSION_COOKIE, secure=True)
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


def sign_in(connection: Connection, subject: str = "g-owner", email: str = OWNER_EMAIL, *, now: datetime = NOW) -> identity.Learner:
    """Signs in with a Google account whose address Google has verified. The account with OWNER_EMAIL becomes the owner.
    Another address needs an invitation first."""
    return identity.sign_in_with_google(
        connection, subject=subject, email=email, email_verified=True, name="Nik", owner_email=OWNER_EMAIL, now=now
    )


def api_client(database_path: Path, user_agent: str | None = None) -> FrancaTestClient:
    """A test client for the app on its https address, with the database at database_path."""
    settings = load_settings({"FRANCA_DATABASE_PATH": str(database_path), "FRANCA_PUBLIC_URL": ORIGIN, "FRANCA_SESSION_SECRET": "x" * 32})
    headers = {"user-agent": user_agent} if user_agent else None
    return FrancaTestClient(create_app(settings), base_url=ORIGIN, headers=headers)


def new_session(
    database_path: Path, *, subject: str = "g-owner", email: str = OWNER_EMAIL, agent: str = "pytest", minutes_ago: int = 0
) -> tuple[identity.Learner, str]:
    """Signs a learner in and starts a session, in the same way as a sign-in with Google. Returns the learner and the
    session token. A learner other than the owner is invited by the owner first. With minutes_ago, the sign-in is that
    many minutes in the past."""
    engine = db.make_engine(database_path)
    with engine.begin() as connection:
        if email != OWNER_EMAIL:
            identity.invite(connection, sign_in(connection, now=utc_now()), email, utc_now())
        learner = sign_in(connection, subject, email, now=utc_now())
        token = identity.start_session(connection, learner, agent, utc_now() - timedelta(minutes=minutes_ago))
    engine.dispose()
    return learner, token


def signed_in(
    client: TestClient,
    database_path: Path,
    *,
    subject: str = "g-owner",
    email: str = OWNER_EMAIL,
    agent: str = "pytest",
    minutes_ago: int = 0,
) -> identity.Learner:
    """Starts a session (see new_session) and gives its cookie to the client. Returns the learner."""
    learner, token = new_session(database_path, subject=subject, email=email, agent=agent, minutes_ago=minutes_ago)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return learner
