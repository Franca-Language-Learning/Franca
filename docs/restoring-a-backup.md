# Restoring a backup

Franca is backed up each night to the backup folder on disk J: (story E01-008). The backups are encrypted with the backup password, which the installer showed you once and asked you to keep in your password manager. Without that password the backups cannot be read.

Once a month a backup is restored as a test, in a scratch folder, and checked. The result is in `restore-test.json` in the backup status volume, and the health monitoring (story E01-010) will tell you if a test fails.

## Putting back the latest backup

Do this only if Franca's data is lost or damaged. Everything learned since the last backup (at most a day) is lost. The current database is kept beside the restored one, as `franca-before-restore-<date and time>.db`, in case it is needed.

1. Open a terminal (on Windows: PowerShell) in the Franca bundle folder, the folder with `compose.yaml` and `.env` in it.
2. Stop the app:

   ```
   docker compose stop app
   ```

3. Put back the latest backup:

   ```
   docker compose run --rm backup python /app/franca_backup.py restore-latest
   ```

   The last line of the output says `"result": "restored"` when it worked. If it says `refused`, the app is still running: do step 2 again.
4. Start the app again:

   ```
   docker compose up -d app
   ```

5. Open Franca and check that your progress is there.

## Restoring an older backup

The backups of the last 14 days, the last 8 weeks and the last 12 months are kept. Restoring one of the older ones is not a one-step job yet; ask Claude for help, and have the backup password ready.
