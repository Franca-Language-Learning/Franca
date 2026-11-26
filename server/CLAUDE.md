# Server

- Python 3.14, FastAPI, mypy strict, ruff. Run from this folder: `uv run pytest`, `uv run mypy`, `PYTHONPATH=src uv run lint-imports`.
- Twelve modules in `src/franca/`, with `franca.api` above them and `franca.platform` below them. A module imports another module's package root only. Each module's `__init__.py` says what it is for.
- `tests/spec/` has the acceptance tests from the specification. Change them only when the specification changes.
- After changing a route, run `scripts/update-contract` from the repository root and commit `contracts/openapi.yaml`.
- No course content in tests. Use the made-up pack in `packs/fixture/`.
