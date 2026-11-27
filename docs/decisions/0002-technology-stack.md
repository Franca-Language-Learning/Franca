---
status: accepted
date: 2026-11-26
decision-makers: product owner
---

# Technology stack for Dutch 1.0

## Context and problem statement

Franca runs on one Windows PC for one learner at first, so it has to be small to run and simple to keep up to date. The options for each part were compared in the technology review of 26 November 2026 (`design/technology-review-2026-11-26.md` in the project documents).

## Decision outcome

| Part | Choice |
|---|---|
| Application service | A modular monolith in Python 3.14 with FastAPI. Twelve modules, with `franca.api` above them and `franca.platform` below them |
| Data | SQLite with SQLAlchemy and Alembic; Huey for background jobs |
| Web client | React 19, React Aria Components, TanStack Router and Query, Vite 8, FormatJS for interface text |
| Scheduling | FSRS-6, with py-fsrs on the server and ts-fsrs in the client |
| Reading | A fork of Lute v3 |
| Speech | sherpa-onnx with Parakeet, Whisper, Silero VAD and Piper voices, in a separate GPL-3.0-or-later container |
| AI | Franca's own adapter on the Anthropic and Mistral SDKs, with JSON-schema structured outputs |
| Running it | Docker Engine in WSL 2, Caddy, Tailscale, Litestream and restic for backups, Gatus for monitoring |

### Rules that come with the stack

- Modules import each other's package root only. import-linter and `server/tests/test_module_boundaries.py` check this.
- The API is described in `contracts/openapi.yaml`, and a test fails when the description and the routes differ.
- Python packages are installed from wheels only, and npm install scripts run only for the packages listed in `pnpm-workspace.yaml`.
- No package release is installed in its first seven days.

### Patterns shared with the Full Stack FastAPI Template

The technology review names the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) (MIT licence) as a pattern for the parts in the table below. On 27 November 2026, Franca's files were compared with the template's `master` branch at commit `f8c6c14`. No file or code was copied from it, so there is no MIT notice in this repository. Before this section was added, the template was not mentioned in Franca's Git history.

| Part | The same as in the template | Different in Franca, and why |
|---|---|---|
| API client | The API description is exported from the FastAPI app by a script, and the client code is generated from it (`scripts/generate-client.sh` in the template, `scripts/update-contract` in Franca). | The description is kept in the repository as `contracts/openapi.yaml`, because it is compared with the routes by a server test, and between versions by oasdiff. There is a check in the pipeline for generated types that are out of date. In Franca, types are generated with openapi-typescript and the API is called through openapi-fetch. The template has a generated client with service classes on axios, from @hey-api/openapi-ts. No reason for the choice of generator is recorded in the Git history. |
| Browser tests | The app is started for the tests by Playwright's `webServer`. Both have `forbidOnly` and retries in the pipeline, and a Desktop Chrome project. A trace is kept when a test fails. Chromium is taken from Playwright's image. | The tests run against the real server on a new SQLite database and the built client, where the template has its development server and Docker Compose. In the template, the test user is signed in once through the password form. There is no password sign-in in Franca, and Google's sign-in page cannot be used in a test, so a session is written to the test database (`client/e2e/helpers.ts`). Playwright's image is used unchanged and named by digest, because a tag can be moved to other content after it is published. `tools/check_pins.py` reports an image in a workflow without a digest as a problem. The template has its own image, built with bun. |
| Pipeline | Server tests and browser tests are separate jobs. The Python packages are installed with uv. No credentials are kept after the checkout, and test reports are deleted after a short time. | Actions are pinned by commit SHA where the template has version tags, because a tag can be moved to other content. The full commit SHA for GitHub Actions is listed in `docs/package-updates.md`. There is a Harden-Runner step at the start of the jobs (story E01-013). The browser tests are not split into shards, because there are few of them. |

The parts of the template that Franca does not use are PostgreSQL with SQLModel, password sign-in, shadcn/ui with Tailwind, and Traefik. Franca has SQLite, Google sign-in and passkeys, React Aria Components with styles written for Franca, and Caddy.
