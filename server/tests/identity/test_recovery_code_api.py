"""Recovery codes through the API (story E02-002)."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franca import identity
from franca.api import create_app
from franca.platform import db, load_settings, utc_now

ORIGIN = "https://franca.example.ts.net"
EMAIL = "owner@example.org"


@pytest.fixture
def client(database_path: Path) -> TestClient:
    settings = load_settings({"FRANCA_DATABASE_PATH": str(database_path), "FRANCA_PUBLIC_URL": ORIGIN, "FRANCA_SESSION_SECRET": "x" * 32})
    return TestClient(create_app(settings), base_url=ORIGIN)


def signed_in(client: TestClient, database_path: Path, minutes_ago: int = 0) -> None:
    engine = db.make_engine(database_path)
    with engine.begin() as connection:
        learner = identity.sign_in_with_google(
            connection, subject="g-owner", email=EMAIL, email_verified=True, name="Nik", owner_email=EMAIL, now=utc_now()
        )
        token = identity.start_session(connection, learner, "pytest", utc_now() - timedelta(minutes=minutes_ago))
    engine.dispose()
    client.cookies.set("franca_session", token)


def test_the_codes_need_a_signed_in_learner(client: TestClient) -> None:
    assert client.get("/api/v1/recovery-codes").status_code == 401
    assert client.post("/api/v1/recovery-codes").status_code == 401


def test_a_learner_makes_codes_and_sees_how_many_are_left(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    assert client.get("/api/v1/recovery-codes").json() == {"unused": 0, "createdAt": None}

    made = client.post("/api/v1/recovery-codes")

    assert made.status_code == 201
    assert made.headers["cache-control"] == "no-store"
    codes = made.json()["codes"]
    assert len(codes) == 10
    status = client.get("/api/v1/recovery-codes").json()
    assert status["unused"] == 10 and status["createdAt"]


def test_making_codes_needs_a_recent_sign_in(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path, minutes_ago=20)
    response = client.post("/api/v1/recovery-codes")
    assert response.status_code == 403
    assert response.json() == {"detail": "sign-in-again"}


def test_a_learner_signs_in_with_a_code(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    code = client.post("/api/v1/recovery-codes").json()["codes"][0]
    client.cookies.clear()

    response = client.post("/api/v1/auth/recovery-code", json={"email": EMAIL, "code": code})

    assert response.status_code == 200
    assert response.json() == {"displayName": "Nik", "role": "owner"}
    assert "franca_session=" in response.headers["set-cookie"]
    assert client.get("/api/v1/recovery-codes").json()["unused"] == 9


def test_a_wrong_code_is_refused_and_counted(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    code = client.post("/api/v1/recovery-codes").json()["codes"][0]
    client.cookies.clear()

    for _ in range(5):
        response = client.post("/api/v1/auth/recovery-code", json={"email": EMAIL, "code": "AAAAA-AAAAA"})
        assert response.status_code == 401
        assert response.json() == {"detail": "recovery-code-not-accepted"}

    blocked = client.post("/api/v1/auth/recovery-code", json={"email": EMAIL, "code": code})
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "too-many-attempts"}


def test_an_unknown_address_is_refused_like_a_wrong_code(client: TestClient) -> None:
    response = client.post("/api/v1/auth/recovery-code", json={"email": "nobody@example.org", "code": "AAAAA-AAAAA"})
    assert response.status_code == 401
    assert response.json() == {"detail": "recovery-code-not-accepted"}


def test_a_code_that_is_too_long_is_refused_before_it_is_checked(client: TestClient) -> None:
    response = client.post("/api/v1/auth/recovery-code", json={"email": EMAIL, "code": "A" * 200})
    assert response.status_code == 422


def test_one_computer_gets_ten_tries_in_15_minutes_whatever_the_address(client: TestClient) -> None:
    for n in range(10):
        response = client.post("/api/v1/auth/recovery-code", json={"email": f"guess{n}@example.org", "code": "AAAAA-AAAAA"})
        assert response.status_code == 401
    response = client.post("/api/v1/auth/recovery-code", json={"email": "guess@example.org", "code": "AAAAA-AAAAA"})
    assert response.status_code == 429
    assert response.json() == {"detail": "too-many-attempts"}


def test_a_sign_in_that_is_not_sent_as_json_is_refused(client: TestClient) -> None:
    # A form or a beacon from another site cannot send JSON without the browser asking first (CORS), so this stops
    # another site from signing the browser in to someone else's account.
    response = client.post(
        "/api/v1/auth/recovery-code", content=b'{"email": "a@example.org", "code": "AAAAA-AAAAA"}', headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
