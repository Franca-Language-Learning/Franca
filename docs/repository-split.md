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

- its path is under `packs/` (other than `packs/fixture/` and the notes in `packs/CLAUDE.md`), `harvest/`, `learner-data/`, `backups/` or `secrets/` at any level, or under `content/` or `media/` at the top level
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

To refresh the fingerprints:

1. In the checkout of `franca`, run `git fetch`, so that `origin/main` is the latest public commit. The public values are read from that commit, not from the files in the checkout.
2. In the top folder of a checkout of `franca-content`, run:

   ```sh
   python3 -I ../franca/tools/content_guard.py --fingerprint . --public ../franca --output ../franca/tools/content-fingerprints.txt
   ```

3. Read the list of paths that is printed for the left-out values (see below). The command stops if a course file of `franca-content` has text in a public file outside `packs/fixture/`. Tell the product owner if that happens.
4. Read the list of files that are not added to Git or have changes that are not staged, if there is one. Their new text is not fingerprinted. Add and commit them in `franca-content`, then run the command again.
5. Commit `tools/content-fingerprints.txt` in `franca` on a new branch and open a pull request.

The fingerprint file is written after the values are made. If the command stops with a message, for example because the folder is not the top folder of a Git checkout, the fingerprint file is not changed. Do not redirect the output into the fingerprint file with `>`, because the file is emptied by the shell before the command starts. The guard stops with a message when the fingerprint file has no values, so an emptied file is noticed. A fingerprint file for a test that is meant to have no values has the line `# No fingerprints`. That line is not accepted in `tools/content-fingerprints.txt`.

### Which files are fingerprinted

The fingerprints are made from the files in the Git index of `franca-content`, which are the files that Git tracks, in the version that was last staged. Files that Git does not track are left out, such as the files in the `.venv` folder made by `uv sync` and in the caches of the test tools. Because the version in the index is read, a file that is left out of the work tree by a sparse checkout, or that was deleted from it, is still fingerprinted. Files with changes that are not staged, and files that are not added to Git and not ignored, are named when the command finishes, because their new text is not fingerprinted.

For a file stored with Git LFS, the index has a small pointer file. The content is read with `git lfs smudge`. If Git LFS is not installed or the content has not been downloaded, the command stops with a message that names the files.

Tracked links are not followed. If the checkout has a submodule or a merge conflict, the command stops with a message that names the paths.

These tracked files are left out:

| Left out | Where it is matched |
|---|---|
| The folder `secrets/`, with everything in it | At the top of the checkout |
| `course-config.yaml` | In any folder |

The keys in `secrets/` are not content. The planner settings in `course-config.yaml` are left out because the fixture pack in this repository has the same settings, so that the tests use them. The lists are `NOT_FINGERPRINTED` and `NOT_FINGERPRINTED_NAMES` in `tools/content_guard.py`.

### Values that are also in this repository

Some files in `franca-content` have lines that are the same as lines in this repository, such as the line in a workflow that pins `actions/checkout`. If their values were in the fingerprint file, the guard would refuse the files of this repository that have the same line. With `--public`, the values of the files in `origin/main` of the given checkout of `franca` are made as well, and the private values that match one of them are left out. Another commit can be given with `--public-ref`. Each pair of paths is then printed, the public file first and then the private file it matches, with no text from the files. A pair is shown as "is a copy of" when the whole file is the same, and as "has lines that are in" otherwise. The pairs with the fixture pack are printed in a group of their own.

A match between a course file and a public file is handled differently. If a file under `packs/`, `harvest/` or another private folder of `franca-content` has text in a public file outside `packs/fixture/`, the command stops and the fingerprint file is not changed. The text may already be public, and leaving its values out would let more copies through.

Before any public file is read, the checkout given with `--public` is checked, and the command stops in these cases:

- the commit has no `tools/content_guard.py`
- the commit has files that the guard keeps out of `franca`
- the first commit of its history is also a first commit of `franca-content`

So a clone or a worktree of `franca-content` is refused.

The command stops if `--public` is missing. With `--skip-public`, all the values are kept. That option is meant for tests, because without `--public`, files of this repository are likely to be refused by the guard.

The folders where icons and documentation screenshots may be kept are listed in `tools/content-guard-allowed-media.txt`. A file that matches one of those entries has to be a real PNG or ICO file.

## If the guard stops a commit

Take the file out of the commit with `git restore --staged <file>` and move it to `franca-content`. If the guard is wrong about a file, ask for a review before changing the guard.

## Interaction limit on the organisation's public repositories

Only members of the organisation and people with write access to this repository can take part in its issues and pull requests. This is an interaction limit in the settings of the organisation `Franca-Language-Learning`, and it applies to the organisation's public repositories. The longest limit on GitHub is six months, so the limit runs out and has to be renewed by hand. The limit that is on now runs out on 27 May 2027 at 07:27 UTC. A reminder from a scheduled task in Claude is due in May 2027.

To renew the limit:

1. Sign in to GitHub with an account that is an owner of the organisation `Franca-Language-Learning`.
2. Open the organisation's page and click **Settings**. In the menu on the left, under **Access**, click **Moderation** and then **Interaction limits**.
3. Under **Temporary interaction limits**, find **Limit to repository collaborators**.
4. To the right of it, open the **Enable** list and click **6 months**. If there is a **Disable** button in place of **Enable**, the old limit is still on. Click **Disable**, then open the **Enable** list and click **6 months**.
5. Check the end date that GitHub shows on the page. Change the date in this section to the new one, and make a reminder for a week before it.

Someone who uses the GitHub command line and is an owner can renew the limit with one command instead, with no gap between the old limit and the new one:

```sh
gh api --method PUT orgs/Franca-Language-Learning/interaction-limits -f limit=collaborators_only -f expiry=six_months
```

## If course material was pushed by mistake

1. Tell the product owner straight away.
2. Make the repository private in its GitHub settings, so that no more copies can be made.
3. Remove the file from the history and force-push, then ask GitHub Support to remove cached views of the commit.
4. Treat anything in the file as possibly copied, and check whether a source's licence requires telling its owner.
