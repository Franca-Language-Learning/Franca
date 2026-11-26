"""Checks of the health monitoring settings (story E01-010) in the bundle's files.

The monitoring is rehearsed with real containers in rehearse_status.py. These tests read the files, so that a check or
an alert that goes missing, or a secret written into a file, fails before any container is built.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

INFRA = Path(__file__).resolve().parents[1]
GATUS_CONFIG = INFRA / "status" / "gatus.yaml"


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((INFRA / "compose.yaml").read_text())
    return loaded


@pytest.fixture(scope="module")
def gatus() -> dict[str, Any]:
    # Gatus replaces ${...} with environment variables before it reads the YAML; the names are left as they are here.
    loaded: dict[str, Any] = yaml.safe_load(GATUS_CONFIG.read_text())
    return loaded


def endpoint(gatus: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(e for e in gatus["endpoints"] if e["name"] == name)
    return found


def external(gatus: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(e for e in gatus["external-endpoints"] if e["name"] == name)
    return found


def test_the_status_container_is_in_its_own_profile_and_hardened(compose: dict[str, Any]) -> None:
    status = compose["services"]["status"]
    assert status["profiles"] == ["monitoring"]
    assert status["read_only"] is True
    assert status["cap_drop"] == ["ALL"]
    assert all(str(port).startswith("127.0.0.1:") for port in status.get("ports", []))


def test_the_alert_topic_and_the_push_token_are_secrets(compose: dict[str, Any]) -> None:
    assert set(compose["services"]["status"]["secrets"]) == {"ntfy_topic", "status_push_token"}
    text = GATUS_CONFIG.read_text()
    assert "${NTFY_TOPIC}" in text
    assert "${STATUS_PUSH_TOKEN}" in text


@pytest.mark.parametrize("name", ["App", "Web server"])
def test_the_app_and_the_web_server_are_checked_every_minute(gatus: dict[str, Any], name: str) -> None:
    checked = endpoint(gatus, name)
    assert checked["interval"] == "1m"
    assert "[STATUS] == 200" in checked["conditions"]
    assert [alert["type"] for alert in checked["alerts"]] == ["ntfy"]


def test_the_app_check_reads_the_health_answer(gatus: dict[str, Any]) -> None:
    app = endpoint(gatus, "App")
    assert app["url"] == "http://app:8000/api/v1/health"
    assert "[BODY].status == ok" in app["conditions"]


def test_https_on_the_tailscale_name_is_checked_with_its_certificate(gatus: dict[str, Any]) -> None:
    https = endpoint(gatus, "HTTPS on the Tailscale name")
    assert https["url"] == "https://${FRANCA_TAILSCALE_NAME}:8443/healthz"
    assert https["enabled"] == "${FRANCA_TAILNET_CHECKS}"
    # Tailscale renews the certificate when it has 30 days or less left. An alert at 14 days leaves time to act.
    assert "[CERTIFICATE_EXPIRATION] > 336h" in https["conditions"]


def test_caddy_answers_to_the_tailscale_name_inside_the_bundle(compose: dict[str, Any]) -> None:
    aliases = compose["services"]["caddy"]["networks"]["internal"]["aliases"]
    assert "${FRANCA_TAILSCALE_NAME:-tailscale-name-not-set.ts.net}" in aliases


def test_tailscale_is_checked_on_an_address_the_tailnet_cannot_reach(gatus: dict[str, Any]) -> None:
    tailscale = endpoint(gatus, "Tailscale")
    assert tailscale["url"] == "http://tailscale:9002/healthz"
    assert tailscale["enabled"] == "${FRANCA_TAILNET_CHECKS}"
    entrypoint = (INFRA / "tailscale" / "entrypoint.sh").read_text()
    # Connections from the tailnet arrive at 127.0.0.1, so the health port listens on the bundle's network address.
    assert "TS_LOCAL_ADDR_PORT" in entrypoint
    assert "127.0.0.1" not in entrypoint


@pytest.mark.parametrize(("name", "interval"), [("Update", "25h"), ("Backup", "25h"), ("Restore test", "745h")])
def test_the_nightly_jobs_report_and_a_missed_report_is_an_alert(gatus: dict[str, Any], name: str, interval: str) -> None:
    job = external(gatus, name)
    assert job["token"] == "${STATUS_PUSH_TOKEN}"  # noqa: S105 - the name of a variable, not a token
    assert job["heartbeat"]["interval"] == interval
    assert [alert["type"] for alert in job["alerts"]] == ["ntfy"]
    assert job["alerts"][0]["failure-threshold"] == 1


def test_alerts_go_to_ntfy_and_say_when_the_problem_is_over(gatus: dict[str, Any]) -> None:
    ntfy = gatus["alerting"]["ntfy"]
    assert ntfy["topic"] == "${NTFY_TOPIC}"
    assert ntfy["url"] == "${FRANCA_NTFY_URL}"
    assert ntfy["default-alert"]["send-on-resolved"] is True


def test_the_history_is_kept_in_the_status_volume(gatus: dict[str, Any], compose: dict[str, Any]) -> None:
    assert gatus["storage"] == {"type": "sqlite", "path": "/data/status.db"}
    assert "status-data:/data" in compose["services"]["status"]["volumes"]


def test_the_updater_and_the_backup_can_report(compose: dict[str, Any]) -> None:
    for name in ("updater", "backup"):
        service = compose["services"][name]
        assert "status_push_token" in service["secrets"]
        assert service["environment"]["FRANCA_STATUS_URL"] == "http://status:8080"


def test_no_secret_value_is_in_the_config() -> None:
    assert not re.search(r"tk_[A-Za-z0-9]{20,}|token: [\"']?[A-Za-z0-9]{16,}", GATUS_CONFIG.read_text())
