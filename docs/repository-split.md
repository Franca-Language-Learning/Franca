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

1. In the checkout of `franca`, run `git fetch`, so that `origin/main` is the latest public commit. The public values are read from that commit (`refs/remotes/origin/main`), not from the files in the checkout.
2. In the top folder of a checkout of `franca-content`, run:

   ```sh
   python3 -I ../franca/tools/content_guard.py --fingerprint . --public ../franca --output ../franca/tools/content-fingerprints.txt
   ```

   The command expects the checkout of `franca` to be in the same parent folder as `franca-content`. If it is somewhere else, replace each `../franca` with its path.

3. Read what is printed. The first line has the public commit and the URL of its remote. The URL should be the address of `Franca-Language-Learning/Franca` on GitHub. If it is another address, stop and tell the product owner. After that line there may be a list of pairs of paths for values that were left out (see "Values that are also in this repository" below).

   If the command stops with a list of pairs of paths, send the list to the product owner, without any text from the files, and do not go on to step 4.
4. If the output ends with a list of files that are not added to Git or that have changes that are not staged, their new text is not in the fingerprint file. Commit those files in `franca-content` and go back to step 2.
5. Commit `tools/content-fingerprints.txt` in `franca` on a new branch and open a pull request.

The fingerprint file is replaced in one step at the end of the run. If the command stops with a message, for example because the folder is not the top folder of a Git checkout, the old file is kept as it was. Do not redirect the output into the fingerprint file with `>`, because the shell empties the file before the command starts.

The guard stops with a message when the fingerprint file has no values, so a file that was emptied by mistake is caught. A fingerprint file for a test that is meant to have no values has the line `# No fingerprints`. That line is not accepted in `tools/content-fingerprints.txt`.

### Which files are fingerprinted

The fingerprints are made from the files in the Git index of `franca-content`, which are the files that Git tracks, in the version that was last staged. Files that Git does not track are not fingerprinted, such as the files in the `.venv` folder made by `uv sync` and in the caches of the test tools. Because the version in the index is read, a file that is not in the work tree because of a sparse checkout, or that was deleted from it, is still fingerprinted. Files with changes that are not staged, and files that are not added to Git and not ignored, are named when the command finishes (see step 4).

For a file stored with Git LFS, the index has a small pointer file in place of the content. The content is read with `git lfs smudge`. That is done for each path that uses the Git LFS filter, whatever the index has for it. If Git LFS is not installed or the content has not been downloaded, the command stops with a message that names the files. Install Git LFS, run `git lfs pull` in `franca-content` and run the command again.

Symbolic links that Git tracks are not followed, so the file a link points to is not read. If the checkout has a submodule or a merge conflict, the command stops with a message that names the paths. For a submodule, move its files into `franca-content` itself. For a merge conflict, finish the merge. Then run the command again.

These tracked files are not fingerprinted:

| Not fingerprinted | Where it is matched |
|---|---|
| The folder `secrets/`, with everything in it | At the top of the checkout |
| `course-config.yaml` | In any folder |

The keys in `secrets/` are not content. The fixture pack in this repository has a copy of the planner settings in `course-config.yaml` for the tests. If the file were fingerprinted, the guard would refuse that copy. The two lists are `NOT_FINGERPRINTED` and `NOT_FINGERPRINTED_NAMES` in `tools/content_guard.py`.

### Values that are also in this repository

Some files in `franca-content` have lines that are the same as lines in this repository, such as the line in a workflow that pins `actions/checkout`. If their values were in the fingerprint file, the guard would refuse the files of this repository that have the same line. With `--public`, the files in `origin/main` of the given checkout of `franca` are fingerprinted too, so that values in both repositories can be found. Another commit can be given with `--public-ref`. The commit and the URL of the remote are printed, so that a fork or an old commit can be noticed.

A private value that is the same as a public value is left out when:

- the private file is on the list of tooling files below, and the public file is outside `packs/`
- the public file is in `packs/fixture/` and has one comment line of the private file, such as the schema comment at the top of a lesson

In any other case the command stops with the pairs of paths, and the fingerprint file is not changed.

For the fixture pack, this means that the command stops when `packs/fixture/` has more of a file of `franca-content` than one comment line, such as a second line or the whole file. The lines are counted over all the files in `packs/fixture/` together. A comment line is a line of a YAML file that starts with `#` in the first column.

Course text can be in any folder of `franca-content`, such as `tests/` or `notes/`. For that reason the command also stops when a file that is not on the tooling list has text in a public file outside `packs/fixture/`. Even if that text is already public, its values are kept, so that the guard goes on refusing new copies of it.

The tooling files are listed in `TOOLING_PATHS` in `tools/content_guard.py`. A path that ends in `/` is a folder with everything in it. The paths are matched from the top of the checkout of `franca-content`, with their case. If a file has a path that differs from one of them only in case, such as `.GITHUB/workflows/check.yml`, the command stops. In that case, rename the file in `franca-content`, or tell the product owner.

| Path in `franca-content` | What it is |
|---|---|
| `.github/workflows/` | The GitHub Actions workflows |
| `.github/renovate.json` | The settings of Renovate, the tool that updates packages, in `.github/` |
| `pyproject.toml` | The Python project file at the top |
| `uv.lock` | The locked Python packages |
| `renovate.json` | The settings of Renovate, at the top |
| `.gitattributes` | Git's file for line endings and Git LFS |
| `.gitignore` | The list of files that Git ignores |

The files on the list are fingerprinted like the other files. The list is used only when a value is found in both repositories. If a refresh stops because of a file of `franca-content` that has no course text, tell the product owner. A file is added to the list only after a review.

For the left-out values, the pairs of paths are printed, the public file first and then the private file, with no text from the files. A pair is shown as "is a copy of" when the whole file is the same, and as "has lines that are in" otherwise. The pairs with tooling files and the pairs with the fixture pack are printed in two groups.

Before any public file is read, the checkout given with `--public` is checked, and the command stops in these cases:

- the commit has no `tools/content_guard.py`
- the commit has files that the guard keeps out of `franca`
- the commit and `HEAD` of `franca-content` start from the same first commit, which means that they share history

With these checks, a clone or a worktree of `franca-content` is refused. Because of the last check, the command also stops if `franca-content` has history from `franca`, for example because it was made from a copy of `franca`. If that happens with a real checkout of `franca`, tell the product owner.

The command stops if `--public` is missing. With `--skip-public`, all the values are kept. That option is meant for tests. Do not use it for a real refresh, because without `--public` the guard is likely to refuse files of this repository.

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
