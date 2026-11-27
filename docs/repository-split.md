# What goes in which repository

The product owner decided on 26 November 2026 that Franca's code is kept in a public repository and its content in a private one (decision record [0001](decisions/0001-public-code-private-content.md)). A file that is pushed to a public repository can be copied before anyone notices, so course material must not reach this repository even for a moment.

## The three places

| Place | What is kept there |
|---|---|
| `franca` (this repository, public) | The app's code, tests, contracts, documentation, and the made-up fixture pack `fx` |
| `franca-content` (private) | Language packs, lessons, word lists, pictures, sound, video, harvested texts, and the source of the content guard's fingerprints |
| The owner's PC | Learner data, backups, secrets, and material that may not be shared under its licence |

If you are not sure where a file belongs, put it in `franca-content`.

## The content guard

The content guard, `tools/content_guard.py`, is run by both Git hooks (before a commit and before a push), by `scripts/check`, and by the pipeline (GitHub's automatic checks) after a push. It refuses a file version when:

- its path is under `packs/` (other than `packs/fixture/`), `harvest/`, `learner-data/`, `backups/` or `secrets/` at any level, or under `content/` or `media/` at the top level
- it is a database file, an `.env` file (other than `.env.example`), a key or certificate file, or `.gitmodules`
- its extension is a picture, sound, video, subtitle, e-book, office document or archive type
- its first bytes show that it is media, a PDF, an archive or a database, whatever it is called
- it is an SVG with an embedded picture, or a Git LFS pointer
- it is larger than 2 MB
- it has the private-content marker, which is written at the top of the files in `franca-content`
- it has text that looks like an API key, a token or a private key
- it is a copy of a file in `franca-content`, or has a line of 40 characters or more copied from one

Submodules are refused, because their address would be public. The push and pipeline checks also look at commit and tag messages for the marker, secrets and copied lines, and at files or folders that a tag points to directly.

A leak is prevented by the pre-push hook. The pipeline runs the same check on every branch and tag, but only after the push, when the file is already public. A pushed branch or tag is checked over its own history. GitHub sends no push event for some pushes, such as more than three tags at once, so a weekly run checks every branch and tag as well. Do not skip the hooks with `--no-verify`. The hooks are installed by `scripts/setup`.

When the repository is created, the product owner turns on secret scanning with push protection in its GitHub settings, as a second check for secrets.

## Fingerprints

The fingerprints for the copy check are in `tools/content-fingerprints.txt`, as HMAC-SHA-256 values of the private files and of their long lines. The values are made with a key that is kept in `franca-content` as `secrets/fingerprint-key`, and in this repository's Actions secrets as `FRANCA_FINGERPRINT_KEY`. Anyone who can read `franca-content` can read the content itself, so keeping the key there gives them nothing more. Without the key, nobody can tell from the values whether a given text is in `franca-content`.

When the fingerprint file has values, the guard needs the key and stops with a message if it is missing. Pull requests from forks get no Actions secrets, so the fingerprints are skipped in their check. They are checked in the merge queue before the merge, if the merge queue is turned on for `main`. On a developer's computer, the key is read from `~/.config/franca/fingerprint-key` or from the variable `FRANCA_FINGERPRINT_KEY`.

To refresh the fingerprints, run this in a checkout of `franca-content`:

```sh
python3 -I ../franca/tools/content_guard.py --fingerprint . > ../franca/tools/content-fingerprints.txt
```

The folders where icons and documentation screenshots may be kept are listed in `tools/content-guard-allowed-media.txt`. A file that matches one of those entries has to be a real PNG or ICO file.

## If the guard stops a commit

Take the file out of the commit with `git restore --staged <file>` and move it to `franca-content`. If the guard is wrong about a file, ask for a review before changing the guard.

## If course material was pushed by mistake

1. Tell the product owner straight away.
2. Make the repository private in its GitHub settings, so that no more copies can be made.
3. Remove the file from the history and force-push, then ask GitHub Support to remove cached views of the commit.
4. Treat anything in the file as possibly copied, and check whether a source's licence requires telling its owner.
