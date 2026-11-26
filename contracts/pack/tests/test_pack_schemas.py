"""Tests for the pack schemas (story E03-001).

Each file type in a language pack has a JSON Schema in contracts/pack. The made-up pack in packs/fixture has an example
of every file type, and every example has to pass its schema. The lists of allowed values in the schemas have to match
the CHECK constraints of the tables that the pack is imported into (contracts/db/schema.sql), so that a file that passes
its schema can also be imported.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "pack"
FIXTURE = ROOT / "packs" / "fixture"
DATABASE = (ROOT / "contracts" / "db" / "schema.sql").read_text(encoding="utf-8")

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


def load_schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return loaded


def registry() -> Registry[Any]:
    """All pack schemas, so that one schema can refer to the shared definitions in another."""
    resources = [(load_schema(path.name)["$id"], Resource.from_contents(load_schema(path.name))) for path in SCHEMAS.glob("*.schema.json")]
    return Registry().with_resources(resources)


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name), registry=registry())


def schema_for(relative: str) -> str | None:
    return next((schema for pattern, schema in FILE_TYPES if re.fullmatch(pattern, relative)), None)


def fixture_files() -> list[Path]:
    return sorted(path for path in FIXTURE.rglob("*.yaml"))


def errors(name: str, document: Any) -> list[str]:
    return [f"{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in validator(name).iter_errors(document)]


def check_values(table: str, column: str) -> set[str]:
    """The values that a CHECK (column IN (...)) constraint of a table allows."""
    body = re.search(rf"CREATE TABLE {table} \((.*?)\n\) STRICT", DATABASE, re.DOTALL)
    assert body, f"table {table} is not in schema.sql"
    found = re.search(rf"\b{column}\s+TEXT[^\n]*?CHECK \((?:{column} IS NULL OR )?{column} IN \(([^)]*)\)", body.group(1), re.DOTALL)
    assert found, f"{table}.{column} has no CHECK ... IN (...) list"
    return set(re.findall(r"'([^']*)'", found.group(1)))


def enum_at(schema: dict[str, Any], pointer: str) -> set[str]:
    node: Any = schema
    for part in pointer.strip("/").split("/"):
        node = node[part]
    values: list[str] = node["enum"]
    return set(values)


# --- the schemas themselves


@pytest.mark.parametrize("path", sorted(SCHEMAS.glob("*.schema.json")), ids=lambda path: path.name)
def test_each_schema_is_a_valid_json_schema_with_an_id(path: Path) -> None:
    schema = load_schema(path.name)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == f"https://franca.local/spec/{path.name}"


def test_every_file_type_named_in_the_acceptance_criteria_has_a_schema() -> None:
    # pack.yaml, lexicon, chunks, grammar, sounds, scenarios, course, media refs, strings.
    named = {schema for _pattern, schema in FILE_TYPES}
    assert named <= {path.name for path in SCHEMAS.glob("*.schema.json")}


# --- the fixture pack


@pytest.mark.parametrize("path", fixture_files(), ids=lambda path: str(path.relative_to(FIXTURE)))
def test_each_fixture_file_passes_its_schema(path: Path) -> None:
    relative = str(path.relative_to(FIXTURE))
    schema = schema_for(relative)
    assert schema, f"{relative} is not a known pack file type"
    assert errors(schema, yaml.safe_load(path.read_text(encoding="utf-8"))) == []


def test_the_fixture_pack_has_an_example_of_every_file_type() -> None:
    used = {schema_for(str(path.relative_to(FIXTURE))) for path in fixture_files()}
    assert used == {schema for _pattern, schema in FILE_TYPES}


# --- mistakes the schemas catch


def fixture(relative: str) -> Any:
    return yaml.safe_load((FIXTURE / relative).read_text(encoding="utf-8"))


def test_an_unknown_field_is_refused() -> None:
    lexeme = fixture("lexicon/zakje.yaml") | {"colour": "blue"}
    assert errors("lexeme.schema.json", lexeme)


def test_a_key_with_capital_letters_is_refused() -> None:
    chunk = fixture("chunks/nodig-hebben.yaml") | {"key": "fx:chunk:Nodig-Hebben"}
    assert errors("chunk.schema.json", chunk)


def test_a_level_that_does_not_exist_is_refused() -> None:
    grammar = fixture("grammar/niet-geen.yaml") | {"level": "a3"}
    assert errors("grammar-point.schema.json", grammar)


def test_a_media_file_needs_a_full_sha256_and_a_licence() -> None:
    media = fixture("media/fixture-greeting.yaml")
    assert errors("media.schema.json", media | {"sha256": "abc123"})
    assert errors("media.schema.json", {key: value for key, value in media.items() if key != "licence"})


def test_a_recorded_pronunciation_names_its_speaker() -> None:
    lexeme = fixture("lexicon/zakje.yaml")
    recorded = {"variety": "fx-north", "media": "a" * 64}
    assert errors("lexeme.schema.json", lexeme | {"pronunciations": [recorded]})


def test_a_pronunciation_has_a_transcription_or_a_recording() -> None:
    lexeme = fixture("lexicon/zakje.yaml")
    assert errors("lexeme.schema.json", lexeme | {"pronunciations": [{"variety": "fx-north"}]})


def test_a_form_that_does_not_exist_has_no_spelling() -> None:
    verb = fixture("lexicon/hebben.yaml")
    verb["forms"] = [{"cell": "past.sg", "nonexistent": True, "form": "fixture"}]
    assert errors("lexeme.schema.json", verb)


def test_a_lesson_node_is_written_as_a_lesson_file_not_a_node_file() -> None:
    node = fixture("course/a1-u05.node.yaml") | {"type": "lesson"}
    assert errors("course-node.schema.json", node)


def test_a_scenario_slot_needs_both_its_node_and_its_number() -> None:
    scenario = fixture("scenarios/at-the-fixture-shop.yaml")
    scenario["slot"] = {"node": "fx:unit:a1-u05"}
    assert errors("scenario.schema.json", scenario)


def test_a_transcript_line_ends_after_it_starts_is_checked_by_the_builder() -> None:
    # JSON Schema cannot compare two fields. The pack builder (E03-002) checks end_ms > start_ms; the schema checks
    # that both are there and not negative.
    media = fixture("media/fixture-greeting.yaml")
    media["transcript"][0]["start_ms"] = -1
    assert errors("media.schema.json", media)


def test_an_interface_string_key_has_the_database_form() -> None:
    strings = fixture("strings/ui.yaml")
    strings["strings"]["Not A Key"] = "Fixture"
    assert errors("strings.schema.json", strings)


# --- the schemas and the database agree


COMMON = load_schema("common.schema.json")["$defs"]


@pytest.mark.parametrize(
    ("definition", "table", "column"),
    [
        ("level", "catalogue_lexeme_v", "level"),
        ("register", "catalogue_sense_v", "register"),
        ("review_status", "catalogue_lexeme_v", "review_status"),
        ("upos", "catalogue_lexeme_v", "upos"),
        ("mime", "catalogue_media_asset", "mime"),
        ("rights_scope", "catalogue_media_asset", "rights_scope"),
    ],
)
def test_shared_lists_match_the_database(definition: str, table: str, column: str) -> None:
    assert set(COMMON[definition]["enum"]) == check_values(table, column)


@pytest.mark.parametrize(
    ("schema", "pointer", "table", "column"),
    [
        ("grammar-point.schema.json", "/$defs/explanation/properties/depth", "catalogue_explanation_v", "depth"),
        ("grammar-point.schema.json", "/$defs/explanation/properties/section", "catalogue_explanation_v", "section"),
        ("grammar-point.schema.json", "/$defs/rule/properties/type", "catalogue_rule_v", "rule_type"),
        ("course-node.schema.json", "/properties/type", "catalogue_course_node_v", "node_type"),
        ("can-do.schema.json", "/properties/activity", "catalogue_can_do_v", "activity"),
        ("can-do.schema.json", "/$defs/component", "catalogue_can_do_component_v", "component"),
        ("scenario.schema.json", "/properties/register", "catalogue_scenario_v", "register"),
        ("pack.schema.json", "/properties/direction", "catalogue_pack", "direction"),
        ("pack.schema.json", "/$defs/speaker/properties/voice", "catalogue_speaker_v", "voice_kind"),
        ("lexeme.schema.json", "/$defs/verb/properties/subject", "catalogue_verb_v", "subject"),
        ("sound.schema.json", "/$defs/recording/properties/side", "catalogue_minimal_pair_audio_v", "side"),
    ],
)
def test_lists_in_the_file_schemas_match_the_database(schema: str, pointer: str, table: str, column: str) -> None:
    # The course-node schema has no lesson: lessons are lesson files.
    allowed = check_values(table, column) - ({"lesson"} if column == "node_type" else set())
    assert enum_at(load_schema(schema), pointer) == allowed
