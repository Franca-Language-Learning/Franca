# Language pack schemas

A language pack is a folder of YAML files. There is a JSON Schema (draft 2020-12) for each type of file, and the pack builder (story E03-002) checks each file against its schema before anything is imported. The fixture pack in `packs/fixture/` has an example of each type of file, and the tests in `tests/` check it.

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
| `media/<name>.yaml` | `media.schema.json` | The record of a media file: licence, rights and transcript. The file itself is kept in the media store, not in the pack folder |
| `strings/<name>.yaml` | `strings.schema.json` | Interface text, element names and the glossary in the pack's language |

`common.schema.json` has the definitions the other schemas share, such as item keys, levels and bilingual text. The lists of allowed values (levels, registers, review states, parts of speech, media types and rights) are the same as the CHECK lists in `../db/schema.sql`, and a test fails if the two differ.

The schemas check each file on its own. Checks across files, such as whether a key that one file refers to exists in another, are made by the pack builder.
