"""The list of signed-in devices and signing out through the API (story E02-003)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from identity_helpers import ORIGIN, SESSION_COOKIE_NAME, api_client, new_session, signed_in
from passkey_device import PasskeyDevice

from conftest import FrancaTestClient

LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


@pytest.fixture
def client(database_path: Path) -> TestClient:
    return api_client(database_path, user_agent=LAPTOP)


def test_the_devices_need_a_signed_in_learner(client: TestClient) -> None:
    assert client.get("/api/v1/sessions").status_code == 401


def test_a_learner_sees_their_devices_and_which_one_this_is(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path, agent=LAPTOP)
    new_session(database_path, agent="Mozilla/5.0 (Linux; Android 15) Chrome/140.0 Mobile Safari/537.36")

    sessions = client.get("/api/v1/sessions").json()["sessions"]

    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1 and current[0]["browser"] == "Chrome on Windows" and current[0]["deviceKind"] == "desktop"
    assert {s["browser"] for s in sessions} == {"Chrome on Windows", "Chrome on Android"}


def test_a_learner_signs_out_another_device(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path, agent=LAPTOP)
    phone = new_session(database_path, agent="Mozilla/5.0 (iPhone) Safari/604.1")[1]
    phone_id = next(s["id"] for s in client.get("/api/v1/sessions").json()["sessions"] if not s["current"])

    assert client.delete(f"/api/v1/sessions/{phone_id}").status_code == 204
    assert client.delete(f"/api/v1/sessions/{phone_id}").status_code == 404

    other = FrancaTestClient(client.app, base_url=ORIGIN)
    other.cookies.set(SESSION_COOKIE_NAME, phone)
    assert other.get("/api/v1/me").status_code == 401


def test_a_learner_signs_out_on_all_other_devices(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path, agent=LAPTOP)
    for _ in range(3):
        new_session(database_path, agent=LAPTOP)

    response = client.post("/api/v1/sessions/sign-out-others")

    assert response.status_code == 200
    assert response.json() == {"signedOut": 3}
    assert [s["current"] for s in client.get("/api/v1/sessions").json()["sessions"]] == [True]


def test_removing_a_passkey_signs_out_the_devices_that_used_it(client: TestClient, database_path: Path) -> None:
    signed_in(client, database_path, agent=LAPTOP)
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
