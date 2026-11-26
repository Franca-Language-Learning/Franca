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
