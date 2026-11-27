"""Settings read from the environment when the service starts (franca.platform.settings)."""

from pathlib import Path

from franca.platform import load_settings


def test_a_secret_is_read_from_the_file_that_its_file_variable_names(tmp_path: Path) -> None:
    # In the bundle, Docker mounts each secret as a file under /run/secrets, and a variable ending in _FILE has the path
    # of that file.
    secret = tmp_path / "session_secret"
    secret.write_text("from-the-file\n", encoding="utf-8")

    settings = load_settings({"FRANCA_SESSION_SECRET_FILE": str(secret), "FRANCA_SESSION_SECRET": "from-the-variable"})

    assert settings.session_secret == "from-the-file"  # noqa: S105 - a made-up value for the test


def test_an_empty_secret_file_counts_as_no_secret(tmp_path: Path) -> None:
    secret = tmp_path / "google_client_secret"
    secret.write_text("\n", encoding="utf-8")

    settings = load_settings({"FRANCA_GOOGLE_CLIENT_ID": "client", "FRANCA_GOOGLE_CLIENT_SECRET_FILE": str(secret)})

    assert settings.google is None


def test_google_sign_in_needs_both_the_client_id_and_the_secret() -> None:
    assert load_settings({"FRANCA_GOOGLE_CLIENT_ID": "client"}).google is None
    google = load_settings({"FRANCA_GOOGLE_CLIENT_ID": "client", "FRANCA_GOOGLE_CLIENT_SECRET": "secret"}).google
    assert google is not None
    assert (google.client_id, google.client_secret) == ("client", "secret")


def test_the_owner_address_is_compared_in_its_stored_form() -> None:
    assert load_settings({"FRANCA_OWNER_EMAIL": "  Owner@Example.ORG "}).owner_email == "owner@example.org"
    assert load_settings({}).owner_email is None


def test_the_public_address_has_no_trailing_slash_and_decides_whether_cookies_are_secure() -> None:
    https = load_settings({"FRANCA_PUBLIC_URL": "https://franca.example.ts.net/"})
    assert https.public_url == "https://franca.example.ts.net"
    assert https.cookies_secure
    assert not load_settings({"FRANCA_PUBLIC_URL": "http://localhost:8080"}).cookies_secure
