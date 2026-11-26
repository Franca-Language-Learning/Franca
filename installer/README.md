# Installer

The installer for the owner's Windows PC (stories E01-011 and E01-012). The owner's steps are in `docs/installing-franca.md`. Each release has the installer as `franca-installer.zip`, made by the release workflow from these files, the updater (`infra/updater/franca_updater.py`) and `infra/compose.yaml`.

| File | What it is |
|---|---|
| `windows/Install-Franca.cmd` | Starts the Windows part with administrator rights |
| `windows/Install-Franca.ps1` | The Windows part: WSL, the Franca system, the questions, the scheduled task and the power settings |
| `windows/PSScriptAnalyzerSettings.psd1` | The settings for PSScriptAnalyzer, which checks the Windows part in the pipeline |
| `windows/tests/Install-Franca.Tests.ps1` | Pester tests of the Windows part's functions that do not need Windows |
| `linux/franca_install.py` | The Linux part, which runs as root in the Franca system with Debian's Python 3.13 |
| `linux/tests/test_install.py` | Tests of the Linux part. They run with the server's tests |

## How Franca runs on the PC

- Franca runs in a WSL 2 system called Franca, with Debian and systemd. Docker Engine runs there as a service, so Docker Desktop is not needed.
- The bundle is in `/opt/franca` inside that system: `compose.yaml`, `.env` and the `secrets` folder. The data is in Docker volumes inside the system, not on the Windows disk.
- The backups go to `/mnt/j/franca-backups`, which is a folder on disk J:. `/etc/wsl.conf` mounts Windows disks with the `metadata` option, so that the folder can belong to the backup container's user (10001).
- A scheduled task called Franca runs `wsl.exe -d Franca -u root -- sleep infinity` when the PC starts, as the owner, with S4U, so no password is stored. The task keeps the Franca system running; systemd starts Docker in it, and Docker starts the containers.
- Sleep and hibernation on mains power are switched off.

## The Linux part

The answers are given as JSON on standard input, so that no secret appears in a command line. The steps are in the module's docstring. The Linux part can be run again: the generated secrets are kept, and the backup password and the topic are shown only when they are made.

Before the first release exists, or in the rehearsal, `--release-file` names local images, and `--skip-docker` and `--ntfy-url` leave out the steps that need the internet. `infra/tests/rehearse_install.py` runs the Linux part this way in the pipeline, with Headscale in place of Tailscale.

## Known limits

- The Windows part cannot be tested in the pipeline, because GitHub's Windows machines cannot run WSL 2. Its functions that do not need Windows have Pester tests, and the rest is tried on the owner's PC at the M0 rehearsal.
- `wsl.exe --install` with `--name` and `--location` needs a recent WSL. The installer runs `wsl.exe --update` first.
- A scheduled task with S4U is the way to start WSL before anyone signs in without storing a password. If it does not start WSL on the owner's PC, the task can be changed to store the owner's password, which the owner types in Task Scheduler.
- The updater changes image references in `.env` and not `compose.yaml`. A release that changes `compose.yaml` needs the installer to be run again.
