"""Adding passkeys and signing in with them through the API (story E02-001)."""

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from identity_helpers import ORIGIN, SESSION_COOKIE_NAME, api_client, signed_in
from passkey_device import PasskeyDevice
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from franca import identity
from franca.platform import db, utc_now


@pytest.fixture
def client(database_path: Path) -> TestClient:
    return api_client(database_path)


def add_passkey(client: TestClient, device: PasskeyDevice, label: str = "Phone") -> Any:
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    return client.post("/api/v1/passkeys", json={"credential": device.register(options), "label": label})


def sign_in(client: TestClient, device: PasskeyDevice, **answer: Any) -> Any:
    options = client.post("/api/v1/auth/passkey/options").json()["publicKey"]
    return client.post("/api/v1/auth/passkey", json={"credential": device.sign_in(options, **answer)})


def test_adding_a_passkey_needs_a_signed_in_learner(client: TestClient) -> None:
    assert client.post("/api/v1/passkeys/options").status_code == 401
    assert client.post("/api/v1/passkeys", json={"credential": {}}).status_code == 401
    assert client.get("/api/v1/passkeys").status_code == 401


def test_a_learner_adds_a_passkey_and_sees_it_in_the_list(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)

    added = add_passkey(client, device)

    assert added.status_code == 201
    body = added.json()
    assert body["label"] == "Phone" and body["synced"] is True and body["lastUsedAt"] is None
    assert client.get("/api/v1/passkeys").json() == {"passkeys": [body]}


def test_the_registration_options_are_for_this_site(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    assert options["rp"]["id"] == "franca.example.ts.net"
    assert options["user"]["displayName"] == "Nik"


def test_a_passkey_answer_without_options_first_is_refused(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    answer = device.register(options)
    client.cookies.delete("franca_oauth")  # the challenge is kept in this cookie

    response = client.post("/api/v1/passkeys", json={"credential": answer})

    assert response.status_code == 400
    assert client.get("/api/v1/passkeys").json() == {"passkeys": []}


def test_a_registration_answer_is_used_once(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    answer = device.register(options)

    assert client.post("/api/v1/passkeys", json={"credential": answer}).status_code == 201
    assert client.post("/api/v1/passkeys", json={"credential": answer}).status_code == 400


def test_a_registration_answer_that_fails_the_checks_is_refused(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    answer = PasskeyDevice(ORIGIN).register(options, origin="https://evil.example")

    response = client.post("/api/v1/passkeys", json={"credential": answer})

    assert response.status_code == 400
    assert response.json() == {"detail": "passkey-not-accepted"}


def test_a_learner_signs_in_with_a_passkey(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    client.post("/api/v1/auth/sign-out")
    client.cookies.clear()
    assert client.get("/api/v1/me").status_code == 401

    response = sign_in(client, device)

    assert response.status_code == 200
    assert response.json() == {"displayName": "Nik", "role": "owner"}
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in cookie and "HttpOnly" in cookie and "Secure" in cookie
    assert client.get("/api/v1/me").json()["role"] == "owner"


def test_signing_in_with_a_passkey_ends_the_earlier_session_in_this_browser(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    earlier = client.cookies.get(SESSION_COOKIE_NAME)

    sign_in(client, device)

    engine = db.make_engine(database_path)
    with engine.begin() as connection:
        assert identity.learner_for_session(connection, str(earlier), utc_now()) is None
    engine.dispose()


def test_a_sign_in_answer_is_used_once(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    client.cookies.clear()
    options = client.post("/api/v1/auth/passkey/options").json()["publicKey"]
    answer = device.sign_in(options)

    assert client.post("/api/v1/auth/passkey", json={"credential": answer}).status_code == 200
    client.cookies.delete(SESSION_COOKIE_NAME)
    assert client.post("/api/v1/auth/passkey", json={"credential": answer}).status_code == 400


def test_an_unknown_passkey_is_refused(client: TestClient) -> None:
    response = sign_in(client, PasskeyDevice(ORIGIN))
    assert response.status_code == 401
    assert response.json() == {"detail": "passkey-unknown"}
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_a_registration_challenge_cannot_be_used_to_sign_in(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]

    response = client.post(
        "/api/v1/auth/passkey", json={"credential": device.sign_in({"rpId": "franca.example.ts.net", "challenge": options["challenge"]})}
    )

    assert response.status_code == 400


def test_a_disabled_learner_is_refused(client: TestClient, database_path: Path) -> None:
    learner = signed_in(client, database_path, subject="g-l", email="learner@example.org")
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    engine = db.make_engine(database_path)
    with engine.begin() as connection:
        connection.execute(text("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = :id"), {"id": learner.learner_id})
    engine.dispose()
    client.cookies.clear()

    response = sign_in(client, device)

    assert response.status_code == 401
    assert response.json() == {"detail": "disabled"}


def test_a_learner_removes_a_passkey(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    passkey_id = add_passkey(client, PasskeyDevice(ORIGIN)).json()["id"]

    assert client.delete(f"/api/v1/passkeys/{passkey_id}").status_code == 204
    assert client.get("/api/v1/passkeys").json() == {"passkeys": []}
    assert client.delete(f"/api/v1/passkeys/{passkey_id}").status_code == 404


def test_a_label_longer_than_60_characters_is_refused(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path)
    response = add_passkey(client, PasskeyDevice(ORIGIN), label="x" * 61)
    assert response.status_code == 422


def test_a_sign_in_answer_cannot_be_replayed_with_the_earlier_cookie(client: TestClient, database_path: Path) -> None:
    # The challenge is kept on the server, so a copy of the cookie from before the sign-in does not bring it back.
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    client.cookies.clear()
    options = client.post("/api/v1/auth/passkey/options").json()["publicKey"]
    copied = client.cookies.get("franca_oauth")
    answer = device.sign_in(options)
    assert client.post("/api/v1/auth/passkey", json={"credential": answer}).status_code == 200

    client.cookies.clear()
    client.cookies.set("franca_oauth", str(copied))
    assert client.post("/api/v1/auth/passkey", json={"credential": answer}).status_code == 400


def test_a_challenge_expires_after_five_minutes(client: TestClient, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    signed_in(client, database_path)
    device = PasskeyDevice(ORIGIN)
    add_passkey(client, device)
    options = client.post("/api/v1/auth/passkey/options").json()["publicKey"]
    later = time.monotonic() + 301
    monkeypatch.setattr(time, "monotonic", lambda: later)
    assert client.post("/api/v1/auth/passkey", json={"credential": device.sign_in(options)}).status_code == 400


def test_adding_a_passkey_needs_a_recent_sign_in(client: TestClient, database_path: Path) -> None:
    # Someone with a stolen session cookie cannot add a passkey of their own and keep a way in.
    signed_in(client, database_path, minutes_ago=20)
    response = client.post("/api/v1/passkeys/options")
    assert response.status_code == 403
    assert response.json() == {"detail": "sign-in-again"}
    assert client.get("/api/v1/passkeys").status_code == 200


def test_a_busy_database_gives_a_503_and_not_a_500(client: TestClient, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    signed_in(client, database_path)

    def busy(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT", {}, Exception("database is locked"))

    monkeypatch.setattr(identity, "list_passkeys", busy)
    response = client.get("/api/v1/passkeys")
    assert response.status_code == 503
