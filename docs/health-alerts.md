# Health alerts on your phone

Franca checks itself every minute and after each night's update and backup (story E01-010). When something fails, a message is sent to your phone through ntfy, a free notification app. A second message is sent when the problem is over.

## Before the installer runs

1. On your phone, install the **ntfy** app from the App Store or Google Play. You do not need an account.

## When the installer asks

2. The installer makes a long, random topic name, such as `franca-k3v9x2m8q1w7`, and shows it to you. Keep a copy in your password manager. Anyone who knows the topic name can read the alerts.
3. In the ntfy app, tap **+** (Subscribe to topic), type the topic name exactly as shown and tap **Subscribe**. Leave the server as `ntfy.sh`.
4. The installer sends a test message. Check that it arrives on your phone.

## What the alerts mean

| Alert | What to do |
|---|---|
| Franca/App | The app does not answer. If a second message saying it is resolved does not follow within a few minutes, restart the PC. |
| Franca/Web server | The web server does not answer. Restart the PC if it does not resolve itself. |
| Franca/HTTPS on the Tailscale name | Franca cannot be opened over HTTPS, or its certificate is about to expire. Check that HTTPS certificates are still on in the Tailscale admin console (see `docs/private-network.md`). |
| Franca/Tailscale | The PC is not connected to your tailnet. Check that the PC has internet access. |
| Nightly/Update | The nightly update failed or did not run. The version that was running is kept. |
| Nightly/Backup | The nightly backup failed or did not run. Check that disk J: is connected. |
| Nightly/Restore test | The monthly restore test failed. Ask for help before the next backup is needed. |

## Looking at the dashboard

5. On the PC, open http://127.0.0.1:8081 in a browser. It lists each check with its recent results. The dashboard cannot be opened from other devices.
