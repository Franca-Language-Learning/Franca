"""Checks of the settings for the app check in the monthly restore test (story E01-008).

The backup restores the latest backup, checks the database, and puts the copy in the restore-test volume with a
request. The updater, which reaches Docker through the socket proxy, starts the app image on that copy in a one-off
container (the restore-check service) and the answer is written beside the copy. rehearse_backup.py rehearses this
with real containers.
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


def test_the_one_off_container_is_the_app_image_on_the_restored_copy(compose: dict[str, Any]) -> None:
    check = compose["services"]["restore-check"]
    assert check["image"] == compose["services"]["app"]["image"]
    assert check["volumes"] == ["restore-test:/data"]
    # Only started with docker compose run, never by docker compose up.
    assert check["profiles"] == ["restore-check"]
    assert check["restart"] == "no"


def test_the_one_off_container_has_no_network_and_only_the_session_secret(compose: dict[str, Any]) -> None:
    check = compose["services"]["restore-check"]
    assert check["network_mode"] == "none"
    assert "networks" not in check
    assert check["secrets"] == ["session_secret"]
    assert "ports" not in check


def test_the_one_off_container_is_hardened(compose: dict[str, Any]) -> None:
    check = compose["services"]["restore-check"]
    assert check["read_only"] is True
    assert check["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in check["security_opt"]


def test_the_backup_and_the_updater_share_the_restore_test_volume(compose: dict[str, Any]) -> None:
    assert "restore-test" in compose["volumes"]
    assert "restore-test:/restore-test" in compose["services"]["backup"]["volumes"]
    assert "restore-test:/restore-test" in compose["services"]["updater"]["volumes"]
    # The backup does not get the Docker API. Only the updater is on the proxy's network.
    assert "docker-api" not in compose["services"]["backup"]["networks"]


@pytest.mark.parametrize("image", ["backup", "updater"])
def test_the_shared_folder_belongs_to_the_apps_user_in_each_image(image: str) -> None:
    # A new volume takes the owner of the folder in the image that mounts it first, and the backup and the one-off
    # container (both user 10001) write there.
    dockerfile = (INFRA / "images" / f"{image}.Dockerfile").read_text(encoding="utf-8")
    assert "install -d -o 10001 -g 10001 /restore-test" in dockerfile
