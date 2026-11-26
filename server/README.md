# Franca server

The application service: the HTTP API in `franca.api`, twelve modules for the learning engine, and `franca.platform` for settings, database access and logging. Each module's `__init__.py` says what it is for.

```sh
uv run pytest                 # tests, including the contract and tool tests
uv run mypy                   # type check
PYTHONPATH=src uv run lint-imports   # layers: api, then modules, then platform
```

The tests in `tests/spec/` are the acceptance tests from the specification of 11 and 21 November 2026.
