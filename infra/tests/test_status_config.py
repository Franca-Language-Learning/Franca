"""Checks of the health-monitoring settings (story E01-010) in the bundle's files.

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


def test_the_alert_topic_the_push_token_and_the_heartbeat_address_are_secrets(compose: dict[str, Any]) -> None:
    assert set(compose["services"]["status"]["secrets"]) == {"ntfy_topic", "status_push_token", "healthchecks_ping_url"}
    assert compose["secrets"]["healthchecks_ping_url"] == {"file": "${FRANCA_SECRETS_DIR:-./secrets}/healthchecks_ping_url"}
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


def test_the_sign_in_page_is_checked_through_the_web_server_every_minute(gatus: dict[str, Any]) -> None:
    page = endpoint(gatus, "Sign-in page")
    assert page["url"] == "http://caddy:8080/sign-in"
    assert page["interval"] == "1m"
    assert "[STATUS] == 200" in page["conditions"]
    # The client's page with its built script, not an error page from Caddy.
    assert '[BODY] == pat(*<div id="root">*)' in page["conditions"]
    assert "[BODY] == pat(*/assets/*.js*)" in page["conditions"]
    assert [alert["type"] for alert in page["alerts"]] == ["ntfy"]


def test_an_api_route_that_needs_a_session_answers_401_without_one(gatus: dict[str, Any]) -> None:
    api = endpoint(gatus, "Signed-in API")
    assert api["url"] == "http://caddy:8080/api/v1/me"
    assert api["interval"] == "1m"
    assert api["conditions"] == ["[STATUS] == 401"]
    assert [alert["type"] for alert in api["alerts"]] == ["ntfy"]


def test_the_socket_proxy_is_reported_by_the_updater_and_a_missed_report_is_an_alert(
    gatus: dict[str, Any], compose: dict[str, Any]
) -> None:
    proxy = external(gatus, "Socket proxy")
    assert proxy["group"] == "Franca"
    assert proxy["token"] == "${STATUS_PUSH_TOKEN}"  # noqa: S105 - the name of a variable, not a token
    assert proxy["heartbeat"]["interval"] == "10m"
    assert [alert["type"] for alert in proxy["alerts"]] == ["ntfy"]
    # Gatus is kept off the proxy's network: a container that can reach the proxy can start containers.
    assert "docker-api" not in compose["services"]["status"]["networks"]


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


@pytest.mark.parametrize("name", ["Update", "Backup", "Restore test"])
def test_the_nightly_jobs_report_and_a_missed_report_is_an_alert(gatus: dict[str, Any], name: str) -> None:
    job = external(gatus, name)
    assert job["token"] == "${STATUS_PUSH_TOKEN}"  # noqa: S105 - the name of a variable, not a token
    # The updater and the backup report every hour, so two hours without a report means that one of them has stopped.
    assert job["heartbeat"]["interval"] == "2h"
    assert [alert["type"] for alert in job["alerts"]] == ["ntfy"]
    assert job["alerts"][0]["failure-threshold"] == 1
    assert job["alerts"][0]["success-threshold"] == 1


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


def test_the_tailnet_checks_need_the_tailnet_profile(compose: dict[str, Any]) -> None:
    assert compose["services"]["status"]["environment"]["FRANCA_PROFILES"] == "${COMPOSE_PROFILES:-}"
    entrypoint = (INFRA / "status" / "entrypoint.sh").read_text()
    assert 'case ",${FRANCA_PROFILES:-}," in' in entrypoint
    assert "*,tailnet,*)" in entrypoint


def test_no_secret_value_is_in_the_config() -> None:
    assert not re.search(r"tk_[A-Za-z0-9]{20,}|token: [\"']?[A-Za-z0-9]{16,}", GATUS_CONFIG.read_text())


# --- the heartbeat to healthchecks.io (story E01-012)
#
# These tests check the layout of the start script and the image file. The behaviour is rehearsed with real containers
# in rehearse_status.py (heartbeats, the process list, the log, a bad setting, the network down).

ENTRYPOINT = INFRA / "status" / "entrypoint.sh"
DOCKERFILE = INFRA / "images" / "status.Dockerfile"


def test_the_start_script_reads_the_heartbeat_address_as_an_optional_secret() -> None:
    script = ENTRYPOINT.read_text()
    assert "read_optional_secret healthchecks_ping_url" in script
    assert 'if [ -n "$HEARTBEAT_URL" ]; then' in script


def test_the_start_script_does_not_pass_the_address_to_gatus_or_write_it() -> None:
    script = ENTRYPOINT.read_text()
    exported = next(line for line in script.splitlines() if line.startswith("export "))
    assert "HEARTBEAT_URL" not in exported
    assert "HEARTBEAT" not in GATUS_CONFIG.read_text()
    assert not [line for line in script.splitlines() if "echo" in line and "HEARTBEAT_URL" in line]


def test_the_start_script_gives_the_address_to_curl_on_standard_input_not_on_its_command_line() -> None:
    script = ENTRYPOINT.read_text()
    # printf is built into the shell, so the address is in no process's command line.
    assert """printf 'url = "%s"\\n' "$1" | curl -fsS -m 10 -o /dev/null -K - 2>/dev/null""" in script
    assert not [line for line in script.splitlines() if "wget" in line and '"$1"' in line]
    assert "apk add --no-cache ca-certificates curl" in DOCKERFILE.read_text()


def test_the_start_script_sends_heartbeats_while_gatus_answers_every_five_minutes_by_default(compose: dict[str, Any]) -> None:
    script = ENTRYPOINT.read_text()
    assert "wget -q -T 10 -O /dev/null http://127.0.0.1:8080/health" in script
    assert compose["services"]["status"]["environment"]["FRANCA_HEARTBEAT_SECONDS"] == "${FRANCA_HEARTBEAT_SECONDS:-300}"


def test_the_start_script_checks_the_address_and_the_interval_against_strict_patterns() -> None:
    # The owner's check on healthchecks.io has a period of 5 minutes and a grace time of 10 minutes.
    script = ENTRYPOINT.read_text()
    assert "matches \"$HEARTBEAT_URL\" 'https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]+)+'" in script
    assert "matches \"$FRANCA_HEARTBEAT_SECONDS\" '([5-9]|[1-9][0-9]|[12][0-9]{2}|300)'" in script


def test_a_bad_heartbeat_setting_turns_the_heartbeat_off_and_leaves_gatus_running() -> None:
    script = ENTRYPOINT.read_text()
    heartbeat_part = script[script.index('HEARTBEAT_URL="$(read_optional_secret') : script.index("export ")]
    assert "fail " not in heartbeat_part
    assert "franca-status: the heartbeat is off:" in heartbeat_part
