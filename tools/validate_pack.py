"""Checks a language pack folder against the pack schemas in contracts/pack.

The *.yaml files under the folder are checked against the schema for their path (FILE_TYPES below), with the format
checker, so that a date such as 2026-13-45 is a problem. A YAML mapping with a duplicate key is a problem, and so is a
key that YAML reads as something other than text, such as 2026 or yes. A file whose path matches no file type is
reported as an unknown file type. A *.yml file is reported in the same way, so that a misnamed file is not passed over.
The checks across files, such as keys that refer to other files, belong to the pack builder (story E03-002) and are not
made here.

The real packs are kept in the private repository Franca-Content, and this command is run on them in that
repository's pipeline. More people can read the log of that pipeline than the pack, so there is no text from the pack
in the output. A problem is printed as one line with the file path relative to the pack folder, the name of the failed
rule and the place in the file. The place is a JSON pointer, with * in place of a key that the schemas do not name, or
for a YAML error a line and column. The error messages of jsonschema and PyYAML quote values and lines from the file,
so they are not printed. The last line has the number of files checked and the number of problems.

Exit codes: 0 when there are no problems, 1 when there are problems, 2 for a usage error.

There is no network access. The schemas are read from contracts/pack in the same checkout, and a $ref to a schema that
is not there is reported as a problem (unresolvable-ref). Nothing is downloaded.

The packages it needs are in the server's locked environment. From the root of a checkout of this repository:

    uv run --project server --frozen --no-dev python -I tools/validate_pack.py <pack folder>

From another repository, with this repository checked out in the folder franca:

    uv run --project franca/server --frozen --no-dev python -I franca/tools/validate_pack.py <pack folder>

uv installs the versions in uv.lock at the root of the checkout, and installs Python 3.14 if it is not there. The
steps for a workflow are in contracts/pack/README.md.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

SCHEMAS = Path(__file__).resolve().parents[1] / "contracts" / "pack"

# Which schema each file in a pack follows, by its path in the pack. The first matching pattern is used.
FILE_TYPES = [
    (r"pack\.yaml", "pack.schema.json"),
    (r"course-config\.yaml", "course-config.schema.json"),
    (r"lexicon/[a-z0-9-]+\.yaml", "lexeme.schema.json"),
    (r"chunks/[a-z0-9-]+\.yaml", "chunk.schema.json"),
    (r"grammar/[a-z0-9-]+\.yaml", "grammar-point.schema.json"),
    (r"sounds/[a-z0-9-]+\.yaml", "sound.schema.json"),
    (r"scenarios/[a-z0-9-]+\.yaml", "scenario.schema.json"),
    (r"course/[a-z0-9-]+\.lesson\.yaml", "lesson.schema.json"),
    (r"course/[a-z0-9-]+\.node\.yaml", "course-node.schema.json"),
    (r"course/[a-z0-9-]+\.can-do\.yaml", "can-do.schema.json"),
    (r"media/[a-z0-9-]+\.yaml", "media.schema.json"),
    (r"strings/[a-z0-9-]+\.yaml", "strings.schema.json"),
]

USAGE = """Usage: validate_pack.py <pack folder>

Run it with the locked packages of the server, from the root of a checkout:
    uv run --project server --frozen --no-dev python -I tools/validate_pack.py <pack folder>"""

STRING_TAG = "tag:yaml.org,2002:str"
MERGE_TAG = "tag:yaml.org,2002:merge"
HIDDEN = "*"


@dataclass(frozen=True)
class Problem:
    """One problem in a pack file. None of the fields has text from the file."""

    path: str
    rule: str
    place: str | None = None

    def __str__(self) -> str:
        return f"{self.path}: {self.rule}" + (f" at {self.place}" if self.place is not None else "")


@dataclass(frozen=True)
class Report:
    files: int
    problems: list[Problem]

    def summary(self) -> str:
        return f"Files checked: {self.files}. Problems: {len(self.problems)}."


# --- the schemas


@cache
def load_schema(name: str, schemas: Path = SCHEMAS) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((schemas / name).read_text(encoding="utf-8"))
    return loaded


@cache
def registry(schemas: Path = SCHEMAS) -> Registry[Any]:
    """All pack schemas, so that one schema can refer to the shared definitions in another.

    The registry has no function to retrieve other schemas, so a $ref to a schema that is not in the folder raises
    referencing.exceptions.Unresolvable and nothing is downloaded.
    """
    names = sorted(path.name for path in schemas.glob("*.schema.json"))
    resources = [(load_schema(name, schemas)["$id"], Resource.from_contents(load_schema(name, schemas))) for name in names]
    return Registry().with_resources(resources)


@cache
def validator(name: str, schemas: Path = SCHEMAS) -> Draft202012Validator:
    # With the format checker, "format": "date" is checked as a calendar date. "format": "uri" stays a note, because
    # rfc3987 is not installed, and a pattern is used for it instead.
    return Draft202012Validator(load_schema(name, schemas), registry=registry(schemas), format_checker=Draft202012Validator.FORMAT_CHECKER)


def schema_for(relative: str) -> str | None:
    """The schema for a file, by its path in the pack with / between folders, or None for an unknown file type."""
    return next((schema for pattern, schema in FILE_TYPES if re.fullmatch(pattern, relative)), None)


@cache
def schema_names(schemas: Path = SCHEMAS) -> frozenset[str]:
    """The property names that the schemas name. Other keys in a pack are pack text and are not printed."""
    names: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for keyword in ("properties", "dependentRequired", "dependentSchemas"):
                if isinstance(node.get(keyword), dict):
                    names.update(node[keyword])
            if isinstance(node.get("required"), list):
                names.update(name for name in node["required"] if isinstance(name, str))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for path in schemas.glob("*.schema.json"):
        collect(load_schema(path.name, schemas))
    return frozenset(names)


# --- places in a file


def pointer(segments: Sequence[str | int]) -> str:
    """A JSON pointer, written as "" for the whole document."""
    if not segments:
        return '""'
    return "".join("/" + str(segment).replace("~", "~0").replace("/", "~1") for segment in segments)


def safe_segment(key: object, names: frozenset[str]) -> str:
    return key if isinstance(key, str) and key in names else HIDDEN


def safe_path(document: Any, path: Sequence[Any], names: frozenset[str]) -> list[str | int]:
    """The path of a schema error, with * in place of each key that the schemas do not name."""
    segments: list[str | int] = []
    node = document
    for step in path:
        if isinstance(node, list) and isinstance(step, int):
            segments.append(step)
            node = node[step] if 0 <= step < len(node) else None
        else:
            segments.append(safe_segment(step, names))
            node = node.get(step) if isinstance(node, dict) else None
    return segments


def yaml_place(error: yaml.YAMLError) -> str | None:
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    return None if mark is None else f"line {mark.line + 1}, column {mark.column + 1}"


def key_problems(root: yaml.Node, names: frozenset[str]) -> Iterator[tuple[str, list[str | int]]]:
    """The duplicate keys and the keys that are not text in the mappings of a composed YAML document.

    Each is given as a rule name and the path of the mapping. A merge key (<<) is not a duplicate: the keys written in
    the mapping take the place of the merged ones.
    """
    seen: set[int] = set()

    def walk(node: yaml.Node, path: list[str | int]) -> Iterator[tuple[str, list[str | int]]]:
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                yield from walk(item, [*path, index])
        elif isinstance(node, yaml.MappingNode):
            keys: set[str] = set()
            for key_node, value_node in node.value:
                if key_node.tag == MERGE_TAG:
                    yield from walk(value_node, path)
                elif not isinstance(key_node, yaml.ScalarNode) or key_node.tag != STRING_TAG:
                    yield "non-string-key", path
                elif key_node.value in keys:
                    yield "duplicate-key", path
                else:
                    keys.add(key_node.value)
                    yield from walk(value_node, [*path, safe_segment(key_node.value, names)])

    yield from walk(root, [])


# --- checking files


def load(text: str, names: frozenset[str]) -> tuple[Any, list[tuple[str, str | None]]]:
    """The document in a YAML file, or the problems that stop it from being read, as rule names and places."""
    loader = yaml.SafeLoader(text)
    try:
        root = loader.get_single_node()
        if root is None:
            return None, []
        found = [(rule, pointer(path)) for rule, path in key_problems(root, names)]
        if found:
            return None, list(dict.fromkeys(found))
        return loader.construct_document(root), []
    except yaml.YAMLError as error:
        return None, [("yaml-syntax", yaml_place(error))]
    finally:
        loader.dispose()


def check_file(path: Path, relative: str, schemas: Path) -> list[Problem]:
    schema = schema_for(relative)
    if schema is None:
        return [Problem(relative, "unknown-file-type")]
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [Problem(relative, "encoding")]
    names = schema_names(schemas)
    document, found = load(text, names)
    if found:
        return [Problem(relative, rule, place) for rule, place in found]
    try:
        # Several errors can give the same line, such as one "required" error for each missing property. The line is
        # printed once.
        errors = validator(schema, schemas).iter_errors(document)
        return list(
            dict.fromkeys(
                Problem(relative, str(error.validator), pointer(safe_path(document, list(error.absolute_path), names))) for error in errors
            )
        )
    except Unresolvable:
        return [Problem(relative, "unresolvable-ref")]


def pack_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*") if path.suffix in {".yaml", ".yml"} and path.is_file())


def check_pack(folder: Path, schemas: Path = SCHEMAS) -> Report:
    files = pack_files(folder)
    problems = [problem for path in files for problem in check_file(path, path.relative_to(folder).as_posix(), schemas)]
    return Report(len(files), problems)


def main(arguments: Sequence[str]) -> int:
    if len(arguments) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    folder = Path(arguments[0])
    if not folder.is_dir():
        print(f"{arguments[0]} is not a folder.\n\n{USAGE}", file=sys.stderr)
        return 2
    report = check_pack(folder)
    for problem in report.problems:
        print(problem)
    print(report.summary())
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
