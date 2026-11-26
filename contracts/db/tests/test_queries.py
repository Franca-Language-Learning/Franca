"""Checks for the read paths in queries.sql.

Each query has to run against the schema, and its rows have to be found through an index.
The test fails if a whole table is scanned in a query plan.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from test_schema import SCHEMA, SEED, T0  # noqa: F401  (shared fixtures and constants)

HERE = Path(__file__).resolve().parent.parent  # contracts/db


def load_queries() -> dict[str, str]:
    text = (HERE / "queries.sql").read_text(encoding="utf-8")
    blocks = re.split(r"^-- name: ", text, flags=re.M)[1:]
    return {b.split("\n", 1)[0].strip(): b.split("\n", 1)[1] for b in blocks}


QUERIES = load_queries()

PARAMS = {
    "enrolment_id": 1,
    "now": T0,
    "limit": 50,
    "pack_id": 1,
    "lesson_item_id": 1,
    "since_30_days": "2026-10-12T08:00:00.000Z",
    "item_id": 1,
    "today": "2026-11-11",
    "form": "zei",
    "rule_item_id": 1,
    "viewer_learner_id": 2,
    "owner_learner_id": 1,
}


@pytest.fixture(scope="module")
def con():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    c.executescript(SEED)
    # Planner statistics as for a database in use: every index is selective. On empty
    # tables SQLite has no statistics, and its plans would say little about real use.
    c.execute("ANALYZE")
    for (table,) in c.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND sql NOT LIKE 'CREATE VIRTUAL%' AND name NOT GLOB '*_fts_*'"
    ).fetchall():
        c.execute("INSERT INTO sqlite_stat1 VALUES (?, NULL, '100000')", (table,))
        for idx in c.execute(f"PRAGMA index_list({table})").fetchall():
            ncols = len(c.execute(f"PRAGMA index_info({idx[1]})").fetchall())
            c.execute("INSERT INTO sqlite_stat1 VALUES (?, ?, ?)", (table, idx[1], "100000" + " 10" * ncols))
    c.execute("ANALYZE sqlite_schema")
    return c


def test_queries_file_has_the_main_read_paths():
    assert set(QUERIES) >= {
        "due_reviews",
        "bridge_candidates",
        "mixed_run_updates_today",
        "open_lookups",
        "verb_chart_by_form",
        "mistakes_per_rule",
        "partner_lessons",
    }


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_query_runs(con, name):
    sql = QUERIES[name]
    needed = set(re.findall(r":([a-z_0-9]+)", sql))
    con.execute(sql, {k: PARAMS[k] for k in needed}).fetchall()


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_query_uses_indexes(con, name):
    sql = QUERIES[name]
    needed = set(re.findall(r":([a-z_0-9]+)", sql))
    plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, {k: PARAMS[k] for k in needed})]
    # Plans name tables by their alias, so any full scan fails, apart from a constant row.
    scans = [p for p in plan if p.startswith("SCAN ") and p != "SCAN CONSTANT ROW"]
    assert scans == [], plan
