# Packs

- Apart from these notes, this folder has the made-up fixture pack `fx` in `fixture/` and nothing else. Its text is placeholder text, written for the public tests.
- Real language packs, such as the Dutch one, are kept in the private repository `franca-content`. Do not copy material from a real pack into this repository. Any other path under `packs/` is refused by the content guard. See `docs/repository-split.md`.
- The fixture pack has an example of each type of pack file. When a schema for a new type of pack file is added to `contracts/pack/`, add an example of that type to `fixture/`. The fixture pack is checked by the schema tests in `contracts/pack/tests/`, which run with the server's tests (`cd server && uv run pytest`).
