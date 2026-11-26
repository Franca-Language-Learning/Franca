# Installing Franca on your PC

These steps install Franca on your Windows PC (stories E01-011 and E01-012). Franca then runs whenever the PC is on, also when nobody is signed in, and you reach it from your phone and laptop over Tailscale. The installation takes about 45 minutes, most of it waiting.

## Before you start

1. Follow the steps under "Before the installer runs" in `docs/private-network.md`, in the Tailscale admin console. Keep the auth key at hand.
2. Install the ntfy app on your phone, as in step 1 of `docs/health-alerts.md`.
3. Have the client ID and the client secret of your Google sign-in client at hand. They are in the Google Cloud console, under **APIs & Services**, then **Credentials**, then the client called Franca. If the secret is no longer shown there, click **Add secret** and copy the new one.
4. Check that disk J: is connected. The nightly backups are written to it.

## Installing

5. Open the latest release on https://github.com/Franca-Language-Learning/Franca/releases and download `franca-installer.zip`.
6. Right-click the file, choose **Extract All** and click **Extract**.
7. In the folder that opens, double-click `Install-Franca.cmd`. When Windows asks whether the app may make changes, click **Yes**.
8. If the installer says that it has switched on WSL, restart the PC and do step 7 again.
9. Answer the questions. The Google client secret and the Tailscale auth key are not shown as you type; paste them with a right-click. If the backup disk is not J:, type its letter.
10. Wait while Docker is installed and Franca is started. This takes 10 to 20 minutes.
11. When the installer shows the backup password, save it in your password manager. It is shown once, and without it the backups cannot be read.
12. In the ntfy app, tap **+**, type the alert topic that the installer shows, and tap **Subscribe**. Check that the test alert arrives.

## After the installation

13. In the Google Cloud console, open the Franca client again. Under **Authorised JavaScript origins**, add the address that the installer showed, such as `https://franca.tail1234.ts.net`. Under **Authorised redirect URIs**, add the same address followed by `/api/v1/auth/google/callback`. Click **Save**. It can take a few minutes before Google uses the change.
14. Follow the steps under "After the installer has run" in `docs/private-network.md`.
15. On your phone, open the address and sign in with Google.
16. Restart the PC, and do not sign in to Windows. After about three minutes, open the address on your phone again. Franca should open. This shows that Franca starts on its own after a Windows Update restart.

## If something goes wrong

- If the installer stops with a message, fix what it names and run `Install-Franca.cmd` again. Secrets that were made before, such as the backup password, are kept.
- If Franca does not open after a restart, open **Task Scheduler** on the PC and check that the task called Franca is there and running.
