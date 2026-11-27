"""Recovery codes through the API (story E02-002)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from identity_helpers import OWNER_EMAIL, api_client, signed_in

from franca.api import recovery


@pytest.fixture
def client(database_path: Path) -> TestClient:
    return api_client(database_path)


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

    response = client.post("/api/v1/auth/recovery-code", json={"email": OWNER_EMAIL, "code": code})

    assert response.status_code == 200
    assert response.json() == {"displayName": "Nik", "role": "owner"}
    assert "__Host-franca_session=" in response.headers["set-cookie"]
    assert client.get("/api/v1/recovery-codes").json()["unused"] == 9


def test_a_wrong_code_is_refused_and_counted(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    code = client.post("/api/v1/recovery-codes").json()["codes"][0]
    client.cookies.clear()

    for _ in range(5):
        response = client.post("/api/v1/auth/recovery-code", json={"email": OWNER_EMAIL, "code": "AAAAA-AAAAA"})
        assert response.status_code == 401
        assert response.json() == {"detail": "recovery-code-not-accepted"}

    blocked = client.post("/api/v1/auth/recovery-code", json={"email": OWNER_EMAIL, "code": code})
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "too-many-attempts"}


def test_an_unknown_address_is_refused_like_a_wrong_code(client: TestClient) -> None:
    response = client.post("/api/v1/auth/recovery-code", json={"email": "nobody@example.org", "code": "AAAAA-AAAAA"})
    assert response.status_code == 401
    assert response.json() == {"detail": "recovery-code-not-accepted"}


def test_a_code_that_is_too_long_is_refused_before_it_is_checked(client: TestClient) -> None:
    response = client.post("/api/v1/auth/recovery-code", json={"email": OWNER_EMAIL, "code": "A" * 200})
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


def test_tries_older_than_the_window_are_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each address that is tried is counted. The counts for old tries are removed, because otherwise they would fill up
    # memory.
    clock = [1000.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: clock[0])
    limiter = recovery.AttemptLimiter(window_seconds=60)
    for number in range(100):
        limiter.record(("address", f"someone{number}@example.org"))
    assert len(limiter) == 100

    clock[0] += 61
    limiter.record(("address", "new@example.org"))

    assert len(limiter) == 1
    assert limiter.allow(("address", "someone1@example.org"), limit=1)
