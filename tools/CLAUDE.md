# Tools

- `content_guard.py` uses the Python standard library only and is run with `python3 -I`. Keep it that way: it runs in Git hooks on computers that have no project environment.
- `check-startup-files.sh` must stay a shell script, because starting Python would run the start-up files it checks.
- Tests are in `tests/` and run with the server's tests (`cd server && uv run pytest`).
- `install_program.py` uses the Python standard library only and is run with `python3 -I`, like the content guard. The programs it downloads are listed in `programs.txt`, one per line, with the SHA-256 of the file, under a platform line for the .tar.gz files and the bare program files. Keep the columns as they are: Renovate's managers in `.github/renovate.json` read them, and a test compares the two.
- `run_osv_scanner.py` runs OSV-Scanner and `check_osv_results.py` reads its JSON output in the OSV-Scanner workflow. They use the Python standard library only and are run with `python3 -I`, so the job needs no project environment.
