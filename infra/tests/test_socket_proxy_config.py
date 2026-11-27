"""Checks of the socket proxy's settings in compose.yaml (stories E01-005 and E01-007).

The socket proxy passes a limited set of Docker API calls from the updater to Docker's socket. These tests read the
file, so that a lost limit fails before any container is built. rehearse_update.py and rehearse_install.py check the
running container: its user and its health.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

INFRA = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((INFRA / "compose.yaml").read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def proxy(compose: dict[str, Any]) -> dict[str, Any]:
    service: dict[str, Any] = compose["services"]["socket-proxy"]
    return service


def test_the_proxy_runs_as_a_user_other_than_root(proxy: dict[str, Any]) -> None:
    user, group = str(proxy["user"]).split(":")
    assert int(user) >= 10000
    assert int(group) >= 10000


def test_the_proxy_can_read_the_socket_through_the_docker_group(proxy: dict[str, Any]) -> None:
    # The installer writes the group of /var/run/docker.sock to .env. Without it, a group that cannot read the socket
    # is used, so the health check fails and the fault is seen.
    assert proxy["group_add"] == ["${FRANCA_DOCKER_GID:-65534}"]


def test_the_proxy_has_a_health_check_that_goes_through_to_docker(proxy: dict[str, Any]) -> None:
    check = proxy["healthcheck"]
    assert check["test"] == ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:2375/_ping"]
    assert check["interval"] == "30s"


def test_the_proxy_is_hardened(proxy: dict[str, Any]) -> None:
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in proxy["security_opt"]
    # HAProxy writes its configuration and its process id to /run, as user 10006. Without the mode, the tmpfs belongs to
    # root and HAProxy does not start (seen in the update rehearsal).
    assert "/run:mode=1777" in proxy["tmpfs"]


def test_the_proxy_is_on_a_network_that_has_no_way_out_and_only_the_updater_joins(compose: dict[str, Any]) -> None:
    assert compose["services"]["socket-proxy"]["networks"] == ["docker-api"]
    assert compose["networks"]["docker-api"]["internal"] is True
    joined = sorted(name for name, service in compose["services"].items() if "docker-api" in (service.get("networks") or []))
    assert joined == ["socket-proxy", "updater"]


def test_the_calls_that_could_take_over_the_pc_without_a_container_are_refused(proxy: dict[str, Any]) -> None:
    environment = proxy["environment"]
    for name in ("EXEC", "BUILD", "SWARM", "SECRETS", "PLUGINS", "SYSTEM", "AUTH"):
        assert environment[name] == 0, name


def test_the_updater_waits_until_the_proxy_is_healthy(compose: dict[str, Any]) -> None:
    assert compose["services"]["updater"]["depends_on"] == {"socket-proxy": {"condition": "service_healthy"}}
