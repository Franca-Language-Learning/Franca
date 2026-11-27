"""Checks a language pack folder against the pack schemas in contracts/pack.

The argument is the pack folder (the folder with pack.yaml), not the root of the content repository. The *.yaml files
under the folder are checked against the schema for their path (FILE_TYPES below), with the format checker, so that a
date such as 2026-13-45 is a problem. A YAML mapping with a duplicate key is a problem, and so is a key that is read as
something other than text, such as 2026 or yes. A file whose path matches no file type is reported as an unknown file
type. A *.yml or *.YAML file is reported in the same way, so that a misnamed file is not passed over. A symlink is
reported and not followed. A YAML-named entry that is not a regular file, such as a named pipe, is reported and not
opened. A file over 5 MB (MAX_FILE_BYTES) is reported as too-large and not read, and so is a file with more than a
million values (MAX_VALUES) when each alias (*name) is counted in full. The checks across files, such as keys that refer
to other files, belong to the pack builder (story E03-002) and are not made here.

The real packs are kept in the private repository Franca-Content, and this command is run on them in that
repository's pipeline. The log of that pipeline can be read by people with access to Franca-Content, who can read the
pack as well. Apart from the file paths, there is no text from the pack in the output, so a log can be shared, for
example in an issue, without sharing course text. A problem is printed as one line in the form
`<path>: <rule> at <place>`, where the path is relative to the pack folder. The place is a JSON pointer, with * in place
of a key that the schemas do not name, or for a YAML error a line and column. The error messages of jsonschema and
PyYAML quote values and lines from the file, so they are not printed, and neither is the message of an unexpected
error. The last line has the number of files checked and the number of problems.

Rule names are the JSON Schema keywords, such as required or enum, and these names for problems found outside the
schemas: duplicate-key, non-string-key, yaml-syntax, yaml-value, too-deep, too-large, encoding, unreadable, symlink,
not-a-file, unknown-file-type, unresolvable-ref and internal-error-<type>.

File paths are printed with escapes for characters that cannot be printed, such as \x0a for a new line, and with ./ in
front of a path that starts with ::, so that a file name cannot start a new line or a GitHub Actions workflow command.

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
from collections.abc import Hashable, Iterator, Sequence
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
YAML_SUFFIXES = {".yaml", ".yml"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # No pack file is near this size. A larger file is a mistake and is not read.

# The number of values in a document when each alias (*name) is counted in full. A few hundred bytes of aliases can
# stand for billions of values, and jsonschema copies a value that fails a rule into its error message, even though the
# message is not printed. A document over this limit is reported as too-large and is not checked against its schema.
MAX_VALUES = 1_000_000


@dataclass(frozen=True)
class Problem:
    """One problem in a pack file. Apart from the path, none of the fields has text from the file."""

    path: str
    rule: str
    place: str | None = None

    def __str__(self) -> str:
        return f"{shown_path(self.path)}: {self.rule}" + (f" at {self.place}" if self.place is not None else "")


def shown_path(path: str) -> str:
    """A file path as it is printed: one line that cannot be read as a GitHub Actions workflow command or a terminal code.

    A character that cannot be printed, or a backslash, is written as a Python escape such as \\x0a. The [ of ##[ is
    written as \\x5b, because the Actions runner can take ##[name] in a line as an old-style command. A path that starts with ::,
    after any spaces, has ./ in front.
    """
    shown = "".join(character if character.isprintable() and character != "\\" else escaped(character) for character in path)
    shown = shown.replace("##[", "##\\x5b")
    return "./" + shown if shown.lstrip().startswith("::") else shown


def escaped(character: str) -> str:
    code = ord(character)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"


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
    """The property names in the schemas. Other keys in a pack are pack text and are not printed."""
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
    """A JSON pointer, written as "" for the root of the document."""
    if not segments:
        return '""'
    return "".join("/" + str(segment).replace("~", "~0").replace("/", "~1") for segment in segments)


def safe_segment(key: object, names: frozenset[str]) -> str:
    return key if isinstance(key, str) and key in names else HIDDEN


def safe_path(document: Any, path: Sequence[Any], names: frozenset[str]) -> list[str | int]:
    """The path of a schema error, with * in place of a key that the schemas do not name."""
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


def line_and_column(line: int, column: int) -> str:
    """A place in a file, from a line and column counted from 0."""
    return f"line {line + 1}, column {column + 1}"


def yaml_place(error: yaml.YAMLError, text: str) -> str | None:
    """The line and column of a PyYAML error. The message of the error is not used, because it quotes the file."""
    if isinstance(error, yaml.reader.ReaderError):
        # A character that YAML does not allow, found before parsing. The error has its position in the text.
        start = text.rfind("\n", 0, error.position) + 1
        return line_and_column(text.count("\n", 0, error.position), error.position - start)
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    return None if mark is None else line_and_column(mark.line, mark.column)


class UnreadableValue(Exception):
    """A YAML value that PyYAML could not turn into a Python value, with the place of its node.

    PyYAML's constructors raise ValueError, AttributeError and others for values such as !!int abc or an unquoted
    2026-13-45. Some of those messages quote the value, so they are replaced with this error, which has the place and
    no message.
    """

    def __init__(self, mark: yaml.Mark) -> None:
        super().__init__()
        self.place = line_and_column(mark.line, mark.column)


class PackLoader(yaml.SafeLoader):
    """PyYAML's safe loader, which raises UnreadableValue in place of the errors of its constructors."""

    def construct_object(self, node: yaml.Node, deep: bool = False) -> Any:
        try:
            return super().construct_object(node, deep=deep)
        except yaml.YAMLError, RecursionError, UnreadableValue:
            raise
        except Exception:
            # Neither the message nor the type of the error is kept, because the message can quote the value.
            raise UnreadableValue(node.start_mark) from None


def key_problems(root: yaml.Node, names: frozenset[str]) -> Iterator[tuple[str, list[str | int]]]:
    """The duplicate keys and the keys that are not text in the mappings of a composed YAML document.

    They are given as rule names with the path of the mapping. A merge key (<<) is not a duplicate, because the keys
    written in the mapping take the place of the merged ones.
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


def expanded_size(root: yaml.Node) -> int:
    """The number of values in a composed YAML document, keys included, with each alias counted in full.

    The count stops at MAX_VALUES + 1. A node that contains itself, such as &a [*a], counts as MAX_VALUES + 1.
    """
    over = MAX_VALUES + 1
    sizes: dict[int, int] = {}

    def size(node: yaml.Node) -> int:
        if id(node) not in sizes:
            # Written before the children are counted, so that a node met again inside itself counts as over the limit.
            sizes[id(node)] = over
            if isinstance(node, yaml.SequenceNode):
                children = list(node.value)
            elif isinstance(node, yaml.MappingNode):
                children = [child for pair in node.value for child in pair]
            else:
                children = []
            total = 1
            for child in children:
                total = min(total + size(child), over)
            sizes[id(node)] = total
        return sizes[id(node)]

    return size(root)


# --- checking files


def load(text: str, names: frozenset[str]) -> tuple[Any, list[tuple[str, str | None]]]:
    """The document in a YAML file, or, when it cannot be read, the problems as rule names and places."""
    loader: PackLoader | None = None
    try:
        # The loader reads the text when it is made, and raises ReaderError for a character that YAML does not allow.
        loader = PackLoader(text)
        root = loader.get_single_node()
        if root is None:
            return None, []
        found = [(rule, pointer(path)) for rule, path in key_problems(root, names)]
        if found:
            return None, list(dict.fromkeys(found))
        if expanded_size(root) > MAX_VALUES:
            return None, [("too-large", None)]
        return loader.construct_document(root), []
    except yaml.YAMLError as error:
        return None, [("yaml-syntax", yaml_place(error, text))]
    except UnreadableValue as error:
        return None, [("yaml-value", error.place)]
    except RecursionError:
        return None, [("too-deep", None)]
    finally:
        if loader is not None:
            loader.dispose()


def read_file(path: Path) -> bytes:
    """The bytes of a file, up to one byte over MAX_FILE_BYTES, so that a large file is not read into memory."""
    with path.open("rb") as file:
        return file.read(MAX_FILE_BYTES + 1)


def check_file(path: Path, relative: str, schemas: Path) -> list[Problem]:
    if path.is_symlink():
        # A symlink can point outside the pack, so it is not read.
        return [Problem(relative, "symlink")]
    if not path.is_file():
        # A named pipe, socket or device file. It is not opened, because opening a named pipe waits for a writer.
        return [Problem(relative, "not-a-file")]
    schema = schema_for(relative)
    if schema is None:
        return [Problem(relative, "unknown-file-type")]
    try:
        data = read_file(path)
    except OSError:
        return [Problem(relative, "unreadable")]
    if len(data) > MAX_FILE_BYTES:
        return [Problem(relative, "too-large")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Problem(relative, "encoding")]
    names = schema_names(schemas)
    document, found = load(text, names)
    if found:
        return [Problem(relative, rule, place) for rule, place in found]
    try:
        # Some errors have the same line, for example the "required" errors for two missing properties. The line is
        # printed once.
        errors = validator(schema, schemas).iter_errors(document)
        return unique(
            Problem(relative, str(error.validator), pointer(safe_path(document, list(error.absolute_path), names))) for error in errors
        )
    except Unresolvable:
        return [Problem(relative, "unresolvable-ref")]
    except RecursionError:
        return [Problem(relative, "too-deep")]


def unique[T: Hashable](items: Iterator[T]) -> list[T]:
    return list(dict.fromkeys(items))


def pack_files(folder: Path) -> list[Path]:
    """The YAML-named entries in a pack folder that are not folders, and any symlinks, whatever their names.

    Symlinked folders are not entered.
    """
    return sorted(path for path in folder.rglob("*") if path.is_symlink() or (path.suffix.lower() in YAML_SUFFIXES and not path.is_dir()))


def check_pack(folder: Path, schemas: Path = SCHEMAS) -> Report:
    files = pack_files(folder)
    problems: list[Problem] = []
    for path in files:
        relative = path.relative_to(folder).as_posix()
        try:
            problems.extend(check_file(path, relative, schemas))
        except Exception as error:
            # The message of an unexpected error can quote the file, so only the name of its type is printed.
            problems.append(Problem(relative, f"internal-error-{type(error).__name__}"))
    return Report(len(files), problems)


def main(arguments: Sequence[str]) -> int:
    if len(arguments) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    folder = Path(arguments[0])
    if not folder.is_dir():
        print(f"{shown_path(arguments[0])} is not a folder.\n\n{USAGE}", file=sys.stderr)
        return 2
    report = check_pack(folder)
    for problem in report.problems:
        print(problem)
    print(report.summary())
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
