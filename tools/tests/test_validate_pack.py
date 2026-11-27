"""Tests for tools/validate_pack.py (defect D17 of the M0 re-test, criterion E01-014 #9).

The values in these tests are made up, and PACK_VALUE and PACK_KEY must not be in the output. The reason is in the
module docstring. Some of the cases come from the review of pull request #38, which tried the command on broken copies
of the fixture pack.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "packs" / "fixture"
PACK_VALUE = "ZZ-PACK_VALUE-ZZ"
PACK_KEY = "zz-secret-key-zz"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_pack", ROOT / "tools" / "validate_pack.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered in sys.modules because dataclasses look up the module of a class. The two test files each load their
    # own copy.
    sys.modules["validate_pack"] = module
    spec.loader.exec_module(module)
    return module


validate_pack = load_tool()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the pack checker tried to use the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def pack(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / "pack"
    for relative, text in files.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    folder.mkdir(exist_ok=True)
    return folder


def fixture_text(relative: str) -> str:
    return (FIXTURE / relative).read_text(encoding="utf-8")


def run(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, list[str], str]:
    """The exit code, the lines written to standard output, and standard error."""
    code = validate_pack.main(list(arguments))
    captured = capsys.readouterr()
    output = captured.out + captured.err
    for value in (PACK_VALUE, PACK_KEY):
        # PyYAML writes some values in lower case in its messages, for example for !!float.
        assert value not in output
        assert value.lower() not in output
    assert "Traceback" not in output
    return code, captured.out.splitlines(), captured.err


def problems(lines: list[str]) -> list[str]:
    return lines[:-1]


# --- the fixture pack and the summary


def test_the_fixture_pack_has_no_problems(capsys: pytest.CaptureFixture[str]) -> None:
    code, lines, _err = run(capsys, str(FIXTURE))
    count = len(list(FIXTURE.rglob("*.yaml")))
    assert code == 0
    assert lines == [f"Files checked: {count}. Problems: 0."]


def test_a_pack_with_problems_exits_with_1_and_counts_them(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = pack(tmp_path, {"pack.yaml": "{}\n", "lexicon/a.yaml": "{}\n", "chunks/b.yaml": fixture_text("chunks/nodig-hebben.yaml")})
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert lines[-1] == "Files checked: 3. Problems: 2."
    assert problems(lines) == ['lexicon/a.yaml: required at ""', 'pack.yaml: required at ""']


# --- usage errors


def test_no_folder_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, lines, err = run(capsys)
    assert code == 2
    assert lines == []
    assert "validate_pack.py <pack folder>" in err


def test_a_folder_that_does_not_exist_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, lines, err = run(capsys, str(tmp_path / "missing"))
    assert code == 2
    assert lines == []
    assert "is not a folder" in err


def test_a_file_instead_of_a_folder_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "pack.yaml"
    path.write_text("{}\n", encoding="utf-8")
    code, _lines, _err = run(capsys, str(path))
    assert code == 2


# --- what is reported, with no value from the pack


def test_a_file_of_unknown_type_is_reported_by_its_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = pack(
        tmp_path,
        {
            "notes/todo.yaml": f"note: {PACK_VALUE}\n",
            "lexicon/Capital.yaml": f"note: {PACK_VALUE}\n",
            "pack.yml": f"a: {PACK_VALUE}\n",
            "lexicon/hallo.YAML": f"a: {PACK_VALUE}\n",
            "chunks/b.Yml": f"a: {PACK_VALUE}\n",
        },
    )
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert sorted(problems(lines)) == [
        "chunks/b.Yml: unknown-file-type",
        "lexicon/Capital.yaml: unknown-file-type",
        "lexicon/hallo.YAML: unknown-file-type",
        "notes/todo.yaml: unknown-file-type",
        "pack.yml: unknown-file-type",
    ]


def test_an_unknown_field_is_reported_at_its_object_without_its_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = fixture_text("lexicon/zakje.yaml") + f"{PACK_KEY}: {PACK_VALUE}\n"
    code, lines, _err = run(capsys, str(pack(tmp_path, {"lexicon/zakje.yaml": text})))
    assert code == 1
    assert problems(lines) == ['lexicon/zakje.yaml: additionalProperties at ""']


@pytest.mark.parametrize(
    ("relative", "change", "expected"),
    [
        ("grammar/niet-geen.yaml", {"level": PACK_VALUE}, "enum at /level"),
        ("chunks/nodig-hebben.yaml", {"key": f"fx:chunk:{PACK_VALUE}"}, "pattern at /key"),
        ("scenarios/at-the-fixture-shop.yaml", {"slot": {"node": PACK_VALUE}}, "required at /slot"),
    ],
)
def test_a_failed_rule_is_reported_by_name_and_place_without_the_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], relative: str, change: dict[str, Any], expected: str
) -> None:
    document = yaml.safe_load(fixture_text(relative)) | change
    code, lines, _err = run(capsys, str(pack(tmp_path, {relative: yaml.safe_dump(document)})))
    assert code == 1
    assert f"{relative}: {expected}" in problems(lines)


def test_a_date_that_is_not_on_the_calendar_fails_the_format_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = fixture_text("pack.yaml").replace('checked_on: "2026-11-21"', 'checked_on: "2026-13-45"')
    code, lines, _err = run(capsys, str(pack(tmp_path, {"pack.yaml": text})))
    assert code == 1
    assert problems(lines) == ["pack.yaml: format at /exams/0/checked_on"]
    assert "2026-13-45" not in "\n".join(lines)


def test_a_key_that_is_not_in_the_schema_is_left_out_of_the_place(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = fixture_text("strings/ui.yaml").replace("strings:\n", f"strings:\n  {PACK_KEY}: 5\n")
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": text})))
    assert code == 1
    assert "strings/ui.yaml: type at /strings/*" in problems(lines)


def test_a_duplicate_key_is_reported_at_its_mapping(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    strings = fixture_text("strings/ui.yaml").replace("strings:\n", f"strings:\n  {PACK_KEY}: {PACK_VALUE}\n  {PACK_KEY}: {PACK_VALUE}\n")
    chunk = fixture_text("chunks/nodig-hebben.yaml") + f"key: {PACK_VALUE}\n"
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": strings, "chunks/nodig-hebben.yaml": chunk})))
    assert code == 1
    assert sorted(problems(lines)) == [
        'chunks/nodig-hebben.yaml: duplicate-key at ""',
        "strings/ui.yaml: duplicate-key at /strings",
    ]


def test_a_merge_key_is_not_a_duplicate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = "element_names: &names\n  today: Fixture\nstrings:\n  <<: {home.title: Fixture}\n  home.title: Fixture\n"
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": text})))
    assert (code, problems(lines)) == (0, [])


def test_a_yaml_syntax_error_is_reported_by_line_and_column(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = f'element_names:\n  today: "{PACK_VALUE}\n'
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": text})))
    assert code == 1
    assert len(problems(lines)) == 1
    assert problems(lines)[0].startswith("strings/ui.yaml: yaml-syntax at line ")


def test_a_yaml_tag_that_is_not_safe_is_reported_without_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = f"element_names: !!python/object:os.system {PACK_VALUE}\n"
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": text})))
    assert code == 1
    assert problems(lines) == ["strings/ui.yaml: yaml-syntax at line 1, column 16"]


def test_a_file_that_is_not_utf_8_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = pack(tmp_path, {})
    (folder / "strings").mkdir()
    (folder / "strings" / "ui.yaml").write_bytes(b"element_names:\n  today: caf\xe9 " + PACK_VALUE.encode())
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert problems(lines) == ["strings/ui.yaml: encoding"]


def test_a_key_that_is_not_text_is_reported_at_its_mapping(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = fixture_text("strings/ui.yaml").replace("strings:\n", "strings:\n  2026: Fixture\n")
    code, lines, _err = run(capsys, str(pack(tmp_path, {"strings/ui.yaml": text})))
    assert code == 1
    assert problems(lines) == ["strings/ui.yaml: non-string-key at /strings"]


def test_a_problem_in_each_file_of_a_large_pack_leaves_no_value_in_the_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "pack"
    shutil.copytree(FIXTURE, folder)
    for path in folder.rglob("*.yaml"):
        path.write_text(path.read_text(encoding="utf-8") + f"{PACK_KEY}: [{PACK_VALUE}]\n", encoding="utf-8")
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert len(problems(lines)) == len(list(folder.rglob("*.yaml")))


@pytest.mark.parametrize(
    ("relative", "text", "expected"),
    [
        ("strings/ui.yaml", f"element_names: !!int {PACK_VALUE}\n", "yaml-value at line 1, column 16"),
        ("strings/ui.yaml", f"element_names: !!float {PACK_VALUE}\n", "yaml-value at line 1, column 16"),
        ("strings/ui.yaml", f"element_names: !!timestamp {PACK_VALUE}\n", "yaml-value at line 1, column 16"),
        ("strings/ui.yaml", "element_names:\n  today: " + "9" * 6000 + "\n", "yaml-value at line 2, column 10"),
        ("strings/ui.yaml", f"element_names:\n  today: {PACK_VALUE}\x07\n", "yaml-syntax at line 2, column 26"),
    ],
    ids=["int tag", "float tag", "timestamp tag", "long integer", "control character"],
)
def test_a_value_that_yaml_cannot_read_is_reported_by_line_and_column(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], relative: str, text: str, expected: str
) -> None:
    code, lines, _err = run(capsys, str(pack(tmp_path, {relative: text})))
    assert code == 1
    assert problems(lines) == [f"{relative}: {expected}"]
    assert lines[-1] == "Files checked: 1. Problems: 1."


@pytest.mark.parametrize("date", ["2026-13-45", "2026-02-30"])
def test_an_unquoted_date_that_is_not_on_the_calendar_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str], date: str) -> None:
    text = fixture_text("pack.yaml").replace('checked_on: "2026-11-21"', f"checked_on: {date}")
    line = text.splitlines().index(next(row for row in text.splitlines() if date in row)) + 1
    code, lines, _err = run(capsys, str(pack(tmp_path, {"pack.yaml": text})))
    assert code == 1
    assert len(problems(lines)) == 1
    assert problems(lines)[0].startswith(f"pack.yaml: yaml-value at line {line}, column ")
    assert date not in "\n".join(lines)


def test_deep_nesting_is_reported_and_the_other_files_are_checked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deep = "element_names: " + "[" * 2000 + PACK_VALUE + "]" * 2000 + "\n"
    folder = pack(tmp_path, {"strings/ui.yaml": deep, "pack.yaml": "{}\n"})
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert problems(lines) == ['pack.yaml: required at ""', "strings/ui.yaml: too-deep"]
    assert lines[-1] == "Files checked: 2. Problems: 2."


def test_deep_nesting_found_by_the_schema_check_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class TooDeep:
        def iter_errors(self, _document: Any) -> Any:
            raise RecursionError(PACK_VALUE)

    monkeypatch.setattr(validate_pack, "validator", lambda *_args: TooDeep())
    code, lines, _err = run(capsys, str(pack(tmp_path, {"pack.yaml": "{}\n"})))
    assert (code, problems(lines)) == (1, ["pack.yaml: too-deep"])


def test_an_unexpected_error_is_reported_by_its_type_without_its_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: Any) -> Any:
        raise ValueError(PACK_VALUE)

    monkeypatch.setattr(validate_pack, "check_file", fail)
    code, lines, _err = run(capsys, str(pack(tmp_path, {"x.yaml": "{}\n", "pack.yaml": "{}\n"})))
    assert code == 1
    assert lines == ["pack.yaml: internal-error-ValueError", "x.yaml: internal-error-ValueError", "Files checked: 2. Problems: 2."]


def test_a_file_that_cannot_be_read_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: Any) -> bytes:
        raise PermissionError(PACK_VALUE)

    monkeypatch.setattr(validate_pack, "read_file", refuse)
    code, lines, _err = run(capsys, str(pack(tmp_path, {"pack.yaml": "{}\n"})))
    assert (code, problems(lines)) == (1, ["pack.yaml: unreadable"])


def test_a_file_over_the_size_limit_is_reported_and_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate_pack, "MAX_FILE_BYTES", 100)
    folder = pack(tmp_path, {"strings/ui.yaml": f"element_names: [{PACK_VALUE}]\n" * 10, "pack.yaml": "# A file under the limit.\n{}\n"})
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert problems(lines) == ['pack.yaml: required at ""', "strings/ui.yaml: too-large"]


def test_the_size_limit_is_well_above_the_fixture_files() -> None:
    largest = max(path.stat().st_size for path in FIXTURE.rglob("*.yaml"))
    assert largest * 10 < validate_pack.MAX_FILE_BYTES


# --- symlinks


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks on this system")
def test_a_symlink_is_reported_by_its_path_and_not_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.yaml").write_text(f"element_names: !!int {PACK_VALUE}\n{PACK_KEY}: 1\n", encoding="utf-8")
    (outside / "lexicon").mkdir()
    (outside / "lexicon" / "hallo.yaml").write_text(f"{PACK_KEY}: {PACK_VALUE}\n", encoding="utf-8")
    folder = pack(tmp_path, {"pack.yaml": fixture_text("pack.yaml")})
    (folder / "strings").mkdir()
    (folder / "strings" / "ui.yaml").symlink_to(outside / "secret.yaml")
    (folder / "lexicon").symlink_to(outside / "lexicon", target_is_directory=True)
    (folder / "media").mkdir()
    (folder / "media" / "gone.yaml").symlink_to(tmp_path / "missing.yaml")
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert problems(lines) == ["lexicon: symlink", "media/gone.yaml: symlink", "strings/ui.yaml: symlink"]
    assert lines[-1] == "Files checked: 4. Problems: 3."


# --- file names in the output


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("notes/x\n::error::fixture-name.yaml", "notes/x\\x0a::error::fixture-name.yaml: unknown-file-type"),
        ("::add-mask::fixture-name.yaml", "./::add-mask::fixture-name.yaml: unknown-file-type"),
        (" ::warning::fixture-name.yaml", "./ ::warning::fixture-name.yaml: unknown-file-type"),
        ("notes/\x1b[2Kfixture-name.yaml", "notes/\\x1b[2Kfixture-name.yaml: unknown-file-type"),
        ("notes/a\rb\u202e.yaml", "notes/a\\x0db\\u202e.yaml: unknown-file-type"),
        ("notes/##[error]fixture-name.yaml", "notes/##\\x5berror]fixture-name.yaml: unknown-file-type"),
        ("notes/back\\slash.yaml", "notes/back\\x5cslash.yaml: unknown-file-type"),
    ],
    ids=["newline", "workflow command", "space and workflow command", "terminal escape", "carriage return", "old command", "backslash"],
)
def test_a_file_name_cannot_start_a_line_or_a_workflow_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], relative: str, expected: str
) -> None:
    folder = pack(tmp_path, {})
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text("a: 1\n", encoding="utf-8")
    except OSError:
        pytest.skip("this file system does not allow the name")
    code, lines, _err = run(capsys, str(folder))
    assert code == 1
    assert lines == [expected, "Files checked: 1. Problems: 1."]


# --- no network


def test_a_reference_outside_the_schemas_is_a_problem_not_a_download(tmp_path: Path) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    shutil.copy(ROOT / "contracts" / "pack" / "common.schema.json", schemas)
    remote = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://franca.local/spec/pack.schema.json",
        "$ref": "https://example.org/pack.schema.json",
    }
    (schemas / "pack.schema.json").write_text(json.dumps(remote), encoding="utf-8")
    folder = pack(tmp_path, {"pack.yaml": f"name: {PACK_VALUE}\n"})
    found = validate_pack.check_pack(folder, schemas)
    assert [(problem.path, problem.rule) for problem in found.problems] == [("pack.yaml", "unresolvable-ref")]


# --- how the command is run


def test_scripts_check_runs_the_command_on_the_fixture_pack() -> None:
    check = (ROOT / "scripts" / "check").read_text(encoding="utf-8")
    assert "tools/validate_pack.py ../packs/fixture" in check
    assert "../tools/validate_pack.py\n" in check
