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

The uv version is pinned in `required-version` in `pyproject.toml`. The same version is installed in the pipeline, because setup-uv reads it from there when no version is given. It is pinned because `tools/startup-files-allowed.txt` has the hash of the `_virtualenv.py` file that uv writes into each environment. Renovate updates it in a pull request that has to be reviewed. If the start-up file check fails, read the new `_virtualenv.py`, then update its hash in `tools/startup-files-allowed.txt` in the same pull request. After the merge, developers install the new version with `uv self update <new version>`, or with the package manager they used to install uv.

## Container images

The container images are built and scanned with Grype in the pipeline. A finding with a severity of high or critical stops the pipeline when a fixed version exists. The final stage of each image installs the operating system's security updates, so most findings in Debian or Alpine packages are fixed by building the images again. Renovate updates the base images.

When a finding does not apply to Franca and the fix is not released yet, it can be ignored in `.grype.yaml`, with a comment that says why it does not apply. A rule names the package version, so it stops applying when the package is updated. Remove a rule when the fixed version is in the image.

## Images, source code, programs and the browser pinned by digest, commit or hash

A tag such as `python:3.14.10-slim-trixie` or `v0.19.1` can be moved to other content after it is published. So the images, source code and programs that Franca is built with are pinned as shown here:

| What | How it is pinned | Updated by Renovate through |
|---|---|---|
| Base images in the Dockerfiles, including `COPY --from` images such as uv | `image:tag@sha256:...` | The Dockerfile manager |
| Helper images in `infra/compose.yaml` | `image:tag@sha256:...` | The Compose manager |
| Images in the scripts and workflows, including the BuildKit builder of the release | `image:tag@sha256:...` with a `# renovate: image` comment | The custom managers in `.github/renovate.json` |
| Source code cloned in the Dockerfiles | The release tag, and a check of the commit it points to | The custom manager for cloned sources. These updates are reviewed before they are merged |
| Chromium for the browser tests | Playwright's image, by digest | Grouped with `@playwright/test`, because the versions have to match |
| pnpm | The version and its SHA-512 in `packageManager` in `package.json`. The hash is checked by Corepack in the pipeline and in `caddy.Dockerfile` | The npm manager |
| Node.js in the pipeline | The version in `.nvmrc`, the same as the Node image in `caddy.Dockerfile`, and the two are updated together | The nvm and Dockerfile managers |
| gitleaks (in the pipeline and by `scripts/check`), and Grype, Syft and PSScriptAnalyzer (in the pipeline) | The version and the SHA-256 of the release file in `tools/programs.txt`. The download is checked by `tools/install_program.py` | The custom manager for `tools/programs.txt`, which updates the version and the hash together. These updates are reviewed before they are merged (see below) |
| Pester, downloaded in the pipeline | The version and the SHA-256 of the `.nupkg` file in `tools/programs.txt` | The custom manager for PowerShell Gallery modules. Renovate updates the version, and the hash is updated with `tools/update_pester_hash.py` (see below). These updates are reviewed before they are merged |
| cosign in the installer | The version in the address and the SHA-256 of the file | The custom manager for the installer's programs, which updates the version and the hash together. The download is checked against the hash in the Container bundle job. These updates are reviewed before they are merged |
| GitHub Actions | The full commit SHA, with the tag in a comment | The GitHub Actions manager |

Franca's own images are named by digest in the release file, which is read by the installer and the updater.

Renovate reads the hash of a program from GitHub by finding the release file that has the current hash, and writes the hash of the same file in the new release. This is done with Renovate's `github-release-attachments` datasource, which has release dates, so the seven-day rule applies.

A download by `tools/install_program.py` that fails with a connection error, a timeout, HTTP 429 or HTTP 5xx is tried again after 5 seconds and again after 15 seconds. A download that fails with HTTP 403 for an address on the PowerShell Gallery (`www.powershellgallery.com` or `cdn.powershellgallery.com`), before or after redirects, is tried again in the same way, because the gallery has refused a request once and accepted it on the next run. Before a new try, a line with the address, the reason and the number of the try is written to standard error, which is the job's log in the pipeline. Other HTTP errors, and a download with another hash, fail at once.

### Updates to the pinned programs are reviewed

Grype and Syft run in the release job that signs the images, cosign checks the signatures of Franca's images, and gitleaks, PSScriptAnalyzer and Pester check the code. With a hash pin, a release file that is replaced after it is published is noticed, and a bad release that is still there after seven days is not. For this reason Renovate does not merge updates to these programs. Its pull requests have the label `needs-review` and wait for a person, who reads the release notes and checks that the release comes from the usual publisher before merging. A pull request that changes the hash of a program without changing its version means that a release file was replaced, and is not merged either.

There are no model files yet. The speech models (epic E09) will be pinned by hash in the same way.

### Updating the hash of Pester

These steps are for the developer who does the weekly maintenance.

Pester is published on the PowerShell Gallery and not as a GitHub release file, and Renovate cannot read a hash from the gallery. When Renovate updates Pester's version in `tools/programs.txt`, the hash on that line is still the old one, and the job "Server, contracts and tools" fails with a message that has both hashes. To finish the pull request:

1. Check out the Renovate branch of the pull request.
2. Run this from the root of the checkout:

   ```sh
   python3 -I tools/update_pester_hash.py
   ```

   The new `.nupkg` file is downloaded, and its SHA-512 is compared with the package hash that the gallery publishes for that version.
3. If the message starts with "The gallery's hash matches", the SHA-256 has been written on the Pester line of `tools/programs.txt`. Commit that change to the Renovate branch, push it, and wait for the checks to pass. Then review and merge the pull request as in the previous section.
4. If the message starts with "The hashes do not match", stop. Nothing has been written. Do not merge the pull request. Open an issue in the Franca repository with the message, the version and the address of the pull request.

### Images from registries other than Docker Hub

Renovate reads release dates from Docker Hub only. The images on other registries are handled like this:

| Image | How the seven-day rule is applied |
|---|---|
| `lscr.io/linuxserver/socket-proxy` | The same image, with the same digests, is published on Docker Hub as `linuxserver/socket-proxy`. Renovate looks up versions and digests there (`overridePackageName` in `.github/renovate.json`), so the rule applies. The socket proxy can reach the Docker socket, so its updates are reviewed before they are merged |
| `ghcr.io/astral-sh/uv` | The same, with `astral/uv` on Docker Hub. uv updates are reviewed before they are merged for another reason (see "uv itself") |
| `mcr.microsoft.com/playwright` | Not applied, because the image is on mcr.microsoft.com alone and has no release date. This is the reviewed-update exception. Its updates are reviewed before they are merged, and an update cannot be merged before the matching `@playwright/test` update, which waits seven days, because the two versions are compared in `infra/tests/test_browser_image.py` |

The digests were compared on 27 November 2026 (socket-proxy 3.4.8-r0-ls107 and uv 0.11.32 had the same digest on both registries). If the digests on the two registries ever differ, the Renovate pull request for that image fails in the Container bundle job, because the bundle cannot be pulled. Do not merge it, and ask the developer to remove the `overridePackageName` rule for that image.

`tools/check_pins.py` is run with the server's tests and in the Container bundle job, and fails when an image has no digest, a pinned image in a Python script or workflow has no `# renovate: image` marker, or a cloned source has no commit check. Renovate adds the digest when it updates an image. To add one by hand, run this on a computer with Docker and access to the registries, and copy the digests that are printed into the files:

```sh
python3 -I tools/check_pins.py --resolve
```

The same command is run in the Container bundle job, so the digests can also be read from its log.

## Allowed endpoints in the pipeline

Most jobs in the pipeline start with Harden-Runner in block mode (story E01-013). A connection from a job to a host that is not on the job's list of allowed endpoints is refused. The list is `allowed-endpoints` under the Harden-Runner step of that job, in the workflow file in `.github/workflows/`. Some of GitHub's own hosts, such as the storage for logs and artifacts, are allowed by Harden-Runner without being listed. The GitHub hosts that a job calls, such as github.com, are listed anyway. The jobs in `release.yml` are in audit mode until the first release, and their lists will be written from that release's logs. The OSV-Scanner workflow is run from Google's reusable workflow, which has no Harden-Runner step.

After a change that adds a new place to download from, such as a package index or an image registry, a job can fail because a connection was refused. To find the host and add it:

1. Open the failed job from the pull request's **Checks** tab, and open the step **Post Run step-security/harden-runner** at the end of the job's log.
2. The blocked host is given on the lines with `domain not allowed:` or `ip address dropped:`. Each connection is on a line starting with `endpoint called`, with the name of the program that made it.
3. Check that the job needs the host. A call for telemetry or an update check can stay blocked if the job passes without it.
4. In a pull request, add the host as `host:port` (for example `files.pythonhosted.org:443`) to the list of that job, in alphabetical order, one per line. A wildcard such as `*.data.mcr.microsoft.com:443` is accepted for hosts that change from run to run. Keep a wildcard as narrow as you can, and do not add a whole cloud domain such as `*.amazonaws.com`. Say in the pull request why the host is needed.

The check in `tools/check_harden_runner.py` is part of `scripts/check python`. A job with no Harden-Runner step, or with Harden-Runner in audit mode outside `release.yml`, is reported as a problem, and so is a list that is empty or out of order. The list is written as a folded block (`allowed-endpoints: >`), because Harden-Runner reads the endpoints as one line with spaces between them. A list in a `|` block is reported too.
