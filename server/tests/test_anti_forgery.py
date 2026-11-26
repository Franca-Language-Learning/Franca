"""Protection against forged requests (story E02-003).

A request that changes something has to carry the anti-forgery token from the franca_csrf cookie in the
X-CSRF-Token header. Another site can make the browser send a request, but it cannot read the cookie, so it cannot
copy the token into the header (the double-submit pattern). The session cookie is SameSite=Strict as well.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franca.api import create_app
from franca.platform import load_settings

ORIGIN = "https://franca.example.ts.net"


@pytest.fixture
def client(database_path: Path) -> TestClient:
    settings = load_settings({"FRANCA_DATABASE_PATH": str(database_path), "FRANCA_PUBLIC_URL": ORIGIN, "FRANCA_SESSION_SECRET": "x" * 32})
    return TestClient(create_app(settings), base_url=ORIGIN)


def test_any_api_answer_gives_the_browser_a_token_cookie(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    cookie = response.headers["set-cookie"]
    assert "__Host-franca_csrf=" in cookie and "SameSite=strict" in cookie and "Secure" in cookie and "HttpOnly" not in cookie
    assert len(client.cookies["__Host-franca_csrf"]) >= 32


def test_the_token_cookie_is_given_once(client: TestClient) -> None:
    client.get("/api/v1/health")
    assert "franca_csrf" not in client.get("/api/v1/health").headers.get("set-cookie", "")


def test_a_change_without_the_token_is_refused(client: TestClient) -> None:
    client.get("/api/v1/health")
    response = client.post("/api/v1/auth/sign-out")
    assert response.status_code == 403
    assert response.json() == {"detail": "anti-forgery-token-missing"}


def test_a_change_with_a_token_that_does_not_match_the_cookie_is_refused(client: TestClient) -> None:
    client.get("/api/v1/health")
    response = client.post("/api/v1/auth/sign-out", headers={"X-CSRF-Token": "a" * 43})
    assert response.status_code == 403
    assert response.json() == {"detail": "anti-forgery-token-wrong"}


def test_a_change_without_a_cookie_is_refused_even_with_a_header(client: TestClient) -> None:
    response = client.post("/api/v1/auth/sign-out", headers={"X-CSRF-Token": "a" * 43})
    assert response.status_code == 403


def test_a_change_with_the_token_is_accepted(client: TestClient) -> None:
    client.get("/api/v1/health")
    response = client.post("/api/v1/auth/sign-out", headers={"X-CSRF-Token": client.cookies["__Host-franca_csrf"]})
    assert response.status_code == 204


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_kind_of_change_needs_the_token(client: TestClient, method: str) -> None:
    client.get("/api/v1/health")
    response = client.request(method.upper(), "/api/v1/passkeys/some-id")
    assert response.status_code == 403


def test_a_change_that_the_browser_marks_as_from_another_site_is_refused(client: TestClient) -> None:
    # Another computer in the same tailnet is the same site, but not the same origin.
    client.get("/api/v1/health")
    token = client.cookies["__Host-franca_csrf"]
    for site in ("same-site", "cross-site"):
        response = client.post("/api/v1/auth/sign-out", headers={"X-CSRF-Token": token, "Sec-Fetch-Site": site})
        assert response.status_code == 403
        assert response.json() == {"detail": "cross-site-request"}
    assert client.post("/api/v1/auth/sign-out", headers={"X-CSRF-Token": token, "Sec-Fetch-Site": "same-origin"}).status_code == 204


def test_the_token_is_found_after_a_cookie_that_another_parser_would_stop_at(client: TestClient) -> None:
    client.get("/api/v1/health")
    token = client.cookies["__Host-franca_csrf"]
    raw = TestClient(client.app, base_url=ORIGIN)
    response = raw.post(
        "/api/v1/auth/sign-out", headers={"X-CSRF-Token": token, "Cookie": f'x=a b; other={{"a":1}}; __Host-franca_csrf={token}'}
    )
    assert response.status_code == 204


def test_over_http_the_cookie_has_no_prefix(database_path: Path) -> None:
    settings = load_settings({"FRANCA_DATABASE_PATH": str(database_path), "FRANCA_PUBLIC_URL": "http://localhost:8080"})
    plain = TestClient(create_app(settings))
    cookie = plain.get("/api/v1/health").headers["set-cookie"]
    assert cookie.startswith("franca_csrf=") and "Secure" not in cookie


def test_a_change_outside_the_api_needs_the_token_too(client: TestClient) -> None:
    client.get("/api/v1/health")
    assert client.post("/some/other/path").status_code == 403
