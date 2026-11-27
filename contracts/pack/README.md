# Language pack schemas

A language pack is a folder of YAML files. There is a JSON Schema (draft 2020-12) for each type of file, and the files are checked against their schemas by `tools/validate_pack.py`, and by the pack builder (story E03-002) before anything is imported. The fixture pack in `packs/fixture/` has an example of each type of file. The fixture pack is checked by the tests in `tests/`, and by `tools/validate_pack.py` in `scripts/check`.

| File in the pack | Schema | What the file has |
|---|---|---|
| `pack.yaml` | `pack.schema.json` | The language, its varieties and speakers, paradigm cells, verb classes, word decks, learner goals and exams |
| `course-config.yaml` | `course-config.schema.json` | The settings for the lesson planner |
| `lexicon/<name>.yaml` | `lexeme.schema.json` | A word: its senses, forms, verb details and pronunciation |
| `chunks/<name>.yaml` | `chunk.schema.json` | A fixed phrase or pattern |
| `grammar/<name>.yaml` | `grammar-point.schema.json` | A grammar point: explanations, decision rules, examples, exceptions and checker rules |
| `sounds/<name>.yaml` | `sound.schema.json` | A sound, or a contrast between two sounds with minimal pairs |
| `scenarios/<name>.yaml` | `scenario.schema.json` | A scenario for the AI conversation partner |
| `course/<name>.node.yaml` | `course-node.schema.json` | A level, stage, unit or domain module in the course tree |
| `course/<name>.lesson.yaml` | `lesson.schema.json` | A lesson |
| `course/<name>.can-do.yaml` | `can-do.schema.json` | A can-do descriptor and the items that count as evidence for it |
| `media/<name>.yaml` | `media.schema.json` | The record of a media file, with its licence and rights details and, for audio and video, a transcript. The file itself is kept in the media store, not in the pack folder |
| `strings/<name>.yaml` | `strings.schema.json` | Interface text, element names and the glossary in the pack's language |

`common.schema.json` has the definitions the other schemas share, such as item keys, levels and bilingual text. Some lists of allowed values (levels, registers, review states, parts of speech, media types and rights) are the same as the CHECK lists in `../db/schema.sql`. Others (licences, learner goals, interface elements and error types) are the same as the reference data in `../db/seed.sql`. There is a test that fails if a list differs from the database. The lengths and ranges that the schemas copy from the database, such as the weight of a goal or the length of an element name, are not compared by a test.

## Checking a pack folder

The YAML files in a pack folder are checked against the schemas by `tools/validate_pack.py`, with the format checker, so that a date such as 2026-13-45 is a problem. A mapping with a duplicate key is a problem, and so is a file whose path matches no file type. The checks across files in the next section are not made.

There is no text from the pack in the output, so the command can be run on a private pack in a pipeline whose log other people can read. A problem is printed as one line with the file path, the name of the failed rule and the place in the file. Rule names are the JSON Schema keywords, such as `required` or `enum`, and `duplicate-key`, `yaml-syntax` and `unknown-file-type`. The place is a JSON pointer, with `*` for a key that the schemas do not name, or a line and column for a YAML error. The last line has the number of files checked and the number of problems. The exit code is 0 for no problems, 1 for problems and 2 for a usage error.

The command is run with the locked packages of the server (`uv.lock` at the root of the repository), and there is no network access once they are installed. From the root of a checkout:

```
uv run --project server --frozen --no-dev python -I tools/validate_pack.py packs/fixture
```

To run it in a workflow in another repository, such as Franca-Content:

1. Check out this repository at a pinned commit into a folder, for example `franca`, with `actions/checkout` (`repository: Franca-Language-Learning/Franca`, `ref: <commit>`, `path: franca`, `persist-credentials: false`).
2. Install uv with `astral-sh/setup-uv`, with `working-directory: franca`, so that the uv version pinned in `franca/pyproject.toml` is installed.
3. Run `uv run --project franca/server --frozen --no-dev python -I franca/tools/validate_pack.py <pack folder>`.

With Harden-Runner in block mode, the allowed hosts are the ones for the Python job in `.github/workflows/ci.yml`, without the PowerShell Gallery. uv and Python 3.14 are downloaded from `releases.astral.sh`, and the packages from `files.pythonhosted.org`.

## Checks made by the pack builder

Each file is checked against its schema on its own, with the format checker, and a file with a duplicate key in a mapping is refused when it is loaded. These checks cannot be written in JSON Schema, so they are made by the pack builder (story E03-002):

- A key that one file refers to is defined in the pack, and the type of file it is defined in fits the place where it is used.
- Keys that have to be unique within a list are unique: varieties, speakers, paradigm cells, verb classes, decks, goals and exams in `pack.yaml`, explanation sections, step ids and checker rule ids in a grammar file, glossary keys, the evidence items of a can-do component, and the pictures of a sense.
- A form that does not exist is the only variant in its cell.
- A grammar point does not require itself.
- In a domain module, `terminology_from` is not later than `tasks_from`.
- In a transcript, a line or a word ends after it starts.
- The size and hash of each media file match the media store.

## Data that is not imported into the database

`typology`, `fonts` and `reading_aids` in `pack.yaml`, and the checker rules in grammar files, have no tables. They are kept in the pack file, and where the app reads them from is worked out in story E03-002.

The distribution of a pack version (private or shareable) is not written in `pack.yaml`. It is worked out by the pack builder from the rights of the media files in the pack.

The lesson in `packs/fixture/course/` is the planner's test lesson, and it refers to keys outside the fixture pack. The other keys that the fixture files refer to are defined in the fixture. The pack builder's tests leave the lesson out of the checks across files.
