# Contracts

This folder has the agreements between the parts of Franca. Other parts rely on them, so every contract is tested.

| Folder or file | Contract | Checked by |
|---|---|---|
| `openapi.yaml` | The HTTP API between the server and the client. Written by `scripts/update-contract` from the server's routes | `server/tests/test_openapi_contract.py` |
| `pack/` | JSON schemas for each type of file in a language pack. See `pack/README.md` | `pack/tests/` and `server/tests/spec/test_planner_rules.py` |
| `db/` | The database tables, written in `tables.sql` and built into `schema.sql`, with sample data and the main queries | `db/tests/` |
| `ui/components.ts` | The props of the shared interface components, which the design and the client both use | `client/src/contracts.test.ts` and the client's type check |

See `db/README.md` for how the database schema is built.
