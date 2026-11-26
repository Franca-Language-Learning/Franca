# Package updates

## The seven-day rule

A package release is not installed until it is seven days old, so that a release that is found to be malicious in its first days is not picked up. The rule is in three places:

| Tool | Setting | File |
|---|---|---|
| uv | `exclude-newer = "7 days"` | `pyproject.toml` |
| pnpm | `minimumReleaseAge: 10080` (minutes) | `pnpm-workspace.yaml` |
| Renovate | `"minimumReleaseAge": "7 days"` | `.github/renovate.json` |

uv and pnpm apply the rule while resolving versions, so a release younger than seven days is not written to the lock file, even when that version is asked for by name.

## Installing a security fix sooner

Renovate opens a pull request for a vulnerability straight away, but the lock cannot be updated until the fixed release is seven days old. To install the fix sooner:

1. Read the advisory and the release, and check that the fixed release comes from the package's usual publisher.
2. Add an exception for that package only, with a comment that names the advisory:
   - uv: in `pyproject.toml` under `[tool.uv]`, add `exclude-newer-package = { "<package>" = "<date and time after the release>" }`.
   - pnpm: in `pnpm-workspace.yaml`, add the package to `minimumReleaseAgeExclude`, as `<package>@<fixed version>`.
3. Update the lock (`uv lock --upgrade-package <package>` or `pnpm update <package>`), run `scripts/check`, and merge the change.
4. Remove the exception after seven days, in a separate change.

## uv itself

The uv version is pinned in `required-version` in `pyproject.toml` and in the `version` of setup-uv in `.github/workflows/ci.yml`. It is pinned because `tools/startup-files-allowed.txt` has the hash of the `_virtualenv.py` file that uv writes into each environment. Renovate updates both places in one pull request, which waits for a review. If the start-up file check fails, read the new `_virtualenv.py`, then update its hash in `tools/startup-files-allowed.txt` in the same pull request. After the merge, developers install the new version with `uv self update <new version>`, or with the package manager they used to install uv.

## Container images

The container images are built and scanned with Grype in the pipeline. A finding with a severity of high or critical stops the pipeline when a fixed version exists. The final stage of each image installs the operating system's security updates, so most findings in Debian or Alpine packages are fixed by building the images again. Renovate updates the base images.

When a finding does not apply to Franca and the fix is not released yet, it can be ignored in `.grype.yaml`, with a comment that says why it does not apply. A rule names the package version, so it stops applying when the package is updated. Remove a rule when the fixed version is in the image.

## Images, source code and the browser named by digest

A tag such as `python:3.14.10-slim-trixie` or `v0.19.1` can be moved to other content after it is published. So the images and source code that Franca is built from are named by digest or commit as well:

| What | How it is pinned | Updated by Renovate through |
|---|---|---|
| Base images in `infra/images/*.Dockerfile` | `image:tag@sha256:...` | The Dockerfile manager |
| Helper images in `infra/compose.yaml` | `image:tag@sha256:...` | The Compose manager |
| Images in the rehearsal scripts and workflows | `image:tag@sha256:...` with a `# renovate: image` comment | The custom managers in `.github/renovate.json` |
| Source code cloned in the Dockerfiles | The release tag, and a check of the commit it points to | The custom manager for cloned sources. These updates wait for a review |
| Chromium for the browser tests | Playwright's image, by digest | Grouped with `@playwright/test`, because the versions have to match |
| GitHub Actions | The full commit SHA, with the tag in a comment | The GitHub Actions manager |

Franca's own images are named by digest in the release file that the installer and the updater read.

There are no model files yet. The speech models (epic E09) will be pinned by hash in the same way.

`tools/check_pins.py` is run with the server's tests and in the Container bundle job, and fails when an image has no digest or a cloned source has no commit check. Renovate adds the digest when it updates an image. To add one by hand, run this on a computer where Docker can reach the registries, and copy the digests it prints into the files:

```sh
python3 -I tools/check_pins.py --resolve
```

The Container bundle job runs the same command, so the digests can also be read from its log.
