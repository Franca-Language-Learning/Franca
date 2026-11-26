"""The list of signed-in devices and signing out through the API (story E02-003)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from passkey_device import PasskeyDevice

from conftest import FrancaTestClient
from franca import identity
from franca.api import create_app
from franca.platform import db, load_settings, utc_now

ORIGIN = "https://franca.example.ts.net"
LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


@pytest.fixture
def client(database_path: Path) -> TestClient:
    settings = load_settings({"FRANCA_DATABASE_PATH": str(database_path), "FRANCA_PUBLIC_URL": ORIGIN, "FRANCA_SESSION_SECRET": "x" * 32})
    return FrancaTestClient(create_app(settings), base_url=ORIGIN, headers={"user-agent": LAPTOP})


def new_session(database_path: Path, agent: str = LAPTOP) -> str:
    engine = db.make_engine(database_path)
    with engine.begin() as connection:
        owner = identity.sign_in_with_google(
            connection,
            subject="g-owner",
            email="owner@example.org",
            email_verified=True,
            name="Nik",
            owner_email="owner@example.org",
            now=utc_now(),
        )
        token = identity.start_session(connection, owner, agent, utc_now())
    engine.dispose()
    return token


def test_the_devices_need_a_signed_in_learner(client: TestClient) -> None:
    assert client.get("/api/v1/sessions").status_code == 401


def test_a_learner_sees_their_devices_and_which_one_this_is(client: TestClient, database_path: Path) -> None:
    client.cookies.set("__Host-franca_session", new_session(database_path))
    new_session(database_path, "Mozilla/5.0 (Linux; Android 15) Chrome/140.0 Mobile Safari/537.36")

    sessions = client.get("/api/v1/sessions").json()["sessions"]

    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1 and current[0]["browser"] == "Chrome on Windows" and current[0]["deviceKind"] == "desktop"
    assert {s["browser"] for s in sessions} == {"Chrome on Windows", "Chrome on Android"}


def test_a_learner_signs_out_another_device(client: TestClient, database_path: Path) -> None:
    client.cookies.set("__Host-franca_session", new_session(database_path))
    phone = new_session(database_path, "Mozilla/5.0 (iPhone) Safari/604.1")
    phone_id = next(s["id"] for s in client.get("/api/v1/sessions").json()["sessions"] if not s["current"])

    assert client.delete(f"/api/v1/sessions/{phone_id}").status_code == 204
    assert client.delete(f"/api/v1/sessions/{phone_id}").status_code == 404

    other = FrancaTestClient(client.app, base_url=ORIGIN)
    other.cookies.set("__Host-franca_session", phone)
    assert other.get("/api/v1/me").status_code == 401


def test_a_learner_signs_out_on_all_other_devices(client: TestClient, database_path: Path) -> None:
    client.cookies.set("__Host-franca_session", new_session(database_path))
    for _ in range(3):
        new_session(database_path)

    response = client.post("/api/v1/sessions/sign-out-others")

    assert response.status_code == 200
    assert response.json() == {"signedOut": 3}
    assert [s["current"] for s in client.get("/api/v1/sessions").json()["sessions"]] == [True]


def test_removing_a_passkey_signs_out_the_devices_that_used_it(client: TestClient, database_path: Path) -> None:
    client.cookies.set("__Host-franca_session", new_session(database_path))
    device = PasskeyDevice(ORIGIN)
    options = client.post("/api/v1/passkeys/options").json()["publicKey"]
    passkey_id = client.post("/api/v1/passkeys", json={"credential": device.register(options)}).json()["id"]

    phone = FrancaTestClient(client.app, base_url=ORIGIN)
    sign_in_options = phone.post("/api/v1/auth/passkey/options").json()["publicKey"]
    assert phone.post("/api/v1/auth/passkey", json={"credential": device.sign_in(sign_in_options)}).status_code == 200
    assert phone.get("/api/v1/me").status_code == 200

    assert client.delete(f"/api/v1/passkeys/{passkey_id}").status_code == 204

    assert phone.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me").status_code == 200
