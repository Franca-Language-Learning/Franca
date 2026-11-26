# Server

- Python 3.14, FastAPI, mypy strict, ruff. Run from this folder: `uv run pytest`, `uv run mypy`, `PYTHONPATH=src uv run lint-imports`.
- Twelve modules in `src/franca/`, with `franca.api` above them and `franca.platform` below them. A module imports another module's package root only. Each module's `__init__.py` says what it is for.
- `tests/spec/` has the acceptance tests from the specification. Change them only when the specification changes.
- After changing a route, run `scripts/update-contract` from the repository root and commit `contracts/openapi.yaml`.
- No course content in tests. Use the made-up pack in `packs/fixture/`.
- The database is SQLite through `franca.platform.db`. A change to `contracts/db/tables.sql` needs a new migration in `src/franca/platform/migrations/versions/`. `tests/test_database.py` fails until the migrations build the same schema as `contracts/db/schema.sql`. Do not edit `0001_baseline.sql`.
- Requests that change something (any method but GET, HEAD and OPTIONS) need the anti-forgery token from the `franca_csrf` cookie in the `X-CSRF-Token` header (`franca.api.anti_forgery`). In tests, use `FrancaTestClient` from `tests/conftest.py`, which sends it.
