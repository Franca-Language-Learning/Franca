"""Tests for tools/check-startup-files.sh (story E01-004).

Python runs .pth files, sitecustomize.py and usercustomize.py from site-packages every time it starts, so a
package that installs one can run code without being imported. The check is a shell script, so running it does
not start Python and does not run the files it looks for.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check-startup-files.sh"
VIRTUALENV_PTH = b"import _virtualenv\n"
VIRTUALENV_PY = b"# stand-in for the module that uv writes\n"


def run(env: Path, allowed: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(env)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "STARTUP_FILES_ALLOWED": str(allowed)},
    )


@pytest.fixture
def env(tmp_path: Path) -> Path:
    site = tmp_path / "venv" / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    (site / "_virtualenv.pth").write_bytes(VIRTUALENV_PTH)
    (site / "_virtualenv.py").write_bytes(VIRTUALENV_PY)
    return tmp_path / "venv"


@pytest.fixture
def allowed(tmp_path: Path) -> Path:
    file = tmp_path / "allowed.txt"
    file.write_text(
        "# name and SHA-256\n"
        f"_virtualenv.pth {hashlib.sha256(VIRTUALENV_PTH).hexdigest()}\n"
        f"_virtualenv.py {hashlib.sha256(VIRTUALENV_PY).hexdigest()}\n"
    )
    return file


def site(env: Path) -> Path:
    return env / "lib" / "python3.14" / "site-packages"


def test_a_clean_environment_passes(env: Path, allowed: Path) -> None:
    result = run(env, allowed)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unknown_pth_file_fails(env: Path, allowed: Path) -> None:
    (site(env) / "evil.pth").write_text("import os; os.system('true')\n")
    result = run(env, allowed)
    assert result.returncode == 1
    assert "evil.pth" in result.stdout


def test_an_allowed_name_with_changed_content_fails(env: Path, allowed: Path) -> None:
    (site(env) / "_virtualenv.pth").write_text("import _virtualenv; import os\n")
    assert run(env, allowed).returncode == 1


def test_a_changed_virtualenv_module_fails(env: Path, allowed: Path) -> None:
    (site(env) / "_virtualenv.py").write_text("import os  # changed by a package\n")
    result = run(env, allowed)
    assert result.returncode == 1
    assert "_virtualenv.py" in result.stdout


@pytest.mark.parametrize("name", ["sitecustomize.py", "usercustomize.py"])
def test_customize_files_fail(env: Path, allowed: Path, name: str) -> None:
    (site(env) / name).write_text("pass\n")
    result = run(env, allowed)
    assert result.returncode == 1
    assert name in result.stdout


def test_a_missing_environment_is_an_error(tmp_path: Path, allowed: Path) -> None:
    assert run(tmp_path / "nothing", allowed).returncode == 2


def test_the_project_environment_passes() -> None:
    venv = SCRIPT.parents[1] / ".venv"
    if not venv.exists():
        if os.environ.get("CI"):
            pytest.fail("the pipeline has no project environment")
        pytest.skip("no project environment")
    result = subprocess.run(["bash", str(SCRIPT), str(venv)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
