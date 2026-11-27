# Franca

Franca is a web app for learning languages as an adult. The first course is Dutch, in its Belgian standard form. Franca runs on one PC and is reached from other devices over Tailscale, a private network.

This repository is public and has the app's code. The courses, pictures, sound, harvested texts and learner data are kept in a private repository and on the PC. See [docs/repository-split.md](docs/repository-split.md) for what goes where.

## Folders

| Folder | What is in it |
|---|---|
| `server/` | The application service in Python (FastAPI): the API and the twelve modules of the learning engine |
| `client/` | The web client in TypeScript (React and Vite) |
| `speech/` | Will have the speech container (speech recognition and text to speech). It has its own licence, GPL-3.0-or-later |
| `contracts/` | The API description, the pack schemas and the database schema, with their tests |
| `packs/fixture/` | A small made-up pack (`fx`) for the tests. Real packs are kept in the private repository |
| `tools/` | The content guard, the pin check, the start-up file check and the Harden-Runner check, with their tests |
| `infra/` | The Docker Compose bundle, the image files, the Caddy configuration, the updater, the backup and the health monitoring, with their tests and rehearsals |
| `docs/` | Decision records (in `docs/decisions/`) and notes for developers |
| `scripts/` | `setup`, `check` and `update-contract` |

## Working on the code

You need [uv](https://docs.astral.sh/uv/) at the version pinned in `pyproject.toml` (0.11.32 at the time of writing), Python 3.10 or later for the Git hooks, Node.js 22 and pnpm 12. Then:

```sh
scripts/setup     # once after cloning: Git hooks, Python and npm packages
scripts/check     # the checks that the pipeline (GitHub's automatic checks after each push) runs
scripts/check python client   # only the parts named (guard, python, windows, client or browser)
```

To start the server and the client during development:

```sh
cd server && PYTHONPATH=src uv run uvicorn franca.api:create_app --factory --reload
pnpm --filter @franca/client dev
```

The client is then at http://localhost:5173.

## Package updates

Renovate, a service that checks for package updates, opens pull requests on Monday mornings. Minor and patch updates are merged automatically when all checks pass. Major updates, and updates of uv itself, wait for a review. A new release is not installed until it is seven days old. The steps for installing a security fix sooner are in [docs/package-updates.md](docs/package-updates.md).

Python packages are installed only as ready-built files (wheels), so no package runs its own build code. An npm package may run an install script only if it is listed under `allowBuilds` in `pnpm-workspace.yaml`. None are listed now, and an unlisted script stops the install.

## Licence

Franca's own code is licensed under the Apache License 2.0, in [LICENSE](LICENSE), with the copyright line "Copyright 2026 the Franca authors". The licence applies to the original work in this repository that was written for Franca, and that includes the made-up test pack in `packs/fixture/`. [NOTICE](NOTICE) has the attribution that copies of the code have to keep, and the list of third-party files in the repository.

Work that was not written for Franca, such as the libraries it uses, keeps its own copyright and licence. Franca's course material is not in this repository and is not licensed by it.

The speech container in `speech/` is licensed under GPL-3.0-or-later because a library it needs has that licence.
