# Franca database schema

11 November 2026, updated 21 November 2026

This folder has the database design for Franca as files that can be run and tested. The design is explained in the data model document in the project documents (`design/data-model.md`).

| File | What it is |
| --- | --- |
| `tables.sql` | The schema as written by hand, with short codes such as `@TS` for checked columns |
| `build_schema.py` | Used to build `schema.sql` from `tables.sql`, with the generated views and triggers |
| `schema.sql` | The schema loaded by the app and the first migration. Do not edit it by hand |
| `seed.sql` | App reference data: licences, activity types, interface element keys, item kinds, error types, goals, tour parts, AI model prices and the first AI spending limits |
| `queries.sql` | The main read paths |
| `tests/test_schema.py`, `tests/test_queries.py` | The schema and query tests |
| `gen_docs.py` | Used to make `docs/data-dictionary.md` and the diagram sources in `docs/erd/` |

## How to run the tests

The tests run with the server's tests. In a terminal in the `server` folder, type:

```
uv run pytest ../contracts/db/tests
```

## How to change the schema

1. Edit `tables.sql`.
2. Run `python3 contracts/db/build_schema.py` to rebuild `schema.sql`.
3. Run the tests. The first test fails if `schema.sql` was not rebuilt.
4. Run `python3 contracts/db/gen_docs.py` to update the data dictionary and diagram sources. The diagrams are made from the `.mmd` files with `mmdc -i <file>.mmd -o <file>.svg`.
