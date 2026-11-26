# Tools

- `content_guard.py` uses the Python standard library only and is run with `python3 -I`. Keep it that way: it runs in Git hooks on computers that have no project environment.
- `check-startup-files.sh` is a shell script so that it does not start Python. Keep it that way.
- Tests are in `tests/` and run with the server's tests (`cd server && uv run pytest`).
