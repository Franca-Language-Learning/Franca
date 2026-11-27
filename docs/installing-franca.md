# Installing Franca on your PC

These steps install Franca on your Windows PC (stories E01-011 and E01-012). Franca then runs whenever the PC is on, even when nobody is signed in, and you reach it from your phone and laptop over Tailscale. The installation takes about 45 minutes, most of it waiting.

## Before you start

1. In the Tailscale admin console, follow the steps under "Before the installer runs" in `docs/private-network.md`. Keep the auth key at hand.
2. Install the ntfy app on your phone, and make the check on healthchecks.io, as described in steps 1 to 15 of `docs/health-alerts.md`. The check is optional. It is used to send you a message when the PC is off. Keep its ping address at hand.
3. Have the client ID and the client secret of your Google sign-in client at hand. They are in the Google Cloud console, under **APIs & Services**, then **Credentials**, then the client called Franca. If the secret is no longer shown there, click **Add secret** and copy the new one.
4. Check that disk J: is connected and formatted as NTFS. To check, right-click the disk in File Explorer and choose **Properties**. The file system is shown on the **General** tab. The nightly backups are written to this disk.

## Installing

5. Open the latest release on https://github.com/Franca-Language-Learning/Franca/releases and download `franca-installer.zip`.
6. Right-click the file, choose **Extract All** and click **Extract**.
7. In the folder that opens, double-click `Install-Franca.cmd`. If a message about allowing the app to make changes appears, click **Yes**.
8. If the message "Switching on WSL" appears, restart the PC and do step 7 again.
9. Answer the questions. The Google client secret, the Tailscale auth key and the healthchecks.io ping address are not shown as you type. Paste them with a right-click. For the backup disk, press Enter to keep disk J:, or type another letter. If you did not make a check on healthchecks.io, press Enter at the last question.
10. Wait while Docker is installed and Franca is started. This takes 10 to 20 minutes.
11. When the installer shows the backup password, save it in your password manager. It is shown once, and without it the backups cannot be read.
12. In the ntfy app, tap **+**, type the alert topic that the installer shows, and tap **Subscribe**. Check that the test alert arrives.

## After the installation

13. In the Google Cloud console, open the Franca client again. Under **Authorised JavaScript origins**, add the address that the installer showed, such as `https://franca.tail1234.ts.net`. Under **Authorised redirect URIs**, add the same address followed by `/api/v1/auth/google/callback`. Click **Save**. It can take a few minutes before Google uses the change.
14. Follow the steps under "After the installer has run" in `docs/private-network.md`, and the steps under "After the installer has run" in `docs/health-alerts.md` if you made a check on healthchecks.io.
15. On your phone, open the address and sign in with Google.
16. Restart the PC, and do not sign in to Windows. After about three minutes, open the address on your phone again. If it opens, Franca will also start on its own after Windows Update restarts the PC.

## If something goes wrong

- If the installer stops with a message, fix the problem it describes and run `Install-Franca.cmd` again. Passwords and keys from the earlier run, such as the backup password, are kept.
- If Franca does not open after a restart, open **Task Scheduler** on the PC and check that the task **Franca** is listed with the status **Running**.
