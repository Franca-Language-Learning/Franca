"""Build schema.sql from tables.sql.

Run with:  python build_schema.py
Check with: python build_schema.py --check   (exit code 1 if schema.sql is out of date)

Steps:
1. Expand the column macros (@TS, @DAY, @TIME, @BOOL, @SHA, @LEVEL, @UUID).
2. Load the tables into an in-memory database and find every pack-content
   table (name ending in _v).
3. Generate:
   * catalogue_version_media, a view of every media hash used in a pack version;
   * catalogue_version_item, a view of every item described in a pack version;
   * three triggers per content table, so that rows can be added or changed only
     while their pack version is importing, and cannot be deleted while it is active;
   * triggers that refuse an item or variety from another pack, or an item of the wrong kind.
4. Write schema.sql with the generated part at the @GENERATED marker.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "tables.sql"
TARGET = HERE / "schema.sql"
MARKER = "-- @GENERATED"

# Tables that describe one kind of item, and the kind they describe.
ENTITY_KIND = {
    "catalogue_course_node_v": "course_node",
    "catalogue_activity_v": "activity",
    "catalogue_lexeme_v": "lexeme",
    "catalogue_sense_v": "sense",
    "catalogue_chunk_v": "chunk",
    "catalogue_grammar_point_v": "grammar_point",
    "catalogue_rule_v": "rule",
    "catalogue_rule_step_v": "rule_step",
    "catalogue_sound_v": "sound",
    "catalogue_sound_contrast_v": "sound_contrast",
    "catalogue_can_do_v": "can_do",
    "catalogue_scenario_v": "scenario",
}
# Tables keyed like an item table that add fields to another one (a lesson or module is a course node).
SUBTYPE_TABLES = {"catalogue_lesson_v", "catalogue_module_v"}

LEVELS = ("orientation", "pre-a1", "a1", "a2", "b1", "b2", "c1", "c2", "professional")

MACROS = {
    "TS": "CHECK ({c} IS NULL OR ({c} GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9].[0-9][0-9][0-9]Z' AND strftime('%Y-%m-%dT%H:%M:%fZ', {c}) = {c}))",
    "DAY": "CHECK ({c} IS NULL OR {c} = date({c}))",
    "TIME": "CHECK ({c} IS NULL OR ({c} GLOB '[0-2][0-9]:[0-5][0-9]' AND {c} < '24:00'))",
    "BOOL": "CHECK ({c} IS NULL OR {c} IN (0, 1))",
    "SHA": "CHECK ({c} IS NULL OR (length({c}) = 64 AND {c} NOT GLOB '*[^0-9a-f]*'))",
    "LEVEL": "CHECK ({c} IS NULL OR {c} IN (" + ", ".join(f"'{lv}'" for lv in LEVELS) + "))",
    "UUID": "CHECK ({c} IS NULL OR (length({c}) = 36 AND {c} GLOB '????????-????-????-????-????????????' AND lower({c}) = {c}))",
}

COLUMN_LINE = re.compile(r"^\s+([a-z_][a-z0-9_]*)\s")
MACRO = re.compile(r"@(" + "|".join(MACROS) + r")\b")


def expand_macros(text: str) -> str:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"@[A-Z]{2,}", line) and not line.lstrip().startswith("--"):
            m = COLUMN_LINE.match(line)
            if not m:
                raise SystemExit(f"tables.sql:{n}: macro outside a column line")
            col = m.group(1)
            line = MACRO.sub(lambda mm, col=col: MACROS[mm.group(1)].format(c=col), line)
            if re.search(r"@[A-Z]{2,}", line.split("--")[0]):
                raise SystemExit(f"tables.sql:{n}: unknown macro in: {line.strip()}")
        out.append(line)
    return "\n".join(out) + "\n"


def generate(base_sql: str) -> str:
    db = sqlite3.connect(":memory:")
    db.executescript(base_sql)
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name LIKE 'catalogue\\_%\\_v' ESCAPE '\\' ORDER BY name"
        )
    ]

    media_selects = []
    for t in tables:
        for fk in db.execute(f"PRAGMA foreign_key_list({t})"):
            if fk[2] == "catalogue_media_asset":
                col = fk[3]
                media_selects.append(f"SELECT pack_version_id, {col} AS sha256 FROM {t} WHERE {col} IS NOT NULL")

    # Tables that describe an item: primary key (pack_version_id, item_id).
    entity = []
    for t in tables:
        pk = [r[1] for r in sorted(db.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5] > 0]
        if pk == ["pack_version_id", "item_id"] and t not in SUBTYPE_TABLES:
            if t not in ENTITY_KIND:
                raise SystemExit(f"{t} describes an item but has no kind in ENTITY_KIND")
            entity.append(t)

    parts = [
        MARKER + " (begin; written by build_schema.py, do not edit by hand)",
        "",
        "-- Every media file used by a pack version, from all content tables.",
        "CREATE VIEW catalogue_version_media AS",
        "\nUNION\n".join(media_selects) + ";",
        "",
        "-- Every item described in a pack version, from the tables that describe items.",
        "CREATE VIEW catalogue_version_item AS",
        "\nUNION ALL\n".join(f"SELECT pack_version_id, item_id FROM {t}" for t in entity) + ";",
        "",
        "-- Pack content can be added or changed only while its version is importing,",
        "-- and cannot be deleted while it is active.",
    ]
    for t in tables:
        parts.append(f"""CREATE TRIGGER {t}_insert_guard BEFORE INSERT ON {t}
WHEN (SELECT status FROM catalogue_pack_version WHERE pack_version_id = NEW.pack_version_id) IS NOT 'importing'
BEGIN SELECT RAISE(ABORT, '{t}: content can be added only while its pack version is importing'); END;
CREATE TRIGGER {t}_update_guard BEFORE UPDATE ON {t}
WHEN (SELECT status FROM catalogue_pack_version WHERE pack_version_id = OLD.pack_version_id) IS NOT 'importing'
BEGIN SELECT RAISE(ABORT, '{t}: content can be changed only while its pack version is importing'); END;
CREATE TRIGGER {t}_delete_guard BEFORE DELETE ON {t}
WHEN (SELECT status FROM catalogue_pack_version WHERE pack_version_id = OLD.pack_version_id) = 'active'
BEGIN SELECT RAISE(ABORT, '{t}: content of the active pack version cannot be deleted'); END;""")

    parts += [
        "",
        "-- Items and varieties in content rows belong to the pack of the row's version, and an",
        "-- item described by a table has that table's kind.",
    ]
    pack_of_version = "(SELECT pack_id FROM catalogue_pack_version WHERE pack_version_id = NEW.pack_version_id)"
    for t in tables:
        conds = []
        for fk in db.execute(f"PRAGMA foreign_key_list({t})"):
            parent, col = fk[2], fk[3]
            if parent == "catalogue_item":
                conds.append(
                    f"(NEW.{col} IS NOT NULL AND (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.{col}) IS NOT {pack_of_version})"
                )
            elif parent == "catalogue_variety":
                conds.append(
                    f"(NEW.{col} IS NOT NULL AND (SELECT pack_id FROM catalogue_variety WHERE variety_id = NEW.{col}) IS NOT {pack_of_version})"
                )
        if t in entity:
            conds.append(f"(SELECT kind FROM catalogue_item WHERE item_id = NEW.item_id) IS NOT '{ENTITY_KIND[t]}'")
        if not conds:
            continue
        when = "\n  OR ".join(conds)
        for event in ("INSERT", "UPDATE"):
            parts.append(f"""CREATE TRIGGER {t}_pack_guard_{event.lower()} BEFORE {event} ON {t}
WHEN {when}
BEGIN SELECT RAISE(ABORT, '{t}: an item or variety is from another pack, or an item has the wrong kind'); END;""")
    parts.append(MARKER + " (end)")
    return "\n".join(parts) + "\n"


def build() -> str:
    expanded = expand_macros(SOURCE.read_text(encoding="utf-8"))
    if expanded.count(MARKER) != 1:
        raise SystemExit("tables.sql needs exactly one @GENERATED marker")
    before, after = expanded.split(MARKER, 1)
    after = after.split("\n", 1)[1]  # drop the rest of the marker line
    header = (
        "-- Franca database schema. Built from tables.sql by build_schema.py; edit tables.sql, not this file.\n"
        "-- The app opens every connection with: PRAGMA foreign_keys = ON; see the design document for the other settings.\n\n"
    )
    return header + before + generate(before) + after


def main() -> None:
    text = build()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("schema.sql is out of date: run python build_schema.py")
            sys.exit(1)
        print("schema.sql is up to date")
        return
    TARGET.write_text(text, encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.executescript(text)
    n = db.execute(
        "SELECT count(*) FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND sql NOT LIKE 'CREATE VIRTUAL%' AND name NOT LIKE '%_fts_%'"
    ).fetchone()[0]
    print(f"wrote {TARGET.name}: {n} tables")


if __name__ == "__main__":
    main()
