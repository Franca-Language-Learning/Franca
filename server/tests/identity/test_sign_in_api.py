"""Sign-in with Google through the API, against a stand-in for Google (story E02-001).

The stand-in answers Google's discovery, token and key requests, and signs ID tokens with a test key, so the whole
OpenID Connect flow runs, including the checks of state, nonce, PKCE and the token signature.
"""

import base64
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from conftest import FrancaTestClient
from franca.api import create_app
from franca.platform import load_settings

CLIENT_ID = "test-client.apps.googleusercontent.com"
ISSUER = "https://accounts.google.com"
KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


class FakeGoogle:
    """Answers as Google does. The claims of the next ID token are in self.claims."""

    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.nonce = ""
        self.code_challenge = ""
        self.token_requests: list[dict[str, list[str]]] = []
        self.fail_token = False

    def authorize(self, location: str) -> dict[str, str]:
        query = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        self.nonce = query["nonce"]
        self.code_challenge = query["code_challenge"]
        return query

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if url == "https://www.googleapis.com/oauth2/v3/certs":
            return httpx2.Response(200, json={"keys": [KEY.as_dict(private=False)]})
        if url == "https://oauth2.googleapis.com/token":
            if self.fail_token:
                return httpx2.Response(502, text="<html>Bad gateway</html>")
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            now = int(time.time())
            claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 3600, "nonce": self.nonce, **self.claims}
            id_token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, KEY)
            return httpx2.Response(200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600, "id_token": id_token})
        return httpx2.Response(404)


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def client(database_path: Path, google: FakeGoogle) -> TestClient:
    settings = load_settings(
        {
            "FRANCA_DATABASE_PATH": str(database_path),
            "FRANCA_PUBLIC_URL": "https://franca.example.ts.net",
            "FRANCA_OWNER_EMAIL": "owner@example.org",
            "FRANCA_GOOGLE_CLIENT_ID": CLIENT_ID,
            "FRANCA_GOOGLE_CLIENT_SECRET": "test-secret",
            "FRANCA_SESSION_SECRET": "test-session-secret",
        }
    )
    app = create_app(settings, google_transport=httpx2.MockTransport(google.handler))
    return FrancaTestClient(app, base_url="https://franca.example.ts.net")


def sign_in(client: TestClient, google: FakeGoogle, **claims: Any) -> Any:
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert start.status_code == 302
    query = google.authorize(start.headers["location"])
    google.claims = {"sub": "owner-sub", "email": "owner@example.org", "email_verified": True, "name": "Owner", **claims}
    return client.get("/api/v1/auth/google/callback", params={"code": "the-code", "state": query["state"]}, follow_redirects=False)


def test_the_start_sends_the_browser_to_google_with_pkce_state_and_nonce(client: TestClient, google: FakeGoogle) -> None:
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    query = google.authorize(start.headers["location"])
    assert start.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == "https://franca.example.ts.net/api/v1/auth/google/callback"
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256"
    assert query["state"] and query["nonce"]


def test_the_owner_signs_in_and_gets_a_session_cookie(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google)
    assert finish.status_code == 303
    assert finish.headers["location"] == "/"
    cookie = finish.headers["set-cookie"]
    assert "franca_session=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert google.token_requests[0]["code_verifier"]
    me = client.get("/api/v1/me")
    assert me.json() == {"displayName": "Owner", "role": "owner"}


def test_a_stranger_is_sent_back_to_the_sign_in_page_with_the_reason(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, sub="stranger", email="stranger@example.org")
    assert finish.headers["location"] == "/sign-in?error=not-invited"
    assert "franca_session" not in finish.headers.get("set-cookie", "")
    assert client.get("/api/v1/me").status_code == 401


def test_an_unverified_address_is_refused(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, email_verified=False)
    assert finish.headers["location"] == "/sign-in?error=email-not-verified"


def test_a_callback_with_the_wrong_state_is_refused(client: TestClient, google: FakeGoogle) -> None:
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    google.authorize(start.headers["location"])
    google.claims = {"sub": "owner-sub", "email": "owner@example.org", "email_verified": True}
    finish = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_an_id_token_for_another_client_is_refused(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, aud="someone-elses-client")
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_an_id_token_for_another_audience_is_refused_even_with_our_client_as_azp(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, aud="evil-client", azp=CLIENT_ID)
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_an_id_token_from_another_issuer_is_refused(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, iss="https://evil.example")
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_the_code_verifier_matches_the_code_challenge(client: TestClient, google: FakeGoogle) -> None:
    sign_in(client, google)
    verifier = google.token_requests[0]["code_verifier"][0]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert google.code_challenge == expected


def test_an_error_at_googles_token_endpoint_ends_the_sign_in_with_a_reason(client: TestClient, google: FakeGoogle) -> None:
    google.fail_token = True
    finish = sign_in(client, google)
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_an_id_token_with_the_wrong_nonce_is_refused(client: TestClient, google: FakeGoogle) -> None:
    finish = sign_in(client, google, nonce="replayed")
    assert finish.headers["location"] == "/sign-in?error=failed"


def test_the_owner_invites_a_learner_who_can_then_sign_in(client: TestClient, google: FakeGoogle, database_path: Path) -> None:
    sign_in(client, google)
    created = client.post("/api/v1/invitations", json={"email": "partner@example.org"})
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert [i["email"] for i in client.get("/api/v1/invitations").json()["invitations"]] == ["partner@example.org"]

    partner = FrancaTestClient(client.app, base_url="https://franca.example.ts.net")
    finish = sign_in(partner, google, sub="partner-sub", email="partner@example.org", name="Partner")
    assert finish.headers["location"] == "/"
    assert partner.get("/api/v1/me").json() == {"displayName": "Partner", "role": "learner"}
    assert partner.post("/api/v1/invitations", json={"email": "friend@example.org"}).status_code == 403
    assert partner.get("/api/v1/invitations").status_code == 403


def test_an_invitation_needs_an_email_address(client: TestClient, google: FakeGoogle) -> None:
    sign_in(client, google)
    assert client.post("/api/v1/invitations", json={"email": "not an address"}).status_code == 422


def test_a_disabled_learners_open_session_stops_working(client: TestClient, google: FakeGoogle, database_path: Path) -> None:
    sign_in(client, google)
    with sqlite3.connect(database_path) as db:
        db.execute("UPDATE identity_learner SET role = 'learner' WHERE role = 'owner'")
        db.execute("UPDATE identity_learner SET status = 'disabled'")
    assert client.get("/api/v1/me").status_code == 401


def test_an_expired_session_stops_working(client: TestClient, google: FakeGoogle, database_path: Path) -> None:
    sign_in(client, google)
    with sqlite3.connect(database_path) as db:
        db.execute(
            "UPDATE identity_auth_session SET created_at = '2026-01-01T00:00:00.000Z', last_seen_at = '2026-01-01T00:00:00.000Z', expires_at = '2026-01-02T00:00:00.000Z'"
        )
    assert client.get("/api/v1/me").status_code == 401


def test_a_used_session_is_extended_in_the_browser_too(client: TestClient, google: FakeGoogle, database_path: Path) -> None:
    sign_in(client, google)
    with sqlite3.connect(database_path) as db:
        db.execute(
            "UPDATE identity_auth_session SET created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-2 hours'), "
            "last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-2 hours'), "
            "expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+29 days')"
        )
    me = client.get("/api/v1/me")
    assert "franca_session=" in me.headers["set-cookie"] and "Max-Age=2592000" in me.headers["set-cookie"]


def test_signing_in_again_closes_the_earlier_session(client: TestClient, google: FakeGoogle, database_path: Path) -> None:
    sign_in(client, google)
    sign_in(client, google)
    with sqlite3.connect(database_path) as db:
        open_sessions = db.execute("SELECT count(*) FROM identity_auth_session WHERE revoked_at IS NULL").fetchone()[0]
    assert open_sessions == 1


def test_signing_out_ends_the_session(client: TestClient, google: FakeGoogle) -> None:
    sign_in(client, google)
    assert client.post("/api/v1/auth/sign-out").status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_without_a_google_client_the_sign_in_routes_say_so(database_path: Path) -> None:
    app = create_app(load_settings({"FRANCA_DATABASE_PATH": str(database_path)}))
    response = TestClient(app).get("/api/v1/auth/google/start", follow_redirects=False)
    assert response.status_code == 503
    assert json.loads(response.text)["detail"] == "Sign-in with Google is not configured"
