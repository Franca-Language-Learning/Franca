"""Checks of the private-network settings (story E01-009) in the bundle's files.

The tailnet itself is rehearsed with real containers in rehearse_tailnet.py. These tests read the files, so that a
change that opens a port, moves TLS away from Caddy or loses the node's state fails before any container is built.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

INFRA = Path(__file__).resolve().parents[1]
CADDY_HTTPS_PORT = 8443


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((INFRA / "compose.yaml").read_text())
    return loaded


@pytest.fixture(scope="module")
def tailscale(compose: dict[str, Any]) -> dict[str, Any]:
    service: dict[str, Any] = compose["services"]["tailscale"]
    return service


def dockerfile_user(name: str) -> str:
    users = re.findall(r"^USER (\d+):\d+$", (INFRA / "images" / name).read_text(), re.MULTILINE)
    assert users, f"{name} has no numeric USER line"
    return str(users[-1])


def test_tailscale_is_in_its_own_profile(tailscale: dict[str, Any]) -> None:
    assert tailscale["profiles"] == ["tailnet"]


def test_tailscale_publishes_no_port(tailscale: dict[str, Any]) -> None:
    assert "ports" not in tailscale
    assert "network_mode" not in tailscale


def test_no_service_publishes_a_port_beyond_this_computer(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port}"


def test_tailscale_runs_hardened_as_a_user(tailscale: dict[str, Any]) -> None:
    assert tailscale["read_only"] is True
    assert tailscale["cap_drop"] == ["ALL"]
    assert "cap_add" not in tailscale
    assert "devices" not in tailscale
    assert dockerfile_user("tailscale.Dockerfile") not in {"0", ""}


def test_the_auth_key_comes_from_a_secret_file(compose: dict[str, Any], tailscale: dict[str, Any]) -> None:
    environment = tailscale["environment"]
    assert environment["TS_AUTHKEY"] == "file:/run/secrets/tailscale_authkey"
    assert tailscale["secrets"] == ["tailscale_authkey"]
    assert compose["secrets"]["tailscale_authkey"]["file"].endswith("/tailscale_authkey")


def test_the_node_keeps_its_identity(compose: dict[str, Any], tailscale: dict[str, Any]) -> None:
    environment = tailscale["environment"]
    # With TS_AUTH_ONCE the key is used once; later starts use the saved state, so a used or expired key is no problem.
    assert environment["TS_AUTH_ONCE"] == "true"
    state_dir = environment["TS_STATE_DIR"]
    mounts = dict(volume.split(":")[1::-1] for volume in tailscale["volumes"])
    assert mounts[state_dir] in compose["volumes"]


def test_tailscale_uses_userspace_networking(tailscale: dict[str, Any]) -> None:
    assert tailscale["environment"]["TS_USERSPACE"] == "true"


def test_only_caddy_may_fetch_certificates(tailscale: dict[str, Any]) -> None:
    assert tailscale["environment"]["TS_PERMIT_CERT_UID"] == dockerfile_user("caddy.Dockerfile")


def test_tailnet_connections_on_443_go_to_caddy_with_tls_intact() -> None:
    serve = json.loads((INFRA / "tailscale" / "serve.json").read_text())
    # A PROXY protocol header (version 2) in front tells Caddy the device's tailnet address.
    assert serve == {"TCP": {"443": {"TCPForward": f"caddy:{CADDY_HTTPS_PORT}", "ProxyProtocol": 2}}}


def test_the_socket_is_in_the_shared_volume_itself(tailscale: dict[str, Any]) -> None:
    # Without TS_SOCKET, containerboot puts the socket in /tmp and leaves a symlink in the volume, which Caddy cannot follow.
    assert tailscale["environment"]["TS_SOCKET"] == "/var/run/tailscale/tailscaled.sock"


def test_caddy_reads_the_tailscale_socket_read_only(tailscale: dict[str, Any], compose: dict[str, Any]) -> None:
    socket_volume = next(v for v in tailscale["volumes"] if v.endswith(":/var/run/tailscale"))
    assert f"{socket_volume}:ro" in compose["services"]["caddy"]["volumes"]


def test_caddy_serves_https_on_the_tailscale_name() -> None:
    caddyfile = (INFRA / "caddy" / "Caddyfile").read_text()
    assert re.search(r"^https://\{\$FRANCA_TAILSCALE_NAME\}:" + str(CADDY_HTTPS_PORT) + r" \{", caddyfile, re.MULTILINE)
    assert "auto_https off" not in caddyfile
    assert "Strict-Transport-Security" in caddyfile


def test_caddy_reads_the_proxy_header_before_tls_and_offers_no_http3() -> None:
    caddyfile = re.sub(r"^\s*#.*\n", "", (INFRA / "caddy" / "Caddyfile").read_text(), flags=re.MULTILINE)
    server = re.search(r"servers :" + str(CADDY_HTTPS_PORT) + r" \{(.*?)\n\t\}", caddyfile, re.DOTALL)
    assert server, "no server options for the HTTPS port"
    options = server.group(1)
    assert re.search(r"listener_wrappers \{\s*proxy_protocol \{.*?\}\s*tls\s*\}", options, re.DOTALL)
    # HTTP/3 would be offered on UDP 8443, which is not passed on over the tailnet.
    assert re.search(r"^\s*protocols h1 h2$", options, re.MULTILINE)


def test_caddy_has_a_tailscale_name_even_before_the_installer_sets_one(compose: dict[str, Any]) -> None:
    name = compose["services"]["caddy"]["environment"]["FRANCA_TAILSCALE_NAME"]
    match = re.fullmatch(r"\$\{FRANCA_TAILSCALE_NAME:-(.+)\}", name)
    assert match, name
    # A .ts.net name is never sent to a public certificate authority by Caddy: it asks tailscaled for it.
    assert match.group(1).endswith(".ts.net")
