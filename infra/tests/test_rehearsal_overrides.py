"""Tests of the Compose overrides in the tailnet and installer rehearsals (rehearse_tailnet.py, rehearse_install.py).

The rehearsals run in the Container bundle job, where Harden-Runner refuses connections to hosts that are not on the
job's list. Headscale, the Tailscale containers and Caddy are given settings in the overrides, so that no connection
from a rehearsal goes to Tailscale or to a public certificate authority.
"""

from pathlib import Path
from typing import Any

import rehearsal
import rehearse_install
import rehearse_tailnet
import yaml


def services(override: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(override)["services"]
    return loaded


def test_the_tailscale_containers_of_the_tailnet_rehearsal_send_nothing_to_tailscale() -> None:
    loaded = services(rehearse_tailnet.OVERRIDE)

    for name in ("tailscale", "phone"):
        environment = loaded[name]["environment"]
        assert rehearsal.TAILSCALE_REHEARSAL_ENVIRONMENT.items() <= environment.items(), name
        assert environment["TS_EXTRA_ARGS"] == f"--login-server={rehearse_tailnet.LOGIN_SERVER}"


def test_caddy_in_the_tailnet_rehearsal_has_no_public_certificate_authority() -> None:
    caddy = services(rehearse_tailnet.OVERRIDE)["caddy"]

    assert "./caddy/Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]


def test_the_tailscale_container_of_the_installer_rehearsal_sends_nothing_to_tailscale(tmp_path: Path) -> None:
    tailscale = services(rehearse_install.override(tmp_path / "Caddyfile"))["tailscale"]

    assert rehearsal.TAILSCALE_REHEARSAL_ENVIRONMENT.items() <= tailscale["environment"].items()
    assert tailscale["environment"]["TS_EXTRA_ARGS"] == "--login-server=http://headscale:8080"


def test_caddy_in_the_installer_rehearsal_has_no_public_certificate_authority(tmp_path: Path) -> None:
    caddy = services(rehearse_install.override(tmp_path / "Caddyfile"))["caddy"]

    assert f"{tmp_path / 'Caddyfile'}:/etc/caddy/Caddyfile:ro" in caddy["volumes"]
