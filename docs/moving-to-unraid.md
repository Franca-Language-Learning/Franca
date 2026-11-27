# Moving Franca to an Unraid server

These are the steps for moving Franca from the Windows PC to an Unraid server, when there is one (story E01-012). Your progress is moved with the latest backup. The Tailscale name stays the same, so the address stays the same.

In these steps, "the bundle" means all of Franca's containers together, and "the app" is the container with Franca's server. "The Franca system" is the Linux system on the PC that the bundle runs in.

None of these steps has been tried on an Unraid server yet. They are based on the installer and on the steps in `docs/restoring-a-backup.md` and `docs/private-network.md`. Names of buttons, pages and settings in Unraid's web page are marked "(not checked yet)", because nobody has checked them on a server. Allow about an hour, and plan it for a day when nobody needs Franca.

## What is not automated yet

- There is no installer and no Unraid template for the server. The template is to be made when the server exists (story E01-011). Until then the bundle folder is copied from the PC by hand, as described below.
- The paths in `.env` are changed by hand on the server.
- The old machine is removed and a new auth key is made by hand in the Tailscale admin console.
- It is not known yet whether the bundle starts again after the server restarts. You check this in step 37.
- Older backups cannot be restored with a single command yet. With the steps below, the latest backup is put back.

## Before you start

1. Check that you have the backup password in your password manager. It is not needed for the steps below, because the secrets folder is copied with the bundle. If the copy goes wrong, the backups cannot be read without it.
2. On the Unraid server, open the terminal with the **Terminal** button (>_) at the top right of Unraid's web page (not checked yet).
3. Type `docker compose version` and press Enter. If the output shows a version number, go on. If it says that `compose` is not a docker command, the Compose plugin has to be added to Unraid first. That is not written up yet, so ask Claude for help.

## On the PC: packing up Franca

4. Right-click the Start button and choose **Terminal (Admin)**. In that window, type these two commands, each followed by Enter, to open the Franca system and go to Franca's folder in it.

   ```
   wsl -d Franca -u root
   cd /opt/franca
   ```

5. Stop the bundle, so that no progress is saved after the last backup:

   ```
   docker compose stop
   ```

6. Take a backup now:

   ```
   docker compose run --rm backup python /app/franca_backup.py backup
   ```

   One of the last lines says `"result": "backed-up"` when it worked. Lines that say `report-not-sent` can be ignored, because the status container is stopped. If there is no `backed-up` line, stop here and copy the output. Then start the bundle again with `docker compose up -d` and ask Claude for help.

7. Put the bundle folder and the backup folder in one file on disk J:.

   ```
   tar --numeric-owner -czf /mnt/j/franca-move.tar.gz -C / opt/franca mnt/j/franca-backups
   ```

   The file also records which user owns each file and folder. The containers run as those users, so the owners have to stay the same. If you chose a disk other than J: when you installed Franca, use its letter in place of `j` here and in step 17.

8. Open **Task Scheduler** on the PC. In **Task Scheduler Library**, right-click the task **Franca** and choose **Disable**. The bundle then does not start again when the PC restarts.

## In the Tailscale admin console: removing the old machine and making a new key

9. Open https://login.tailscale.com/admin and go to the **Machines** page.
10. Click the **…** button beside the machine `franca` and choose **Remove**. While the old machine is there, the name `franca` is taken. The new server would then be called `franca-1`, and the address would change.
11. Make a new auth key with steps 5 to 8 of `docs/private-network.md` (one day, not reusable, not ephemeral, with the tag `tag:franca`). Keep it in your password manager until step 23.

## Copying the file to the server

12. If the `appdata` share is not shared on the network yet, switch it on in Unraid's web page. Open **Shares**, click **appdata**, choose **Yes** for **Export** under **SMB Security Settings** and click **Apply** (not checked yet).
13. In File Explorer on the PC, type `\\` followed by the server's name and `\appdata` in the address bar and press Enter, for example `\\tower\appdata`.
14. Copy `franca-move.tar.gz` from disk J: into that folder.
15. If you switched the export on in step 12, switch it off again. Choose **No** for **Export** and click **Apply** (not checked yet).

## On the server: putting the files in place

Unraid's system runs from memory, so a file is lost when the server restarts unless it is on the flash drive or on one of the server's disks (the array and the pools). The bundle folder and the backup folder go in `/mnt/user/`, which is kept. The backup folder is shown as a new share, `franca-backups`, on Unraid's **Shares** page (not checked yet).

From step 19 on, the commands are typed in the bundle folder. If you close the terminal after step 18, open it again, type `cd /mnt/user/appdata/franca` and press Enter.

16. In the Unraid terminal, unpack the file into a temporary folder:

    ```
    mkdir /mnt/user/appdata/franca-move
    tar --numeric-owner -xzf /mnt/user/appdata/franca-move.tar.gz -C /mnt/user/appdata/franca-move
    ```

17. Move the two folders to their new places:

    ```
    mv /mnt/user/appdata/franca-move/opt/franca /mnt/user/appdata/franca
    mv /mnt/user/appdata/franca-move/mnt/j/franca-backups /mnt/user/franca-backups
    ```

18. Go to the bundle folder:

    ```
    cd /mnt/user/appdata/franca
    ```

19. Change the paths in `.env` to the new places:

    ```
    sed -i 's#/opt/franca#/mnt/user/appdata/franca#g; s#/mnt/j/franca-backups#/mnt/user/franca-backups#' .env
    ```

20. Check the result:

    ```
    grep -E 'BUNDLE_DIR|SECRETS_DIR|BACKUP_DIR' .env
    ```

    There are three lines. `FRANCA_BUNDLE_DIR` is `/mnt/user/appdata/franca`, `FRANCA_SECRETS_DIR` is `/mnt/user/appdata/franca/secrets` and `FRANCA_BACKUP_DIR` is `/mnt/user/franca-backups`.

## On the server: starting Franca and restoring the backup

21. Download Franca's images. The versions are the ones that were running on the PC.

    ```
    docker compose pull
    ```

22. Open the auth key file in the nano editor:

    ```
    nano secrets/tailscale_authkey
    ```

23. Paste the auth key from step 11 with a right-click. If a menu opens, choose **Paste**, or press Ctrl+Shift+V (not checked yet). The key is not typed in a command, so it does not end up in the terminal's history.
24. Save the file and close the editor: press Ctrl+O, then Enter, then Ctrl+X.
25. Start the app on its own. Its data volume and an empty database are made.

    ```
    docker compose up -d --no-build --wait app
    ```

    Do not start the rest of the bundle yet. A backup of the empty database would be made at once, and step 27 would then put back that empty backup.

26. Stop the app:

    ```
    docker compose stop app
    ```

27. Put back the latest backup:

    ```
    docker compose run --rm backup python /app/franca_backup.py restore-latest
    ```

    The last line says `"result": "restored"` when it worked. If it says `refused`, the app is still running. Do step 26 again. If it says anything else, stop, copy the output and ask Claude for help.

28. Start the bundle. With the new key, the server is added to your tailnet.

    ```
    docker compose up -d --no-build --wait
    ```

    This can take a few minutes. The output ends with a line for each container that says `Healthy`.

29. Empty the auth key file, as the installer did on the PC. The key has been used and cannot be used again.

    ```
    : > secrets/tailscale_authkey
    ```

## Checking the move

30. In the Tailscale admin console, open the **Machines** page. There is a machine called `franca` with the tag `tag:franca`. If it is called `franca-1`, the old machine was still there in step 10. Follow "If the address changes" below.
31. On your phone, open Franca at the address you normally use. Sign in if you are asked to, and check that your progress is there.
32. In the Unraid terminal, stop the app with `docker compose stop app`.
33. Check that an alert arrives on your phone within about three minutes.
34. Start the app again with `docker compose up -d app`.
35. Restart the Unraid server with the **Reboot** button on Unraid's **Main** page (not checked yet).
36. After it has started, open Unraid's **Main** page and check that the array is started. If it is not, click **Start** (not checked yet).
37. Open Franca on your phone again. If it does not open, ask Claude for help. The bundle has to be started when the server starts, and the steps for that on Unraid are not written up yet.
38. Open the Unraid terminal again, type `cd /mnt/user/appdata/franca` and press Enter.
39. Type `docker compose exec backup cat /status/backup.json` and press Enter. A backup of the restored database was made soon after step 28, because there was no record of a backup on the server yet. The output has `"result": "backed-up"` when it worked.

## Cleaning up

40. In File Explorer on the PC, delete `franca-move.tar.gz` from disk J:.
41. In the Unraid terminal, delete the copy of the file and the temporary folder. The file and the folder have the secrets in them.

    ```
    rm /mnt/user/appdata/franca-move.tar.gz
    rm -r /mnt/user/appdata/franca-move
    ```

42. Keep the Franca system on the PC and the backups on disk J: for a few weeks, in case something has to be fetched from them.
43. After those weeks, delete the Franca system in the PC's terminal with `wsl --unregister Franca`. This deletes the Franca system and everything in it. The backups on disk J: are not deleted.
44. In **Task Scheduler**, right-click the task **Franca** and choose **Delete**.

## If the address changes

The address changes if the server's machine is not called `franca` in your tailnet, or if the server is in another tailnet.

1. Note the new name from the **Machines** page, for example `franca-1.tail1234.ts.net`.
2. In the Unraid terminal, in `/mnt/user/appdata/franca`, open `.env` in the nano editor with `nano .env`.
3. Change the name in two lines. `FRANCA_TAILSCALE_NAME` has the name, and `FRANCA_PUBLIC_URL` has `https://` followed by the name.
4. Save the file and close the editor: press Ctrl+O, then Enter, then Ctrl+X.
5. Start the bundle again with `docker compose up -d --no-build --wait`.
6. In the Google Cloud console, add the new address to the Franca client, as in step 13 of `docs/installing-franca.md`. Remove the old address when the new one works.
7. Passkeys belong to an address, so the passkeys made for the old address do not work on the new one. Sign in with Google or with a recovery code, and add a passkey again on the Passkeys page.
