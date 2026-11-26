"""Tests for the pack schemas (story E03-001).

Each file type in a language pack has a JSON Schema in contracts/pack. The made-up pack in packs/fixture has an example
of every file type, and every example has to pass its schema. The lists of allowed values in the schemas have to match
the CHECK constraints in contracts/db/schema.sql and the reference data in contracts/db/seed.sql, so that a file that
passes its schema can also be imported.
"""

import json
import re
from functools import cache
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
SEED = (ROOT / "contracts" / "db" / "seed.sql").read_text(encoding="utf-8")

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


@cache
def load_schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return loaded


@cache
def registry() -> Registry[Any]:
    """All pack schemas, so that one schema can refer to the shared definitions in another."""
    resources = [(load_schema(path.name)["$id"], Resource.from_contents(load_schema(path.name))) for path in SCHEMAS.glob("*.schema.json")]
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Draft202012Validator:
    # With the format checker, "format": "date" is checked as a calendar date. "format": "uri" stays a note, because
    # rfc3987 is not installed, and a pattern is used for it instead.
    return Draft202012Validator(load_schema(name), registry=registry(), format_checker=Draft202012Validator.FORMAT_CHECKER)


def schema_for(relative: str) -> str | None:
    return next((schema for pattern, schema in FILE_TYPES if re.fullmatch(pattern, relative)), None)


def fixture_files() -> list[Path]:
    return sorted(path for path in FIXTURE.rglob("*.yaml"))


def errors(name: str, document: Any) -> set[tuple[str, str]]:
    """The place and the failed keyword of each error, for example ("pronunciations/0", "dependentRequired")."""
    found = set()
    for error in validator(name).iter_errors(document):
        for leaf in error.context or [error]:
            found.add(("/".join(map(str, leaf.absolute_path)), str(leaf.validator)))
        found.add(("/".join(map(str, error.absolute_path)), str(error.validator)))
    return found


def check_values(table: str, column: str) -> set[str]:
    """The values that a CHECK (column IN (...)) constraint of a table allows."""
    body = re.search(rf"CREATE TABLE {table} \((.*?)\n\) STRICT", DATABASE, re.DOTALL)
    assert body, f"table {table} is not in schema.sql"
    found = re.search(rf"\b{column}\s+TEXT[^\n]*?CHECK \((?:{column} IS NULL OR )?{column} IN \(([^)]*)\)", body.group(1), re.DOTALL)
    assert found, f"{table}.{column} has no CHECK ... IN (...) list"
    return set(re.findall(r"'([^']*)'", found.group(1)))


def seed_values(table: str) -> set[str]:
    """The keys (first column) of the reference data that contracts/db/seed.sql inserts into a table."""
    rows = re.search(rf"INSERT INTO {table} \([^)]*\) VALUES\n(.*?);\n", SEED, re.DOTALL)
    assert rows, f"seed.sql inserts nothing into {table}"
    return set(re.findall(r"^\s*\('([^']*)'", rows.group(1), re.MULTILINE))


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


# The file types that the acceptance criteria of E03-001 name, and the schema for each.
ACCEPTANCE = {
    "pack.yaml": "pack.schema.json",
    "lexicon": "lexeme.schema.json",
    "chunks": "chunk.schema.json",
    "grammar": "grammar-point.schema.json",
    "sounds": "sound.schema.json",
    "scenarios": "scenario.schema.json",
    "course": "course-node.schema.json",
    "media refs": "media.schema.json",
    "strings": "strings.schema.json",
}


@pytest.mark.parametrize(("file_type", "schema"), ACCEPTANCE.items())
def test_each_file_type_in_the_acceptance_criteria_has_a_schema_that_is_used(file_type: str, schema: str) -> None:
    assert (SCHEMAS / schema).is_file(), file_type
    assert schema in {used for _pattern, used in FILE_TYPES}, file_type


# --- the fixture pack


@pytest.mark.parametrize("path", fixture_files(), ids=lambda path: str(path.relative_to(FIXTURE)))
def test_each_fixture_file_passes_its_schema(path: Path) -> None:
    relative = str(path.relative_to(FIXTURE))
    schema = schema_for(relative)
    assert schema, f"{relative} is not a known pack file type"
    assert errors(schema, yaml.safe_load(path.read_text(encoding="utf-8"))) == set()


def test_the_fixture_pack_has_an_example_of_every_file_type() -> None:
    used = {schema_for(str(path.relative_to(FIXTURE))) for path in fixture_files()}
    assert used == {schema for _pattern, schema in FILE_TYPES}


# --- mistakes the schemas catch


def fixture(relative: str) -> Any:
    return yaml.safe_load((FIXTURE / relative).read_text(encoding="utf-8"))


def without(document: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in document.items() if name != key}


def test_an_unknown_field_is_refused() -> None:
    lexeme = fixture("lexicon/zakje.yaml") | {"colour": "blue"}
    assert ("", "additionalProperties") in errors("lexeme.schema.json", lexeme)


def test_a_key_with_capital_letters_is_refused() -> None:
    chunk = fixture("chunks/nodig-hebben.yaml") | {"key": "fx:chunk:Nodig-Hebben"}
    assert ("key", "pattern") in errors("chunk.schema.json", chunk)


def test_a_key_too_long_for_a_suffix_is_refused() -> None:
    lexeme = fixture("lexicon/zakje.yaml") | {"key": "fx:lexeme:" + "a" * 130}
    assert ("key", "maxLength") in errors("lexeme.schema.json", lexeme)


def test_a_level_that_does_not_exist_is_refused() -> None:
    grammar = fixture("grammar/niet-geen.yaml") | {"level": "a3"}
    assert ("level", "enum") in errors("grammar-point.schema.json", grammar)


def test_a_pack_needs_a_version_of_three_numbers() -> None:
    pack = fixture("pack.yaml")
    assert ("", "required") in errors("pack.schema.json", without(pack, "version"))
    assert ("version", "pattern") in errors("pack.schema.json", pack | {"version": "1.0"})


def test_a_goal_that_the_app_does_not_have_is_refused() -> None:
    pack = fixture("pack.yaml")
    pack["goals"][0]["key"] = "daily_life"
    assert ("goals/0/key", "enum") in errors("pack.schema.json", pack)
    node = fixture("course/a1-u05.node.yaml") | {"goals": {"daily_life": 1}}
    assert ("goals", "enum") in errors("course-node.schema.json", node)


def test_an_exam_date_that_is_not_a_date_is_refused() -> None:
    pack = fixture("pack.yaml")
    pack["exams"][0]["checked_on"] = "last tuesday"
    assert ("exams/0/checked_on", "pattern") in errors("pack.schema.json", pack)


def test_an_exam_date_that_is_not_on_the_calendar_is_refused() -> None:
    pack = fixture("pack.yaml")
    pack["exams"][0]["checked_on"] = "2026-13-45"
    assert ("exams/0/checked_on", "format") in errors("pack.schema.json", pack)


def test_an_exam_address_that_is_not_a_web_address_is_refused() -> None:
    pack = fixture("pack.yaml")
    pack["exams"][0]["url"] = "https://exa mple.org/"
    assert ("exams/0/url", "pattern") in errors("pack.schema.json", pack)


def test_the_same_confusable_pair_twice_is_refused() -> None:
    pack = fixture("pack.yaml")
    pack["confusable_pairs"].append(pack["confusable_pairs"][0])
    assert ("confusable_pairs", "uniqueItems") in errors("pack.schema.json", pack)


def test_a_media_file_needs_a_full_sha256_and_a_licence_from_the_list() -> None:
    media = fixture("media/fixture-greeting.yaml")
    assert ("sha256", "pattern") in errors("media.schema.json", media | {"sha256": "abc123"})
    assert ("", "required") in errors("media.schema.json", without(media, "licence"))
    assert ("licence", "enum") in errors("media.schema.json", media | {"licence": "all-rights-mine"})


def test_a_file_under_a_private_licence_is_kept_private() -> None:
    media = fixture("media/fixture-greeting.yaml") | {"licence": "owned-copy", "rights_scope": "shareable"}
    assert ("rights_scope", "const") in errors("media.schema.json", media)


def test_the_private_licences_are_the_ones_the_database_does_not_share() -> None:
    rows = re.search(r"INSERT INTO catalogue_licence \([^)]*\) VALUES\n(.*?);\n", SEED, re.DOTALL)
    assert rows
    not_shareable = set(re.findall(r"^\s*\('([^']*)'.*, 0\),?$", rows.group(1), re.MULTILINE))
    rule = load_schema("media.schema.json")["allOf"][1]
    assert set(rule["if"]["properties"]["licence"]["enum"]) == not_shareable


def test_a_picture_has_no_transcript() -> None:
    picture = fixture("media/fixture-bag-picture.yaml") | {"transcript": [{"start_ms": 0, "end_ms": 1, "text_tl": "x"}]}
    assert ("", "not") in errors("media.schema.json", picture)


def test_a_negative_start_time_is_refused() -> None:
    media = fixture("media/fixture-greeting.yaml")
    media["transcript"][0]["start_ms"] = -1
    assert ("transcript/0/start_ms", "minimum") in errors("media.schema.json", media)


def test_a_recorded_pronunciation_names_its_speaker() -> None:
    lexeme = fixture("lexicon/zakje.yaml") | {"pronunciations": [{"variety": "fx-north", "media": "a" * 64}]}
    assert ("pronunciations/0", "dependentRequired") in errors("lexeme.schema.json", lexeme)


def test_a_pronunciation_has_a_transcription_or_a_recording() -> None:
    lexeme = fixture("lexicon/zakje.yaml") | {"pronunciations": [{"variety": "fx-north"}]}
    assert ("pronunciations/0", "anyOf") in errors("lexeme.schema.json", lexeme)


def test_a_form_that_does_not_exist_has_no_spelling() -> None:
    verb = fixture("lexicon/hebben.yaml") | {"forms": [{"cell": "imperative", "nonexistent": True, "form": "fixture"}]}
    assert ("forms/0", "not") in errors("lexeme.schema.json", verb)


def test_verb_details_are_for_verbs_only() -> None:
    noun = fixture("lexicon/zakje.yaml") | {"verb": fixture("lexicon/hebben.yaml")["verb"]}
    assert ("", "not") in errors("lexeme.schema.json", noun)


def test_a_checker_rule_with_a_misspelt_field_is_refused() -> None:
    grammar = fixture("grammar/niet-geen.yaml")
    grammar["checker_rules"][0]["stpe"] = "ng-1"
    assert ("checker_rules/0", "additionalProperties") in errors("grammar-point.schema.json", grammar)


def test_a_checker_rule_names_an_error_type_from_the_list() -> None:
    grammar = fixture("grammar/niet-geen.yaml")
    grammar["checker_rules"][0]["error_type"] = "negation_choice"
    assert ("checker_rules/0/error_type", "enum") in errors("grammar-point.schema.json", grammar)


def test_a_sound_has_its_transcription_and_a_contrast_has_its_pairs() -> None:
    sound = fixture("sounds/ui.yaml")
    assert ("", "required") in errors("sound.schema.json", without(sound, "ipa"))
    contrast = fixture("sounds/ui-uu.yaml")
    assert ("", "required") in errors("sound.schema.json", without(contrast, "minimal_pairs"))
    assert ("", "unevaluatedProperties") in errors("sound.schema.json", contrast | {"ipa": "y"})


def test_a_lesson_node_is_written_as_a_lesson_file_not_a_node_file() -> None:
    node = fixture("course/a1-u05.node.yaml") | {"type": "lesson"}
    assert ("type", "enum") in errors("course-node.schema.json", node)


def test_a_node_key_names_the_type_of_the_node() -> None:
    node = fixture("course/a1-u05.node.yaml") | {"key": "fx:level:a1-u05"}
    assert ("key", "pattern") in errors("course-node.schema.json", node)


def test_a_level_has_no_parent_and_other_nodes_have_one() -> None:
    level = fixture("course/a1.node.yaml") | {"parent": "fx:level:a2"}
    assert ("", "not") in errors("course-node.schema.json", level)
    unit = without(fixture("course/a1-u05.node.yaml"), "parent")
    assert ("", "required") in errors("course-node.schema.json", unit)


def test_module_fields_are_for_domain_modules_only() -> None:
    unit = fixture("course/a1-u05.node.yaml") | {"module": {"terminology_from": "a2", "tasks_from": "b1"}}
    assert ("", "not") in errors("course-node.schema.json", unit)
    module = fixture("course/a1-u05.node.yaml") | {"key": "fx:module:health", "type": "module"}
    assert ("", "required") in errors("course-node.schema.json", module)


def test_a_can_do_component_that_does_not_exist_is_refused() -> None:
    can_do = fixture("course/a1-shop.can-do.yaml")
    can_do["components"]["charm"] = [{"item": "fx:lexeme:zakje"}]
    assert ("components", "enum") in errors("can-do.schema.json", can_do)


def test_a_scenario_slot_needs_both_its_node_and_its_number() -> None:
    scenario = fixture("scenarios/at-the-fixture-shop.yaml") | {"slot": {"node": "fx:unit:a1-u05"}}
    assert ("slot", "required") in errors("scenario.schema.json", scenario)


def test_a_scenario_is_not_written_in_a_vulgar_register() -> None:
    scenario = fixture("scenarios/at-the-fixture-shop.yaml") | {"register": "vulgar"}
    assert ("register", "enum") in errors("scenario.schema.json", scenario)


def test_an_interface_string_key_has_the_database_form() -> None:
    strings = fixture("strings/ui.yaml")
    strings["strings"]["Not A Key"] = "Fixture"
    assert ("strings", "pattern") in errors("strings.schema.json", strings)


def test_an_element_name_is_for_an_element_the_app_has() -> None:
    strings = fixture("strings/ui.yaml")
    strings["element_names"]["warm_up"] = "Fixture"
    assert ("element_names", "enum") in errors("strings.schema.json", strings)


def test_an_empty_strings_file_is_refused() -> None:
    assert ("", "minProperties") in errors("strings.schema.json", {})


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
    ("definition", "table"),
    [
        ("licence", "catalogue_licence"),
        ("goal_key", "study_goal"),
        ("ui_element", "catalogue_ui_element"),
        ("error_type", "catalogue_error_type"),
    ],
)
def test_shared_lists_match_the_reference_data(definition: str, table: str) -> None:
    assert set(COMMON[definition]["enum"]) == seed_values(table)


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
