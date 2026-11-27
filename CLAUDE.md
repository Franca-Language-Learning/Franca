# Notes for Claude working in this repository

Franca is a language-learning app. The product owner reviews the work, and anything the owner has to do is written as numbered steps.

## Rules

- Course material, pictures, sound, harvested texts, learner data and secrets never go in this repository. It is public. See `docs/repository-split.md`. The content guard runs in the hooks and the pipeline; do not bypass it.
- Write the test first, see it fail, then write the code.
- Run `scripts/check` before saying a change is finished.
- Modules in `server/src/franca/` import each other's package root only (`from franca.study import ...`, never `from franca.study.planner_rules import ...` in another module).
- After changing a route, run `scripts/update-contract` and commit `contracts/openapi.yaml` with the change.
- New packages: check the licence (no AGPL or GPL packages outside `speech/`), and add them with `uv add` or `pnpm add`, so that no release younger than seven days is installed. For a security fix that is newer, follow `docs/package-updates.md`.
- Interface text and documentation follow the writing rules in the language-standard skill, and an independent agent reviews new text.

## Commands

| Task | Command |
|---|---|
| Set up a checkout | `scripts/setup` |
| All checks | `scripts/check` |
| Some of the checks | `scripts/check python client` (the parts are guard, secrets, python, windows, client and browser) |
| Server tests | `cd server && uv run pytest` |
| Client tests | `pnpm --filter @franca/client test` |
| Write the API contract | `scripts/update-contract` |

The server is not installed as a package (uv installs wheels only), so commands that import `franca` outside pytest and mypy need `PYTHONPATH=src` from `server/`.
