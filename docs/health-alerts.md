# Health alerts on your phone

Franca is checked every minute, and again after the nightly update and backup (story E01-010). When something fails, a message is sent to your phone through ntfy, a free notification app. A second message is sent when the problem is over.

## Before the installer runs

1. On your phone, install the **ntfy** app from the App Store or Google Play. You do not need an account.

## During installation

2. A long, random topic name, such as `franca-k3v9x2m8q1w7`, is made and shown on screen. Keep a copy in your password manager. Anyone who knows the topic name can read the alerts.
3. In the ntfy app, tap **+** (Subscribe to topic), type the topic name exactly as shown and tap **Subscribe**. Leave the server as `ntfy.sh`.
4. A test message is sent. Check that it arrives on your phone.

## What the alerts mean

| Alert | What to do |
|---|---|
| Franca/App | The app does not answer. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/Web server | The web server does not answer. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/HTTPS on the Tailscale name | Franca cannot be opened over HTTPS, or its certificate is about to expire. Check that HTTPS certificates are still switched on in the Tailscale admin console (see `docs/private-network.md`). |
| Franca/Tailscale | The tailscale container has stopped or is not signed in to your tailnet. Restart the PC. If the alert comes back, check the `franca` machine in the Tailscale admin console. |
| Nightly/Update | The nightly update failed, has not succeeded for a day, or the updater has stopped. The version that was running is kept. |
| Nightly/Backup | The nightly backup failed, has not succeeded for a day, or the backup has stopped. Check that disk J: is connected. |
| Nightly/Restore test | The monthly restore test failed or is overdue. Ask for help soon. Until this is fixed, a restore from backup may not work. |

## Looking at the dashboard

5. On the PC, open http://127.0.0.1:8081 in a browser. It lists each check with its recent results. The dashboard cannot be opened from other devices.

## When no alert can be sent

6. If the PC is switched off or Docker has stopped, no alert can be sent from the PC. An outside check for that is planned with the story that keeps Franca running on the PC around the clock (E01-012).
