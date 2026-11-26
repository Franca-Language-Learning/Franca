# Contracts

This folder has the agreements between the parts of Franca. Other parts rely on them, so every contract is tested, except `ui/`, which is not written yet.

| Folder or file | Contract | Checked by |
|---|---|---|
| `openapi.yaml` | The HTTP API between the server and the client. Written by `scripts/update-contract` from the server's routes | `server/tests/test_openapi_contract.py` |
| `pack/` | JSON schemas for a language pack's course settings and lessons | `server/tests/spec/test_planner_rules.py` |
| `db/` | The database tables, written in `tables.sql` and built into `schema.sql`, with sample data and the main queries | `db/tests/` |
| `ui/` (from story E01-002) | The interface components that the design and the client share | not yet written |

See `db/README.md` for how the database schema is built.
