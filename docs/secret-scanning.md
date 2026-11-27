# Secret scanning

Secrets such as keys and passwords are not allowed in this repository (story E01-013). The repository is public, so a secret that is committed can be copied before it is removed, even when a later commit deletes it. For this reason the history is scanned as well as the current files.

## What is scanned

The history of the checked-out commit is scanned with [gitleaks](https://github.com/gitleaks/gitleaks), in two places:

| Where | When | Command |
|---|---|---|
| Pipeline, workflow "Secret scan" | Pull requests, the merge queue, pushes to `main`, and a weekly run on Monday | `scripts/check secrets` |
| A developer's computer | With the other checks, or on its own | `scripts/check` or `scripts/check secrets` |

Merge commits are scanned too. For a merge with two parents, the part that the person who merged wrote is scanned, for example the way a merge conflict was resolved. In git's terms, this is the difference between git's own merge of the two parents and the merge commit (`git log --diff-merges=remerge`). The changes from the merged branch are scanned in that branch's commits and are not scanned again under the merge commit. For this reason, a finding that is listed in `.gitleaksignore` does not come back with the merge commit's fingerprint. A merge with more than two parents (an octopus merge) has no such view in git, so it is scanned as the difference from each parent.

gitleaks is downloaded from its release page by `tools/install_program.py` and kept only when its SHA-256 matches the one in `tools/programs.txt`. Renovate updates the version and the hash on the same line, seven days after a release. The download is kept in `~/.cache/franca/programs`, so the scan needs no network after the first run.

The file is for Linux on x86-64. On another computer nothing is downloaded, the scan is left to the pipeline, and `scripts/check` shows a message about this. The same message is shown when gitleaks cannot be downloaded, for example with no network. A download with another SHA-256 fails the check, on a computer and in the pipeline.

The scan needs git 2.36 or later. With an older git, `scripts/check secrets` fails with a message that says so. The check is needed because gitleaks reports no leaks, without scanning anything, when it cannot read the history.

Each finding is printed with its file, line, commit, rule and fingerprint, and with the secret replaced by REDACTED. The name and e-mail address of the commit's author are printed too. They are public in the history already. No report is uploaded.

## Agent session logs

The session logs and transcripts of the AI agents that work on Franca are not kept in this repository, so the pipeline has none to scan. If they are saved in a folder later, the folder is to be named in this section, and they are scanned there with the same gitleaks:

```sh
"$(python3 -I tools/install_program.py gitleaks)" dir --redact --verbose --no-banner <folder with the logs>
```

## When the scan finds something

The job "Secret scan" fails, and the findings are listed in its log.

1. Open the pull request on GitHub, select the **Checks** tab, and open the job "Secret scan". Each finding starts with the line `Finding:`, and has the lines `File:`, `Line:`, `Commit:`, `RuleID:` and `Fingerprint:`.
2. Open the file at that line, and decide whether the value is a real secret or a made-up value, for example in a test.
3. If it is a made-up value, add the finding's fingerprint (the text after `Fingerprint:`) as a new line in `.gitleaksignore`, with a comment line above it that says what the value is. Make this change in the same pull request.
4. If it is a real secret, it has to be replaced, because the old commit is public and can be copied:
   1. Sign in to the service the secret belongs to (for example the Google Cloud console for the Google client secret, or the Tailscale admin console for the auth key). Revoke or delete the old secret, and make a new one.
   2. Remove the secret from the code in the same pull request.
   3. Give Franca the new secret. Franca's secrets are kept in the folder `/opt/franca/secrets` inside the Franca WSL distribution on the PC, and never in the repository. For the Google client secret or the Tailscale auth key, run the installer again (`docs/installing-franca.md`) and give the new value when asked. The installer writes it to that folder and keeps the other secrets.
   4. Add the finding's fingerprint to `.gitleaksignore`, with a comment line that says the secret was revoked and on which date. The revoked secret stays in the history, so without this line the scan fails on each later pull request.

If a finding that is in `.gitleaksignore` comes back under a merge commit, add the new fingerprint as well. This can happen with a merge that was made with another merge strategy, or after a git update that changes how git merges.
