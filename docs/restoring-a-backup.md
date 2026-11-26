# Restoring a backup

Franca is backed up nightly to the backup folder on disk J:. The backups are encrypted with the backup password, which the installer showed you once and asked you to keep in your password manager. Without that password the backups cannot be read.

Once a month a backup is restored as a test, in a scratch folder, and checked. When a backup or a test fails, or does not run, an alert is sent to your phone (see `docs/health-alerts.md`).

## Putting back the latest backup

Do this only if Franca's data is lost or damaged. Everything learned since the last backup (at most a day) is lost. The current database is kept beside the restored one, as `franca-before-restore-<date and time>.db`, in case it is needed.

1. In File Explorer, open the Franca folder (the one with `compose.yaml` and `.env` in it). Right-click an empty part of the folder and choose **Open in Terminal**.
2. Stop the app:

   ```
   docker compose stop app
   ```

   The output ends with a line that says `Stopped`.

3. Put back the latest backup:

   ```
   docker compose run --rm backup python /app/franca_backup.py restore-latest
   ```

   The last line of the output says `"result": "restored"` when it worked. If it says `refused`, the app is still running. Do step 2 again. If it says anything else, stop, copy the output and ask Claude for help.
4. Start the app again:

   ```
   docker compose up -d app
   ```

   The output ends with a line that says `Started`.

5. Open Franca at the address you normally use and check that your progress is there. If it isn't, ask Claude for help. Your old data is still in the `franca-before-restore` file.

## Restoring an older backup

These backups are kept:

- one a day for 14 days
- one a week for 8 weeks
- one a month for 12 months

The steps for restoring an older backup are not written up yet. Ask Claude for help, and have the backup password ready.
