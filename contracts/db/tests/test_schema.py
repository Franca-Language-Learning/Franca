"""Tests for the Franca database schema.

Run with:  python -m pytest db/
Python 3.11 or later with SQLite 3.37 or later (for STRICT tables) and pytest are needed.

The tests are in two groups:
* structure: rules that every table has to follow, checked by reading the schema;
* behaviour: inserts and deletes that have to be allowed or refused by the constraints and triggers.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
import uuid as uuidlib
from collections import deque
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent  # contracts/db
SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")
SEED = (HERE / "seed.sql").read_text(encoding="utf-8")

MODULES = ("identity", "catalogue", "study", "memory", "checking", "mastery", "speech", "partner", "ai", "library", "studio", "records")

# Tables outside catalogue that do not belong to one learner.
SHARED_TABLES = {
    "study_goal",
    "study_tour_part",  # app reference data
    "library_item",
    "library_section",
    "library_caption_track",
    "library_item_goal",  # the household library
    "partner_roleplay",  # reached through its members
    "studio_review_task",  # the owner's queue for the installation
    "ai_price",
    "ai_budget_alert",  # installation settings and records for AI use
}

# Catalogue tables that learner data may refer to.
STABLE_CATALOGUE = {
    "catalogue_pack",
    "catalogue_variety",
    "catalogue_item",
    "catalogue_media_asset",
    "catalogue_licence",
    "catalogue_activity_type",
    "catalogue_ui_element",
    "catalogue_error_type",
}

T0 = "2026-11-11T08:00:00.000Z"


def ts(day: int = 11, hour: int = 8, minute: int = 0) -> str:
    return f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00.000Z"


def new_uuid() -> str:
    return str(uuidlib.uuid4())


@pytest.fixture()
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    con.executescript(SEED)
    yield con
    con.close()


def tables(con: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND sql NOT LIKE 'CREATE VIRTUAL%' AND name NOT GLOB '*_fts_*' ORDER BY name"
        )
    ]


def foreign_keys(con: sqlite3.Connection, table: str) -> list[tuple[str, list[str], list[str]]]:
    """(parent table, child columns, parent columns) for each foreign key."""
    groups: dict[int, tuple[str, list[str], list[str]]] = {}
    for row in con.execute(f"PRAGMA foreign_key_list({table})"):
        fk_id, _seq, parent, child_col, parent_col = row[0], row[1], row[2], row[3], row[4]
        groups.setdefault(fk_id, (parent, [], []))
        groups[fk_id][1].append(child_col)
        groups[fk_id][2].append(parent_col)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Fixtures for content and learners
# ---------------------------------------------------------------------------


def make_pack(con, language="nl") -> int:
    cur = con.execute(
        "INSERT INTO catalogue_pack (language, name_en, script, direction, created_at) VALUES (?, 'Dutch', 'Latn', 'ltr', ?)",
        (language, T0),
    )
    pack_id = cur.lastrowid
    con.execute("INSERT INTO catalogue_variety (pack_id, code, name_en, productive) VALUES (?, 'nl-BE', 'Belgian Dutch', 1)", (pack_id,))
    con.execute(
        "INSERT INTO catalogue_variety (pack_id, code, name_en, productive, receptive_from) VALUES (?, 'nl-NL', 'Netherlands Dutch', 0, 'a2')",
        (pack_id,),
    )
    return pack_id


def variety(con, pack_id, code="nl-BE") -> int:
    return con.execute("SELECT variety_id FROM catalogue_variety WHERE pack_id = ? AND code = ?", (pack_id, code)).fetchone()[0]


def make_version(con, pack_id, version="1.0.0", distribution="private") -> int:
    cur = con.execute(
        "INSERT INTO catalogue_pack_version (pack_id, version, content_sha256, signature, distribution, built_at, imported_at) "
        "VALUES (?, ?, ?, x'00', ?, ?, ?)",
        (pack_id, version, "a" * 64, distribution, T0, T0),
    )
    return cur.lastrowid


def activate(con, pv) -> None:
    con.execute(
        "UPDATE catalogue_pack_version SET status = 'active', activated_at = ?, retired_at = NULL WHERE pack_version_id = ?", (T0, pv)
    )


def retire(con, pv) -> None:
    con.execute("UPDATE catalogue_pack_version SET status = 'retired', retired_at = ? WHERE pack_version_id = ?", (T0, pv))


def item(con, pack_id, key, kind) -> int:
    row = con.execute("SELECT item_id FROM catalogue_item WHERE pack_id = ? AND item_key = ?", (pack_id, key)).fetchone()
    if row:
        return row[0]
    return con.execute("INSERT INTO catalogue_item (pack_id, item_key, kind) VALUES (?, ?, ?)", (pack_id, key, kind)).lastrowid


def lexeme(con, pv, pack_id, lemma, upos="NOUN") -> int:
    iid = item(con, pack_id, f"nl:lexeme:{lemma}", "lexeme")
    con.execute("INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, ?, ?)", (pv, iid, lemma, upos))
    return iid


def media(con, sha="b" * 64, scope="private", licence="owned-copy") -> str:
    con.execute(
        "INSERT INTO catalogue_media_asset (sha256, mime, byte_size, licence_code, rights_scope, added_at) "
        "VALUES (?, 'audio/ogg', 100, ?, ?, ?)",
        (sha, licence, scope, T0),
    )
    return sha


def make_learner(con, name="Owner") -> int:
    return con.execute("INSERT INTO identity_learner (uuid, display_name, created_at) VALUES (?, ?, ?)", (new_uuid(), name, T0)).lastrowid


def enrol(con, learner_id, pack_id) -> int:
    return con.execute(
        "INSERT INTO study_enrolment (learner_id, pack_id, variety_id, started_at) VALUES (?, ?, ?, ?)",
        (learner_id, pack_id, variety(con, pack_id), T0),
    ).lastrowid


def card(con, enrolment_id, item_id, direction="recall", form_type="", state="review", due=None) -> int:
    due = due or ts(11, 6)
    if state == "new":
        return con.execute(
            "INSERT INTO memory_card (enrolment_id, item_id, direction, form_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (enrolment_id, item_id, direction, form_type, T0),
        ).lastrowid
    return con.execute(
        "INSERT INTO memory_card (enrolment_id, item_id, direction, form_type, state, due_at, stability, difficulty, reps, last_review_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 3.0, 5.0, 1, ?, ?)",
        (enrolment_id, item_id, direction, form_type, state, due, ts(1), T0),
    ).lastrowid


def session(con, enrolment_id, kind="review") -> int:
    return con.execute(
        "INSERT INTO study_session (uuid, enrolment_id, kind, pack_version, device_kind, started_at) "
        "VALUES (?, ?, ?, '1.0.0', 'desktop', ?)",
        (new_uuid(), enrolment_id, kind, T0),
    ).lastrowid


def attempt(con, session_id, item_id, activity_type="retrieval_card", direction="recall") -> int:
    return con.execute(
        "INSERT INTO study_attempt (uuid, session_id, activity_type, item_id, direction, input_mode, response, is_correct, started_at, answered_at) "
        "VALUES (?, ?, ?, ?, ?, 'typed', 'brood', 1, ?, ?)",
        (new_uuid(), session_id, activity_type, item_id, direction, T0, T0),
    ).lastrowid


def review(con, card_id, day=11, context="review", grade=3, source="auto", corrects=None, state="review", hour=9, attempt_id=None) -> int:
    return con.execute(
        "INSERT INTO memory_review_log (uuid, card_id, attempt_id, context, grade, grade_source, state_before, reviewed_at, review_day, "
        "recorded_at, corrects_review_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_uuid(), card_id, attempt_id, context, grade, source, state, ts(day, hour), f"2026-11-{day:02d}", ts(day, 23), corrects),
    ).lastrowid


@pytest.fixture()
def world(db):
    """A pack with an active version, one learner with an enrolment and one card."""
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    brood = lexeme(db, pv, pack_id, "brood")
    activate(db, pv)
    learner = make_learner(db)
    enrolment = enrol(db, learner, pack_id)
    c = card(db, enrolment, brood)
    return {"pack": pack_id, "pv": pv, "brood": brood, "learner": learner, "enrolment": enrolment, "card": c}


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_schema_sql_is_built_from_tables_sql():
    result = subprocess.run([sys.executable, str(HERE / "build_schema.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_loads_cleanly(db):
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_every_table_is_strict(db):
    loose = [t for t in tables(db) if "STRICT" not in db.execute("SELECT sql FROM sqlite_schema WHERE name = ?", (t,)).fetchone()[0]]
    assert loose == []


def test_every_table_name_starts_with_a_module(db):
    assert [t for t in tables(db) if t.split("_")[0] not in MODULES] == []


def test_every_foreign_key_has_an_index(db):
    """Without an index, the whole child table has to be read when a row is deleted from the parent table."""
    missing = []
    for t in tables(db):
        index_columns = []
        for idx in db.execute(f"PRAGMA index_list({t})"):
            if idx[4]:  # a partial index cannot be used for the lookup when a parent row is deleted
                continue
            cols = [r[2] for r in db.execute(f"PRAGMA index_info({idx[1]})")]
            index_columns.append(cols)
        pk = [r[1] for r in sorted(db.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5] > 0]
        index_columns.append(pk)
        for parent, child_cols, _ in foreign_keys(db, t):
            if not any(cols[: len(child_cols)] == child_cols for cols in index_columns):
                missing.append(f"{t}({', '.join(child_cols)}) -> {parent}")
    assert missing == []


def test_learner_tables_reach_identity_learner(db):
    """Every learner table is linked to identity_learner, so a learner's data is deleted with the learner."""
    unreached = []
    for t in tables(db):
        if t.startswith("catalogue_") or t in SHARED_TABLES or t == "identity_learner":
            continue
        seen, queue, found = {t}, deque([t]), False
        while queue and not found:
            for parent, _, _ in foreign_keys(db, queue.popleft()):
                if parent == "identity_learner":
                    found = True
                    break
                if parent not in seen and not parent.startswith("catalogue_"):
                    seen.add(parent)
                    queue.append(parent)
        if not found:
            unreached.append(t)
    assert unreached == []


def test_learner_tables_refer_only_to_stable_content(db):
    """Learner data is linked to stable ids, so it is kept when a pack is updated."""
    bad = []
    for t in tables(db):
        if t.startswith("catalogue_"):
            continue
        for parent, cols, _ in foreign_keys(db, t):
            if parent.startswith("catalogue_") and parent not in STABLE_CATALOGUE:
                bad.append(f"{t}({', '.join(cols)}) -> {parent}")
    assert bad == []


def test_content_tables_are_keyed_by_pack_version(db):
    bad = []
    for t in tables(db):
        if not t.endswith("_v"):
            continue
        pk = [r[1] for r in sorted(db.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5] > 0]
        if not pk or pk[0] != "pack_version_id":
            bad.append(t)
    assert bad == []


def test_content_tables_have_import_guards(db):
    triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type = 'trigger'")}
    missing = [
        f"{t}_{g}_guard" for t in tables(db) if t.endswith("_v") for g in ("insert", "update", "delete") if f"{t}_{g}_guard" not in triggers
    ]
    assert missing == []


def test_no_game_mechanics_columns(db):
    banned = re.compile(r"(^|_)(streak|streaks|xp|points|coins|gems|hearts|lives|energy|league|leaderboard|badge|badges)(_|$)")
    found = [f"{t}.{r[1]}" for t in tables(db) for r in db.execute(f"PRAGMA table_info({t})") if banned.search(r[1])]
    assert found == []


def test_timestamp_columns_are_checked(db):
    unchecked = []
    for t in tables(db):
        sql = db.execute("SELECT sql FROM sqlite_schema WHERE name = ?", (t,)).fetchone()[0]
        for r in db.execute(f"PRAGMA table_info({t})"):
            col = r[1]
            if (col.endswith("_at") or col in ("at", "delete_after")) and f"CHECK ({col} IS NULL OR ({col} GLOB" not in sql:
                unchecked.append(f"{t}.{col}")
    assert unchecked == []


def test_due_query_uses_the_due_index(db):
    plan = " ".join(
        r[3]
        for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT card_id FROM memory_card "
            "WHERE enrolment_id = 1 AND suspended_at IS NULL AND state <> 'new' AND due_at <= ? ORDER BY due_at",
            (T0,),
        )
    )
    assert "memory_card_due" in plan


# ---------------------------------------------------------------------------
# Behaviour: pack content and versions
# ---------------------------------------------------------------------------


def test_content_can_be_added_while_importing_only(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    lexeme(db, pv, pack_id, "brood")
    activate(db, pv)
    with pytest.raises(sqlite3.IntegrityError, match="only while its pack version is importing"):
        lexeme(db, pv, pack_id, "kaas")
    with pytest.raises(sqlite3.IntegrityError, match="changed only while"):
        db.execute("UPDATE catalogue_lexeme_v SET lemma = 'broodje' WHERE pack_version_id = ?", (pv,))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM catalogue_lexeme_v WHERE pack_version_id = ?", (pv,))


def test_one_active_version_per_pack(db):
    pack_id = make_pack(db)
    v1, v2 = make_version(db, pack_id, "1.0.0"), make_version(db, pack_id, "1.1.0")
    activate(db, v1)
    with pytest.raises(sqlite3.IntegrityError):
        activate(db, v2)


def test_active_version_cannot_be_deleted(world, db):
    with pytest.raises(sqlite3.IntegrityError, match="retire"):
        db.execute("DELETE FROM catalogue_pack_version WHERE pack_version_id = ?", (world["pv"],))


def test_items_are_never_deleted(world, db):
    with pytest.raises(sqlite3.IntegrityError, match="retired, not deleted"):
        db.execute("DELETE FROM catalogue_item WHERE item_id = ?", (world["brood"],))


def test_shareable_version_cannot_use_private_media(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id, distribution="shareable")
    lex = lexeme(db, pv, pack_id, "brood")
    sense = item(db, pack_id, "nl:sense:brood-1", "sense")
    db.execute(
        "INSERT INTO catalogue_sense_v (pack_version_id, item_id, lexeme_item_id, sense_no, gloss_en) VALUES (?, ?, ?, 1, 'bread')",
        (pv, sense, lex),
    )
    sha = media(db, scope="private")
    db.execute(
        "INSERT INTO catalogue_sense_example_v (pack_version_id, sense_item_id, example_no, text_tl, text_en, audio_sha256) "
        "VALUES (?, ?, 1, 'Ik eet brood.', 'I eat bread.', ?)",
        (pv, sense, sha),
    )
    assert db.execute("SELECT sha256 FROM catalogue_version_media WHERE pack_version_id = ?", (pv,)).fetchall() == [(sha,)]
    with pytest.raises(sqlite3.IntegrityError, match="private media"):
        activate(db, pv)


def test_learner_history_survives_a_pack_update(world, db):
    """After version 1.1.0 is switched on in place of 1.0.0, the card and its reviews are still linked to the same item."""
    review(db, world["card"])
    v2 = make_version(db, world["pack"], "1.1.0")
    db.execute(
        "INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos, frequency_rank) VALUES (?, ?, 'brood', 'NOUN', 812)",
        (v2, world["brood"]),
    )
    retire(db, world["pv"])
    activate(db, v2)
    db.execute("DELETE FROM catalogue_pack_version WHERE pack_version_id = ?", (world["pv"],))
    row = db.execute(
        "SELECT l.lemma, l.frequency_rank, count(r.review_id) FROM memory_card c "
        "JOIN catalogue_active_version a ON a.pack_id = ? "
        "JOIN catalogue_lexeme_v l ON l.pack_version_id = a.pack_version_id AND l.item_id = c.item_id "
        "LEFT JOIN memory_review_log r ON r.card_id = c.card_id WHERE c.card_id = ?",
        (world["pack"], world["card"]),
    ).fetchone()
    assert row == ("brood", 812, 1)


def test_lesson_item_relations_are_checked(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    unit = item(db, pack_id, "nl:unit:a1-u05", "course_node")
    lesson = item(db, pack_id, "nl:lesson:a1-u05-l03", "course_node")
    later = item(db, pack_id, "nl:lesson:a1-u07-l01", "course_node")
    db.execute(
        "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, node_type, position, level, title_tl, title_en) "
        "VALUES (?, ?, 'unit', 5, 'a1', 'Eten', 'Food')",
        (pv, unit),
    )
    for iid, pos, title in ((lesson, 3, "Niet of geen?"), (later, 9, "Deze en die")):
        db.execute(
            "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, parent_item_id, node_type, position, level, title_tl, title_en, lesson_role) "
            "VALUES (?, ?, ?, 'lesson', ?, 'a1', ?, ?, 'core')",
            (pv, iid, unit, pos, title, title),
        )
    db.execute("INSERT INTO catalogue_lesson_v (pack_version_id, item_id) VALUES (?, ?)", (pv, lesson))
    deze = item(db, pack_id, "nl:lexeme:deze", "lexeme")
    art = item(db, pack_id, "nl:grammar:article-indefinite", "grammar_point")
    sql = (
        "INSERT INTO catalogue_lesson_item_v (pack_version_id, lesson_item_id, item_id, relation, weight, position, taught_in_item_id) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (pv, lesson, art, "builds_on", None, None))  # builds_on needs core or support
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (pv, lesson, deze, "exposure_only", None, None))  # exposure_only needs taught_in
    db.execute(sql, (pv, lesson, art, "builds_on", "core", None))
    db.execute(sql, (pv, lesson, deze, "exposure_only", None, later))


def test_forms_that_do_not_exist_have_no_text(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    regenen = lexeme(db, pv, pack_id, "regenen", "VERB")
    db.execute(
        "INSERT INTO catalogue_paradigm_cell_v (pack_version_id, cell_key, upos, form_type, label_tl, label_en, position) "
        "VALUES (?, 'imp', 'VERB', 'imperative', 'gebiedende wijs', 'imperative', 9)",
        (pv,),
    )
    sql = "INSERT INTO catalogue_form_v (pack_version_id, lexeme_item_id, cell_key, variant_no, form, nonexistent) VALUES (?, ?, 'imp', ?, ?, ?)"
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (pv, regenen, 1, "regen", 1))
    db.execute(sql, (pv, regenen, 1, None, 1))


def test_verb_variants_and_two_auxiliaries(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    zeggen = lexeme(db, pv, pack_id, "zeggen", "VERB")
    vergeten = lexeme(db, pv, pack_id, "vergeten", "VERB")
    hebben, zijn = lexeme(db, pv, pack_id, "hebben", "AUX"), lexeme(db, pv, pack_id, "zijn", "AUX")
    db.execute(
        "INSERT INTO catalogue_verb_class_v (pack_version_id, class_key, label_tl, label_en) VALUES (?, 'strong', 'sterk', 'strong')", (pv,)
    )
    db.execute(
        "INSERT INTO catalogue_verb_class_v (pack_version_id, class_key, label_tl, label_en) VALUES (?, 'irregular', 'onregelmatig', 'irregular')",
        (pv,),
    )
    db.execute(
        "INSERT INTO catalogue_verb_v (pack_version_id, lexeme_item_id, class_key, stem) VALUES (?, ?, 'irregular', 'zeg')", (pv, zeggen)
    )
    db.execute(
        "INSERT INTO catalogue_verb_v (pack_version_id, lexeme_item_id, class_key, stem) VALUES (?, ?, 'strong', 'vergeet')", (pv, vergeten)
    )
    db.execute(
        "INSERT INTO catalogue_paradigm_cell_v (pack_version_id, cell_key, upos, form_type, label_tl, label_en, position) "
        "VALUES (?, 'past.sg', 'VERB', 'past', 'verleden tijd enkelvoud', 'past singular', 5)",
        (pv,),
    )
    be = variety(db, pack_id, "nl-BE")
    db.execute(
        "INSERT INTO catalogue_form_v (pack_version_id, lexeme_item_id, cell_key, variant_no, form) VALUES (?, ?, 'past.sg', 1, 'zei')",
        (pv, zeggen),
    )
    db.execute(
        "INSERT INTO catalogue_form_v (pack_version_id, lexeme_item_id, cell_key, variant_no, form, variety_id) VALUES (?, ?, 'past.sg', 2, 'zegde', ?)",
        (pv, zeggen, be),
    )
    for aux in (hebben, zijn):
        db.execute(
            "INSERT INTO catalogue_verb_auxiliary_v (pack_version_id, verb_item_id, auxiliary_item_id) VALUES (?, ?, ?)",
            (pv, vergeten, aux),
        )
    assert db.execute("SELECT count(*) FROM catalogue_verb_auxiliary_v WHERE verb_item_id = ?", (vergeten,)).fetchone()[0] == 2
    forms = db.execute("SELECT form FROM catalogue_form_v WHERE lexeme_item_id = ? ORDER BY variant_no", (zeggen,)).fetchall()
    assert forms == [("zei",), ("zegde",)]


# ---------------------------------------------------------------------------
# Behaviour: memory and the review log
# ---------------------------------------------------------------------------


def test_review_log_cannot_be_changed_or_deleted(world, db):
    r = review(db, world["card"])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE memory_review_log SET grade = 4 WHERE review_id = ?", (r,))
    with pytest.raises(sqlite3.IntegrityError, match="only with their card"):
        db.execute("DELETE FROM memory_review_log WHERE review_id = ?", (r,))


def test_a_grade_change_is_a_new_row_for_the_same_card(world, db):
    r = review(db, world["card"], grade=1)
    other = card(db, world["enrolment"], world["brood"], direction="say")
    with pytest.raises(sqlite3.IntegrityError, match="must match"):
        review(db, other, grade=3, source="override", corrects=r)  # another card
    with pytest.raises(sqlite3.IntegrityError, match="must match"):
        review(db, world["card"], grade=3, source="override", corrects=r, hour=10)  # another time
    review(db, world["card"], grade=3, source="override", corrects=r)
    with pytest.raises(sqlite3.IntegrityError):
        review(db, world["card"], grade=3, source="auto", corrects=r)  # a correction has to say it is an override


def test_step_by_step_answers_are_graded_hard_or_again(world, db):
    review(db, world["card"], grade=2, source="step_by_step")
    with pytest.raises(sqlite3.IntegrityError):
        review(db, world["card"], grade=3, source="step_by_step")


def test_mixed_run_limit_counts_per_item_and_day(world, db):
    """The limit is a pack setting per item (spec: mix_updates_per_item_per_day), checked by the engine."""
    from test_queries import QUERIES

    recognise = card(db, world["enrolment"], world["brood"], direction="recognise")
    first = review(db, world["card"], day=11, context="practice_mixed")
    review(db, recognise, day=11, context="practice_mixed")  # another card of the same item
    review(db, world["card"], day=11, context="practice_mixed", source="override", corrects=first)
    review(db, world["card"], day=11, context="review")
    review(db, world["card"], day=12, context="practice_mixed")

    def count(day):
        return db.execute(
            QUERIES["mixed_run_updates_today"], {"enrolment_id": world["enrolment"], "item_id": world["brood"], "today": day}
        ).fetchone()[0]

    assert (count("2026-11-11"), count("2026-11-12")) == (2, 1)


def test_lapses_leave_out_corrected_and_learning_answers(world, db):
    from test_queries import QUERIES

    pack, pv = world["pack"], make_version(db, world["pack"], "1.1.0")
    unit = item(db, pack, "nl:unit:a1-u05", "course_node")
    lesson = item(db, pack, "nl:lesson:a1-u05-l03", "course_node")
    db.execute(
        "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, node_type, position, title_tl, title_en) VALUES (?, ?, 'unit', 5, 'Eten', 'Food')",
        (pv, unit),
    )
    db.execute(
        "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, parent_item_id, node_type, position, title_tl, title_en, lesson_role) "
        "VALUES (?, ?, ?, 'lesson', 3, 'Niet of geen?', 'Niet or geen?', 'core')",
        (pv, lesson, unit),
    )
    db.execute("INSERT INTO catalogue_lesson_v (pack_version_id, item_id) VALUES (?, ?)", (pv, lesson))
    db.execute(
        "INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, 'brood', 'NOUN')", (pv, world["brood"])
    )
    db.execute(
        "INSERT INTO catalogue_lesson_item_v (pack_version_id, lesson_item_id, item_id, relation, weight, position) VALUES (?, ?, ?, 'builds_on', 'core', 0)",
        (pv, lesson, world["brood"]),
    )
    retire(db, world["pv"])
    activate(db, pv)
    counted = review(db, world["card"], day=2, grade=1)
    corrected = review(db, world["card"], day=3, grade=1)
    review(db, world["card"], day=3, grade=3, source="override", corrects=corrected)
    review(db, world["card"], day=4, grade=1, state="learning")
    row = db.execute(
        QUERIES["bridge_candidates"],
        {"enrolment_id": world["enrolment"], "pack_id": pack, "lesson_item_id": lesson, "since_30_days": "2026-10-12T08:00:00.000Z"},
    ).fetchone()
    assert row[0] == world["brood"] and row[-1] == 1 and counted


def test_card_rules(world, db):
    with pytest.raises(sqlite3.IntegrityError):
        card(db, world["enrolment"], world["brood"], direction="conjugate")  # needs a form type
    card(db, world["enrolment"], world["brood"], direction="conjugate", form_type="past")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO memory_card (enrolment_id, item_id, direction, state, due_at, created_at) VALUES (?, ?, 'spell', 'new', ?, ?)",
            (world["enrolment"], world["brood"], T0, T0),
        )  # a new card has no due date


def test_deleting_a_learner_removes_their_data(world, db):
    s = session(db, world["enrolment"])
    a = attempt(db, s, world["brood"])
    review(db, world["card"], attempt_id=a)
    db.execute("INSERT INTO checking_feedback (attempt_id, position, layer, message_en) VALUES (?, 1, 'accepted_answer', 'Right.')", (a,))
    sonnet = db.execute("SELECT ai_price_id FROM ai_price WHERE model = 'claude-sonnet-5-5'").fetchone()[0]
    db.execute(
        "INSERT INTO ai_request (learner_id, category, purpose, ai_price_id, input_tokens, outcome, latency_ms, at) "
        "VALUES (?, 'learning', 'feedback', ?, 100, 'ok', 500, ?)",
        (world["learner"], sonnet, T0),
    )
    db.execute("DELETE FROM identity_learner WHERE learner_id = ?", (world["learner"],))
    # the spending record stays, without the learner
    assert db.execute("SELECT learner_id FROM ai_request").fetchone() == (None,)
    for t in ("study_enrolment", "memory_card", "memory_review_log", "study_session", "study_attempt", "checking_feedback"):
        assert db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0, t
    assert db.execute("SELECT count(*) FROM catalogue_item").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Behaviour: daily plan, retention, search, formats
# ---------------------------------------------------------------------------


def test_daily_plan_rules(world, db):
    plan = db.execute(
        "INSERT INTO study_daily_plan (enrolment_id, plan_day, built_at, planned_minutes, review_minutes, mode, pack_version) "
        "VALUES (?, '2026-11-11', ?, 30, 5, 'normal', '1.0.0')",
        (world["enrolment"], T0),
    ).lastrowid
    entry = "INSERT INTO study_daily_plan_entry (daily_plan_id, entry_no, section, card_id, item_id, released_at) VALUES (?, ?, ?, ?, ?, ?)"
    db.execute(entry, (plan, 1, "bridge", world["card"], None, None))
    never_met = item(db, world["pack"], "nl:grammar:article-indefinite", "grammar_point")
    db.execute(entry, (plan, 2, "reminder", None, never_met, None))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(entry, (plan, 3, "reminder", world["card"], None, None))  # reminders have no card
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(entry, (plan, 4, "review", world["card"], None, None))  # the card is already in the plan
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(entry, (plan, 5, "reminder", None, never_met, None))  # the reminder is already in the plan
    db.execute("UPDATE study_daily_plan_entry SET released_at = ? WHERE daily_plan_id = ? AND entry_no = 1", (ts(11, 23), plan))
    lesson = item(db, world["pack"], "nl:lesson:a1-u05-l03", "course_node")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO study_daily_plan (enrolment_id, plan_day, built_at, planned_minutes, review_minutes, mode, new_items_factor, pack_version, lesson_item_id) "
            "VALUES (?, '2026-11-12', ?, 30, 20, 'review_only', 0.5, '1.0.0', ?)",
            (world["enrolment"], T0, lesson),
        )


def test_recordings_are_kept_30_days_at_most(world, db):
    sql = (
        "INSERT INTO speech_recording (uuid, learner_id, purpose, sha256, mime, duration_ms, recorded_at, delete_after) "
        "VALUES (?, ?, 'attempt', ?, 'audio/ogg', 2000, ?, ?)"
    )
    db.execute(sql, (new_uuid(), world["learner"], "c" * 64, ts(1), ts(30)))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (new_uuid(), world["learner"], "d" * 64, "2026-10-01T08:00:00.000Z", ts(11)))
    expired = db.execute("SELECT table_name FROM retention_expired WHERE expired_at <= ?", ("2026-12-01T00:00:00.000Z",)).fetchall()
    assert ("speech_recording",) in expired


def test_formats_are_checked(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO identity_learner (uuid, display_name, created_at) VALUES (?, 'A', '2026-11-11 08:00:00')", (new_uuid(),))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO identity_learner (uuid, display_name, created_at) VALUES (?, 'A', ?)", (new_uuid().upper(), T0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO identity_learner (uuid, display_name, created_at) VALUES (?, 'A', '2026-02-30T08:00:00.000Z')", (new_uuid(),)
        )


def test_notebook_search(world, db):
    db.execute(
        "INSERT INTO study_notebook_entry (uuid, enrolment_id, body_md, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (new_uuid(), world["enrolment"], "Geen staat voor een zelfstandig naamwoord zonder lidwoord.", T0, T0),
    )
    hits = db.execute("SELECT rowid FROM study_notebook_fts WHERE study_notebook_fts MATCH 'lidwoord'").fetchall()
    assert len(hits) == 1


def test_partners_share_with_each_other_not_themselves(world, db):
    alex = make_learner(db, "Alex")
    db.execute("INSERT INTO partner_share VALUES (?, ?, ?, 'lessons', ?)", (world["learner"], alex, world["pack"], T0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO partner_share VALUES (?, ?, ?, 'words', ?)", (alex, alex, world["pack"], T0))


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO memory_card (enrolment_id, item_id, direction, created_at) VALUES (999, 999, 'recall', ?)", (T0,))


# ---------------------------------------------------------------------------
# Behaviour: fixes from the independent review of 11 November
# ---------------------------------------------------------------------------


def test_deleting_a_session_keeps_its_reviews(world, db):
    """ON DELETE SET NULL on attempt_id is an update; it is the one update the log allows."""
    s = session(db, world["enrolment"])
    r = review(db, world["card"], attempt_id=attempt(db, s, world["brood"]))
    db.execute("DELETE FROM study_session WHERE session_id = ?", (s,))
    assert db.execute("SELECT attempt_id FROM memory_review_log WHERE review_id = ?", (r,)).fetchone() == (None,)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE memory_review_log SET attempt_id = 5 WHERE review_id = ?", (r,))


def test_pack_versions_move_only_along_allowed_steps(world, db):
    with pytest.raises(sqlite3.IntegrityError, match="starts as importing"):
        db.execute(
            "INSERT INTO catalogue_pack_version (pack_id, version, content_sha256, signature, distribution, status, built_at, imported_at, activated_at) "
            "VALUES (?, '2.0.0', ?, x'00', 'private', 'active', ?, ?, ?)",
            (world["pack"], "a" * 64, T0, T0, T0),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed after import"):
        db.execute("UPDATE catalogue_pack_version SET signature = x'01' WHERE pack_version_id = ?", (world["pv"],))
    retire(db, world["pv"])
    with pytest.raises(sqlite3.IntegrityError, match="not allowed"):
        db.execute("UPDATE catalogue_pack_version SET status = 'importing' WHERE pack_version_id = ?", (world["pv"],))


def test_media_rights_follow_the_licence_and_freeze(db):
    with pytest.raises(sqlite3.IntegrityError, match="cannot be shareable"):
        media(db, sha="e" * 64, scope="shareable", licence="owned-copy")
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    lex = lexeme(db, pv, pack_id, "brood")
    sense = item(db, pack_id, "nl:sense:brood-1", "sense")
    db.execute(
        "INSERT INTO catalogue_sense_v (pack_version_id, item_id, lexeme_item_id, sense_no, gloss_en) VALUES (?, ?, ?, 1, 'bread')",
        (pv, sense, lex),
    )
    sha = media(db, sha="f" * 64, scope="shareable", licence="CC0-1.0")
    db.execute(
        "INSERT INTO catalogue_sense_example_v (pack_version_id, sense_item_id, example_no, text_tl, text_en, audio_sha256) "
        "VALUES (?, ?, 1, 'Ik eet brood.', 'I eat bread.', ?)",
        (pv, sense, sha),
    )
    activate(db, pv)
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
        db.execute("UPDATE catalogue_media_asset SET rights_scope = 'private' WHERE sha256 = ?", (sha,))


def test_rollback_brings_retired_items_back(world, db):
    pack = world["pack"]
    # Version 1.0.0 (active) has brood. Version 1.1.0 adds zakje; 1.2.0 drops it again.
    v11 = make_version(db, pack, "1.1.0")
    for lemma in ("brood", "zakje"):
        iid = item(db, pack, f"nl:lexeme:{lemma}", "lexeme")
        db.execute("INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, ?, 'NOUN')", (v11, iid, lemma))
    zakje = item(db, pack, "nl:lexeme:zakje", "lexeme")
    retire(db, world["pv"])
    activate(db, v11)
    v12 = make_version(db, pack, "1.2.0")
    db.execute(
        "INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, 'brood', 'NOUN')", (v12, world["brood"])
    )
    retire(db, v11)
    activate(db, v12)

    def live():
        return {r[0] for r in db.execute("SELECT item_id FROM catalogue_item_live WHERE pack_id = ?", (pack,))}

    assert zakje not in live()
    retire(db, v12)
    activate(db, v11)
    assert zakje in live() and world["brood"] in live()


def test_content_cannot_mix_packs_or_kinds(db):
    nl, fr = make_pack(db, "nl"), make_pack(db, "fr")
    pv = make_version(db, nl)
    french_item = item(db, fr, "fr:lexeme:pain", "lexeme")
    with pytest.raises(sqlite3.IntegrityError, match="another pack"):
        db.execute(
            "INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, 'pain', 'NOUN')", (pv, french_item)
        )
    node = item(db, nl, "nl:unit:a1-u01", "course_node")
    with pytest.raises(sqlite3.IntegrityError, match="wrong kind"):
        db.execute("INSERT INTO catalogue_lexeme_v (pack_version_id, item_id, lemma, upos) VALUES (?, ?, 'x', 'NOUN')", (pv, node))
    learner = make_learner(db)
    enrolment = enrol(db, learner, nl)
    with pytest.raises(sqlite3.IntegrityError, match="enrolment's pack"):
        card(db, enrolment, french_item)


def test_unique_rules_with_nulls(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    a, b = item(db, pack_id, "nl:level:a1", "course_node"), item(db, pack_id, "nl:level:a2", "course_node")
    sql = "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, node_type, position, title_tl, title_en) VALUES (?, ?, 'level', 0, 'A1', 'A1')"
    db.execute(sql, (pv, a))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (pv, b))  # two roots at position 0
    zeggen = lexeme(db, pv, pack_id, "zeggen", "VERB")
    db.execute(
        "INSERT INTO catalogue_paradigm_cell_v (pack_version_id, cell_key, upos, form_type, label_tl, label_en, position) "
        "VALUES (?, 'imp', 'VERB', 'imperative', 'gebiedende wijs', 'imperative', 9)",
        (pv,),
    )
    db.execute(
        "INSERT INTO catalogue_form_v (pack_version_id, lexeme_item_id, cell_key, variant_no, form) VALUES (?, ?, 'imp', 1, 'zeg')",
        (pv, zeggen),
    )
    with pytest.raises(sqlite3.IntegrityError, match="nonexistent"):
        db.execute(
            "INSERT INTO catalogue_form_v (pack_version_id, lexeme_item_id, cell_key, variant_no, form, nonexistent) VALUES (?, ?, 'imp', 2, NULL, 1)",
            (pv, zeggen),
        )


def test_handover_codes_last_ten_minutes_at_most(world, db):
    s = session(db, world["enrolment"])
    act = item(db, world["pack"], "nl:lesson:a1-u05-l03#dictee-1", "activity")
    sql = "INSERT INTO study_handover (session_id, activity_item_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)"
    db.execute(sql, (s, act, b"\x01" * 32, ts(11, 8, 0), ts(11, 8, 10)))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (s, act, b"\x02" * 32, ts(11, 8, 0), ts(11, 8, 30)))


def test_one_owner(db):
    db.execute("INSERT INTO identity_learner (uuid, display_name, role, created_at) VALUES (?, 'Owner', 'owner', ?)", (new_uuid(), T0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO identity_learner (uuid, display_name, role, created_at) VALUES (?, 'Alex', 'owner', ?)", (new_uuid(), T0))


def test_cards_and_links_stay_within_one_course(world, db):
    node = item(db, world["pack"], "nl:unit:a1-u01", "course_node")
    with pytest.raises(sqlite3.IntegrityError, match="learnable item"):
        card(db, world["enrolment"], node)
    alex = make_learner(db, "Alex")
    other = enrol(db, alex, world["pack"])
    plan = db.execute(
        "INSERT INTO study_daily_plan (enrolment_id, plan_day, built_at, planned_minutes, review_minutes, mode, pack_version) "
        "VALUES (?, '2026-11-11', ?, 30, 5, 'normal', '1.0.0')",
        (other, T0),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="same course"):
        db.execute(
            "INSERT INTO study_daily_plan_entry (daily_plan_id, entry_no, section, card_id) VALUES (?, 1, 'review', ?)",
            (plan, world["card"]),
        )
    nik_attempt = attempt(db, session(db, world["enrolment"]), world["brood"])
    alex_card = card(db, other, world["brood"])
    with pytest.raises(sqlite3.IntegrityError, match="same course"):
        review(db, alex_card, attempt_id=nik_attempt)


def test_course_tree_cannot_loop(db):
    pack_id = make_pack(db)
    pv = make_version(db, pack_id)
    unit, lesson = item(db, pack_id, "nl:unit:a1-u05", "course_node"), item(db, pack_id, "nl:lesson:a1-u05-l03", "course_node")
    db.execute(
        "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, node_type, position, title_tl, title_en) VALUES (?, ?, 'unit', 5, 'Eten', 'Food')",
        (pv, unit),
    )
    db.execute(
        "INSERT INTO catalogue_course_node_v (pack_version_id, item_id, parent_item_id, node_type, position, title_tl, title_en, lesson_role) "
        "VALUES (?, ?, ?, 'lesson', 3, 'Niet of geen?', 'Niet or geen?', 'core')",
        (pv, lesson, unit),
    )
    with pytest.raises(sqlite3.IntegrityError, match="cycle"):
        db.execute("UPDATE catalogue_course_node_v SET parent_item_id = ? WHERE pack_version_id = ? AND item_id = ?", (lesson, pv, unit))
    with pytest.raises(sqlite3.IntegrityError, match="lesson node"):
        db.execute("INSERT INTO catalogue_lesson_v (pack_version_id, item_id) VALUES (?, ?)", (pv, unit))


def test_step_by_step_grades_cannot_be_changed(world, db):
    r = review(db, world["card"], grade=2, source="step_by_step")
    with pytest.raises(sqlite3.IntegrityError, match="Stap voor stap"):
        review(db, world["card"], grade=3, source="override", corrects=r)


def test_sign_in_sessions_last_30_days_after_last_use(world, db):
    sql = (
        "INSERT INTO identity_auth_session (learner_id, token_hash, device_kind, created_at, last_seen_at, expires_at) "
        "VALUES (?, ?, 'desktop', ?, ?, ?)"
    )
    db.execute(sql, (world["learner"], b"\x01" * 32, ts(1), ts(11), "2026-12-11T08:00:00.000Z"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (world["learner"], b"\x02" * 32, ts(1), ts(11), "2026-12-20T08:00:00.000Z"))


# ---------------------------------------------------------------------------
# Behaviour: accounts and AI use (decisions of 21 November)
# ---------------------------------------------------------------------------


def test_invitations_and_google_sign_in(db):
    owner = make_learner(db, "Owner")
    sql = "INSERT INTO identity_invitation (email_norm, invited_by_learner_id, created_at, expires_at) VALUES (?, ?, ?, ?)"
    db.execute(sql, ("partner@example.org", owner, T0, ts(18)))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("partner@example.org", owner, T0, ts(18)))  # one open invitation per address
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("Other@Example.org", owner, T0, ts(18)))  # stored in lower case
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("late@example.org", owner, T0, ts(28)))  # 14 days at most
    ext = (
        "INSERT INTO identity_external_identity (learner_id, provider, subject, email, email_verified, created_at) "
        "VALUES (?, 'google', ?, ?, ?, ?)"
    )
    db.execute(ext, (owner, "108234", "owner@example.org", 1, T0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(ext, (make_learner(db, "X"), "108234", "x@example.org", 1, T0))  # one learner per Google account
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(ext, (make_learner(db, "Y"), "999", "y@example.org", 0, T0))  # the address has to be verified


def test_ai_cost_and_month_spend(world, db):
    sonnet = db.execute("SELECT ai_price_id FROM ai_price WHERE model = 'claude-sonnet-5-5'").fetchone()[0]
    sql = (
        "INSERT INTO ai_request (learner_id, category, purpose, ai_price_id, input_tokens, cache_read_tokens, output_tokens, "
        "outcome, latency_ms, at) VALUES (?, 'learning', 'conversation', ?, ?, ?, ?, ?, 900, ?)"
    )
    db.execute(sql, (world["learner"], sonnet, 1000, 3000, 150, "ok", T0))
    # 1,000 x 2 + 3,000 x 0.1 + 150 x 10 = 3,800 micro-dollars
    assert db.execute("SELECT cost_microusd FROM ai_request_cost").fetchone()[0] == 3800
    db.execute(
        "INSERT INTO ai_request (learner_id, category, purpose, outcome, latency_ms, at) "
        "VALUES (?, 'learning', 'conversation', 'over_limit', 0, ?)",
        (world["learner"], T0),
    )
    assert db.execute("SELECT spent_microusd, calls, refused_calls FROM ai_month_spend WHERE month = '2026-11'").fetchone() == (3800, 2, 1)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (None, sonnet, 10, 0, 1, "ok", T0))  # learning calls belong to a learner
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ai_request (learner_id, category, purpose, input_tokens, outcome, latency_ms, at) "
            "VALUES (?, 'learning', 'feedback', 5, 'over_limit', 0, ?)",
            (world["learner"], T0),
        )  # a refused call used no tokens


def test_current_ai_limit(db):
    assert db.execute("SELECT monthly_limit_microusd FROM ai_budget_current WHERE category = 'learning'").fetchone() == (40000000,)
    db.execute(
        "INSERT INTO ai_budget (category, monthly_limit_microusd, learner_daily_limit_microusd, valid_from) "
        "VALUES ('learning', 25000000, 2000000, '2026-11-21T01:00:00.000Z')"
    )
    assert db.execute("SELECT monthly_limit_microusd FROM ai_budget_current WHERE category = 'learning'").fetchone() == (25000000,)


def test_goals_keep_their_history(world, db):
    e = world["enrolment"]
    add = "INSERT INTO study_enrolment_goal (enrolment_id, goal_key, added_at, removed_at) VALUES (?, ?, ?, ?)"
    db.execute(add, (e, "work", T0, ts(12)))  # chosen, then removed
    db.execute(add, (e, "work", ts(13), None))  # chosen again
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(add, (e, "work", ts(14), None))  # one open row per goal
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(add, (e, "hobbies", T0, None))  # goal keys come from the app's list
    target = "INSERT INTO study_enrolment_target (enrolment_id, target_level, exam_key, chosen_at, replaced_at) VALUES (?, ?, ?, ?, ?)"
    db.execute(target, (e, "a2", None, T0, ts(12)))
    db.execute(target, (e, "b1", "staatsexamen-1", ts(12), None))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(target, (e, "b1", None, ts(13), None))  # one open target
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(target, (e, None, None, ts(13), ts(14)))  # a level or an exam is needed
    assert [r[0] for r in db.execute("SELECT goal_key FROM study_goal WHERE followup IS NOT NULL ORDER BY position")] == ["exam", "field"]


def test_pending_calls_and_lost_timeouts_count_at_their_estimate(world, db):
    sonnet = db.execute("SELECT ai_price_id FROM ai_price WHERE model = 'claude-sonnet-5-5'").fetchone()[0]
    sql = (
        "INSERT INTO ai_request (learner_id, category, purpose, estimated_microusd, outcome, latency_ms, ai_price_id, at) "
        "VALUES (?, 'learning', 'conversation', ?, ?, ?, ?, ?)"
    )
    db.execute(sql, (world["learner"], 5000, "pending", None, sonnet, T0))
    db.execute(sql, (world["learner"], 7000, "timeout", 30000, None, T0))  # no usage came back
    assert db.execute("SELECT sum(cost_microusd) FROM ai_request_cost").fetchone()[0] == 12000
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (world["learner"], 1, "pending", 10, sonnet, T0))  # a pending call has no latency yet
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (None, 1, "timeout", 10, None, T0))  # a learning call needs a learner


def test_prices_in_force_leave_out_future_rows(db):
    db.execute(
        "INSERT INTO ai_price (provider, model, min_prompt_tokens, input, output, cache_write_5m, cache_write_1h, cache_read, valid_from) "
        "VALUES ('anthropic', 'claude-sonnet-5-5', 0, 1, 1, 1, 1, 1, '2999-01-01')"
    )
    assert db.execute("SELECT count(*) FROM ai_price_current").fetchone()[0] == 3


def test_invitation_and_owner_rules(db):
    owner = make_learner(db, "Owner")
    db.execute("UPDATE identity_learner SET role = 'owner' WHERE learner_id = ?", (owner,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = ?", (owner,))  # owner cannot be locked out
    sql = "INSERT INTO identity_invitation (email_norm, role, created_at, expires_at, accepted_at) VALUES (?, ?, ?, ?, ?)"
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("a@example.org", "owner", T0, ts(18), None))  # no owner by invitation
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("b@example.org", "learner", T0, ts(18), ts(19)))  # accepted after it expired


def test_goal_choices_stay_in_the_enrolment_pack(world, db):
    other = make_pack(db, "fr")
    fr_can_do = item(db, other, "fr:can-do:a1-1", "can_do")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO study_personal_can_do (enrolment_id, can_do_item_id, source, added_at) VALUES (?, ?, 'goal', ?)",
            (world["enrolment"], fr_can_do, T0),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO study_enrolment_module (enrolment_id, module_item_id, added_at) VALUES (?, ?, ?)",
            (world["enrolment"], world["brood"], T0),
        )  # a word is not a module


def test_wablieft_licence_is_private(db):
    assert db.execute("SELECT shareable FROM catalogue_licence WHERE licence_code = 'int-noncommercial'").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="cannot be shareable"):
        media(db, sha="a1" * 32, scope="shareable", licence="int-noncommercial")


def test_games_are_activity_types(db):
    games = dict(db.execute("SELECT activity_type, response FROM catalogue_activity_type WHERE game = 1").fetchall())
    assert set(games) == {"crossword", "collocation_match", "odd_one_out", "article_sort", "memory_game", "guess_the_word", "story_game"}
    assert games["crossword"] == "production" and games["memory_game"] == "recognition"


def test_game_results_can_be_shared_with_the_partner(world, db):
    alex = make_learner(db, "Alex")
    db.execute("INSERT INTO partner_share VALUES (?, ?, ?, 'game_results', ?)", (world["learner"], alex, world["pack"], T0))
