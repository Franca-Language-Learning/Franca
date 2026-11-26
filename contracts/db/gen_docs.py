"""Generate the data dictionary and the diagrams from schema.sql.

Run with:  python gen_docs.py
Output files:
  docs/data-dictionary.md    every table with its columns, keys and the comment from tables.sql
  docs/erd/<group>.mmd       one Mermaid entity-relationship diagram per group of tables
Render the diagrams with: mmdc -i docs/erd/<group>.mmd -o docs/erd/<group>.svg
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "docs"

GROUPS = {
    "catalogue-packs": "Packs, versions, stable items, media and settings",
    "catalogue-course": "Course tree, lessons and activities",
    "catalogue-words": "Lexicon, forms, verbs, pronunciation and chunks",
    "catalogue-grammar": "Grammar, rules, sounds, can-dos and scenarios",
    "identity": "Learners, sign-in, preferences and audit log",
    "study": "Enrolments, daily plan, sessions, attempts and lookups",
    "memory-checking-mastery": "Cards, review log, feedback and mastery",
    "speech-ai-partner": "Recordings, conversations and Samen",
    "library-studio-records": "Library, review queue and xAPI outbox",
}


def group_of(table: str) -> str:
    if table.startswith("catalogue_"):
        if table in {
            "catalogue_pack",
            "catalogue_variety",
            "catalogue_pack_version",
            "catalogue_item",
            "catalogue_media_asset",
            "catalogue_licence",
            "catalogue_activity_type",
            "catalogue_ui_element",
            "catalogue_error_type",
            "catalogue_course_config_v",
            "catalogue_preteach_limit_v",
            "catalogue_listening_rule_v",
            "catalogue_element_name_v",
            "catalogue_ui_string_v",
            "catalogue_glossary_v",
            "catalogue_transcript_line_v",
            "catalogue_alignment_token_v",
        }:
            return "catalogue-packs"
        if any(k in table for k in ("course_node", "lesson", "prediction", "activity_v", "activity_use", "accepted_answer", "deck")):
            return "catalogue-course"
        if any(k in table for k in ("lexeme", "sense", "picture", "paradigm", "form_v", "verb", "speaker", "pronunciation", "chunk")):
            return "catalogue-words"
        return "catalogue-grammar"
    module = table.split("_")[0]
    if module in ("memory", "checking", "mastery"):
        return "memory-checking-mastery"
    if module in ("speech", "ai", "partner"):
        return "speech-ai-partner"
    if module in ("library", "studio", "records"):
        return "library-studio-records"
    return module


def table_comments(source: str) -> dict[str, str]:
    comments, pending = {}, []
    for line in source.splitlines():
        s = line.strip()
        if s.startswith("-- ") and not s.startswith("-- ="):
            pending.append(s[3:])
        elif s.startswith("CREATE TABLE") or s.startswith("CREATE VIRTUAL TABLE"):
            name = re.search(r"TABLE (\w+)", s).group(1)
            comments[name] = " ".join(pending)
            pending = []
        elif not s.startswith("--"):
            pending = []
    return comments


def main() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    comments = table_comments((HERE / "tables.sql").read_text(encoding="utf-8"))
    names = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND sql NOT LIKE 'CREATE VIRTUAL%' AND name NOT GLOB '*_fts_*' ORDER BY name"
        )
    ]

    info, fks = {}, {}
    for t in names:
        info[t] = list(db.execute(f"PRAGMA table_info({t})"))
        groups: dict[int, list] = {}
        for r in db.execute(f"PRAGMA foreign_key_list({t})"):
            groups.setdefault(r[0], [r[2], [], [], r[6]])
            groups[r[0]][1].append(r[3])
            groups[r[0]][2].append(r[4])
        fks[t] = list(groups.values())

    # Data dictionary
    OUT.mkdir(exist_ok=True)
    lines = [
        "# Franca data dictionary",
        "",
        "Generated from `schema.sql` by `gen_docs.py`. Do not edit by hand.",
        "",
        f"{len(names)} tables. Tables ending in `_v` hold pack content for one pack version.",
        "",
    ]
    for g, title in GROUPS.items():
        members = [t for t in names if group_of(t) == g]
        lines += [f"## {title}", ""]
        for t in members:
            lines += [f"### `{t}`", ""]
            if comments.get(t):
                lines += [comments[t], ""]
            fk_cols = {c: (p, on_delete) for p, cs, _, on_delete in fks[t] for c in cs}
            lines += ["| Column | Type | Required | Key | Refers to |", "| --- | --- | --- | --- | --- |"]
            for _cid, col, typ, notnull, _default, pk in info[t]:
                key = "PK" if pk else ""
                ref = ""
                if col in fk_cols:
                    p, od = fk_cols[col]
                    ref = f"`{p}`" + (f" (on delete {od.lower()})" if od and od != "NO ACTION" else "")
                    key = (key + " FK").strip()
                req = "yes" if notnull or pk else ""
                lines.append(f"| `{col}` | {typ} | {req} | {key} | {ref} |")
            lines.append("")
    (OUT / "data-dictionary.md").write_text("\n".join(lines), encoding="utf-8")

    # Diagrams: keys only; full columns are in the data dictionary.
    erd = OUT / "erd"
    erd.mkdir(exist_ok=True)
    for g in GROUPS:
        members = [t for t in names if group_of(t) == g]
        outside = sorted({p for t in members for p, *_ in fks[t] if p not in members})
        out = ["erDiagram"]
        for t in members + outside:
            fk_cols = {c for p, cs, *_ in fks[t] for c in cs}
            attrs = []
            for _cid, col, typ, _notnull, _default, pk in info[t]:
                if t in outside and not pk:
                    continue
                if pk or col in fk_cols:
                    tags = ",".join(x for x in ("PK" if pk else "", "FK" if col in fk_cols else "") if x)
                    attrs.append(f"        {typ or 'TEXT'} {col} {tags}")
            out.append(f"    {t} {{")
            out += attrs or ["        TEXT see_its_own_group"]
            out.append("    }")
        for t in members:
            for p, cs, _, _od in fks[t]:
                nullable = any(not r[3] and not r[5] for r in info[t] if r[1] in cs)
                left = "|o" if nullable else "||"
                out.append(f'    {p} {left}--o{{ {t} : "{", ".join(cs)}"')
        (erd / f"{g}.mmd").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"data dictionary: {len(names)} tables; diagrams: {len(GROUPS)}")


if __name__ == "__main__":
    main()
