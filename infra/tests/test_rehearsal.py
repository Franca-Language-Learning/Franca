"""Tests for the helpers that the rehearsals share (rehearsal.py). The rehearsals themselves need Docker and run in the
Container bundle job of the pipeline."""

import stat
from pathlib import Path

import pytest
import rehearsal
import yaml


def test_a_check_is_printed_and_a_failure_is_kept(capsys: pytest.CaptureFixture[str]) -> None:
    checks = rehearsal.Checks()
    checks.check(True, "the app starts")
    checks.check(False, "the backup runs")

    assert capsys.readouterr().out == "ok:   the app starts\nFAIL: the backup runs\n"
    assert checks.failures == ["the backup runs"]


def test_the_exit_code_is_1_after_a_failure_and_0_without_one(capsys: pytest.CaptureFixture[str]) -> None:
    passed, failed = rehearsal.Checks(), rehearsal.Checks()
    passed.check(True, "one")
    failed.check(False, "two")

    assert passed.exit_code() == 0
    assert "The rehearsal passed." in capsys.readouterr().out
    assert failed.exit_code() == 1
    assert "The rehearsal failed: 1 check(s)." in capsys.readouterr().out


def test_each_secret_in_the_compose_file_gets_a_file_that_every_container_can_read(tmp_path: Path) -> None:
    folder = rehearsal.write_secrets(tmp_path / "secrets", {"ntfy_topic": "a-topic"})

    compose = yaml.safe_load((rehearsal.ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"))
    assert set(rehearsal.SECRET_NAMES) == set(compose["secrets"])
    assert sorted(path.name for path in folder.iterdir()) == sorted(rehearsal.SECRET_NAMES)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o644 for path in folder.iterdir())
    assert (folder / "ntfy_topic").read_text(encoding="utf-8") == "a-topic"


def test_the_session_secret_and_backup_password_are_random_and_the_other_secrets_empty(tmp_path: Path) -> None:
    first = rehearsal.write_secrets(tmp_path / "first")
    second = rehearsal.write_secrets(tmp_path / "second")

    for name in ("session_secret", "backup_password"):
        assert len((first / name).read_text(encoding="utf-8")) == 64
        assert (first / name).read_text(encoding="utf-8") != (second / name).read_text(encoding="utf-8")
    assert (first / "google_client_secret").read_text(encoding="utf-8") == ""
    assert (first / "tailscale_authkey").read_text(encoding="utf-8") == ""


def test_a_given_value_replaces_a_random_one(tmp_path: Path) -> None:
    folder = rehearsal.write_secrets(tmp_path / "secrets", {"session_secret": "given"})

    assert (folder / "session_secret").read_text(encoding="utf-8") == "given"


def test_the_env_file_has_one_line_for_each_value(tmp_path: Path) -> None:
    rehearsal.write_env(tmp_path / ".env", {"FRANCA_VERSION": "1.0.0", "COMPOSE_PROFILES": "backups"})

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "FRANCA_VERSION=1.0.0\nCOMPOSE_PROFILES=backups\n"


def test_the_compose_file_is_copied_with_an_override_beside_it(tmp_path: Path) -> None:
    rehearsal.copy_compose_file(tmp_path, override="services: {}\n")

    assert (tmp_path / "compose.yaml").read_text(encoding="utf-8") == (rehearsal.ROOT / "infra" / "compose.yaml").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "compose.override.yaml").read_text(encoding="utf-8") == "services: {}\n"


def test_without_an_override_no_override_file_is_written(tmp_path: Path) -> None:
    rehearsal.copy_compose_file(tmp_path)

    assert not (tmp_path / "compose.override.yaml").exists()


def test_the_compose_command_names_the_folder_and_the_project(tmp_path: Path) -> None:
    assert rehearsal.compose_command(tmp_path, "rehearsal-1") == [
        "docker",
        "compose",
        "--project-directory",
        str(tmp_path),
        "--project-name",
        "rehearsal-1",
    ]
    assert rehearsal.compose_command(tmp_path) == ["docker", "compose", "--project-directory", str(tmp_path)]


def test_a_failed_command_ends_the_rehearsal_with_its_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="Command failed: sh -c"):
        rehearsal.sh("sh", "-c", "echo the reason >&2; exit 3")

    assert "the reason" in capsys.readouterr().out


def test_a_failed_command_is_returned_when_it_is_not_checked() -> None:
    result = rehearsal.sh("sh", "-c", "read line; echo got $line; exit 3", check=False, stdin="input\n")

    assert (result.returncode, result.stdout) == (3, "got input\n")


def test_a_free_port_can_be_listened_on() -> None:
    port = rehearsal.free_port()

    assert 1024 <= port <= 65535


@pytest.mark.parametrize("base_domain", [None, "rehearsal.ts.net"])
def test_the_headscale_settings_are_valid_yaml(base_domain: str | None) -> None:
    settings = yaml.safe_load(rehearsal.headscale_config(base_domain))

    assert settings["server_url"] == "http://headscale:8080"
    assert settings["dns"]["magic_dns"] is (base_domain is not None)
    assert settings["dns"].get("base_domain") == base_domain
    assert settings["dns"]["override_local_dns"] is False


@pytest.mark.parametrize("base_domain", [None, "rehearsal.ts.net"])
def test_headscale_uses_its_own_relay_and_no_server_on_the_internet(base_domain: str | None) -> None:
    settings = yaml.safe_load(rehearsal.headscale_config(base_domain))

    derp = settings["derp"]
    assert derp["server"]["enabled"] is True
    assert derp["server"]["automatically_add_embedded_derp_region"] is True
    assert derp["server"]["stun_listen_addr"] == "0.0.0.0:3478"
    assert derp["server"]["private_key_path"].startswith("/var/lib/headscale/")
    assert derp["urls"] == []
    assert derp["paths"] == []
    assert derp["auto_update_enabled"] is False
    assert settings["disable_check_updates"] is True
    assert settings["logtail"]["enabled"] is False


def test_the_tailscale_containers_of_a_rehearsal_send_nothing_to_tailscale() -> None:
    assert rehearsal.TAILSCALE_REHEARSAL_ENVIRONMENT == {
        "TS_NO_LOGS_NO_SUPPORT": "true",
        "TS_DEBUG_USE_DERP_HTTP": "true",
        "TS_DISABLE_PORTMAPPER": "true",
    }


def test_environment_lines_are_a_yaml_mapping_at_the_given_indent() -> None:
    lines = rehearsal.environment_lines({"A": "true", "B": "--x=http://h:1"}, indent=6)

    assert lines == '      A: "true"\n      B: "--x=http://h:1"\n'
    assert yaml.safe_load("environment:\n" + lines) == {"environment": {"A": "true", "B": "--x=http://h:1"}}


def test_the_rehearsal_caddyfile_has_local_certificates_and_is_otherwise_the_bundles() -> None:
    bundle = (rehearsal.ROOT / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    rehearsed = rehearsal.rehearsal_caddyfile()

    added = [line.strip() for line in rehearsed.splitlines() if line not in bundle.splitlines()]
    assert added == ["local_certs", "skip_install_trust"]
    assert rehearsed.splitlines()[rehearsed.splitlines().index("{") + 1].strip() == "local_certs"
    assert "local_certs" not in bundle


def test_a_rehearsal_caddyfile_is_written_for_every_user_to_read(tmp_path: Path) -> None:
    path = rehearsal.write_rehearsal_caddyfile(tmp_path / "caddy")

    assert path.read_text(encoding="utf-8") == rehearsal.rehearsal_caddyfile()
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_a_service_counts_as_healthy_only_when_it_is_running_and_its_health_check_passes() -> None:
    listed = ["app running healthy", "caddy running healthy", "socket-proxy running", "backup running unhealthy", "updater exited"]

    assert rehearsal.services_not_healthy(listed, ["app", "caddy", "socket-proxy", "backup", "updater", "status"]) == [
        "socket-proxy: running, with no health check",
        "backup: running, unhealthy",
        "updater: exited",
        "status: not started",
    ]


def test_all_services_running_and_healthy_gives_no_problem() -> None:
    assert rehearsal.services_not_healthy(["app running healthy"], ["app"]) == []


def test_the_docker_group_is_the_group_of_the_socket(tmp_path: Path) -> None:
    socket = tmp_path / "docker.sock"
    socket.touch()

    assert rehearsal.docker_group(socket) == str(socket.stat().st_gid)
