# Installer

- The Windows part (`windows/`) is PowerShell 5.1, the version that comes with Windows. It is checked with PSScriptAnalyzer and Pester in the pipeline; locally only when `pwsh` is installed.
- The Linux part (`linux/franca_install.py`) and the updater it imports run with Debian 13's Python 3.13, so neither may use syntax that is new in 3.14. A test parses both with the 3.13 grammar, and ruff formats them for 3.13.
- No secret goes in a command line: the answers reach the Linux part as JSON on standard input.
- `infra/tests/rehearse_install.py` rehearses the Linux part with real containers.
