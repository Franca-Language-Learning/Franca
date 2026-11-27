# Health alerts on your phone

Franca is checked every minute, and again after the nightly update and backup (story E01-010). When something fails, a message is sent to your phone through ntfy, a free notification app. A second message is sent when the problem is over.

These checks run on the PC, so there is no alert from them when the PC itself is off. For that, a short signal, a heartbeat, is sent from the PC to a free service called healthchecks.io every five minutes. When the heartbeats stop, you get a message from healthchecks.io through ntfy (story E01-012). The heartbeat is optional. You make the account and the check before the installer runs, and connect the check to ntfy after it has run.

## Before the installer runs

1. On your phone, install the **ntfy** app from the App Store or Google Play. You do not need an account.
2. On a computer, open https://healthchecks.io and click **Sign Up**. Type your e-mail address and click the button to get a sign-in link. Open the e-mail from healthchecks.io and click the link. The free plan is enough.
3. In your project, click **Add Check**. A new check is added to the list.
4. Click the check's name and type `Franca` as its name. Click **Save**.
5. On the check's page, click **Change Schedule**. Choose a **Period** of 5 minutes and a **Grace Time** of 10 minutes, and click **Save**. With these values, a message is sent when no heartbeat has arrived for about 15 minutes.
6. On the check's page, there is a ping address: `https://hc-ping.com/` followed by a long id, such as `https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b`. Copy it into your password manager. It is a secret: anyone who has it can send heartbeats for your check, which would hide that the PC is off. Do not send it by e-mail or chat.

## During installation

7. When the installer asks for the healthchecks.io ping address, paste it with a right-click. It is not shown as you type. If you do not want the heartbeat, press Enter.
8. A long, random topic name, such as `franca-k3v9x2m8q1w7`, is made and shown on screen. Keep a copy in your password manager. Anyone who knows the topic name can read the alerts.
9. In the ntfy app, tap **+** (Subscribe to topic), type the topic name exactly as shown and tap **Subscribe**. Leave the server as `ntfy.sh`.
10. A test message is sent. Check that it arrives on your phone.

## After the installer has run

11. On healthchecks.io, open **Integrations** at the top of the page. Find **ntfy** in the list and click **Add Integration**.
12. As the topic, type the same topic name as in step 9. Leave the server as `https://ntfy.sh`. Click **Save Integration**.
13. On the **Integrations** page, check that the Franca check is switched on for the ntfy integration. Click **Test!** beside it and check that the test message arrives on your phone.
14. After about ten minutes, open the Franca check on healthchecks.io. Its status should be **up**, with the time of the last heartbeat. If it still says **new**, check that you pasted the whole ping address in step 7. To change the address, run the installer again and paste it when it asks.

## What the alerts mean

| Alert | What to do |
|---|---|
| Franca/App | The app does not answer. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/Web server | The web server does not answer. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/Sign-in page | The sign-in page cannot be opened. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/Signed-in API | The part of Franca behind the sign-in does not answer as it should. Wait a few minutes. If no "resolved" message follows, restart the PC. |
| Franca/Socket proxy | The updater cannot reach Docker, so the nightly update cannot run. Restart the PC. If the alert comes back, run the installer again. If it still comes back, ask for help. |
| Franca/HTTPS on the Tailscale name | Franca cannot be opened over HTTPS, or its certificate is about to expire. Check that HTTPS certificates are still switched on in the Tailscale admin console (see `docs/private-network.md`). |
| Franca/Tailscale | The tailscale container has stopped or is not signed in to your tailnet. Restart the PC. If the alert comes back, check the `franca` machine in the Tailscale admin console. |
| Nightly/Update | The nightly update failed, has not succeeded for a day, or the updater has stopped. The version that was running is kept. |
| Nightly/Backup | The nightly backup failed, has not succeeded for a day, or the backup has stopped. Check that disk J: is connected. |
| Nightly/Restore test | The monthly restore test failed or is overdue. Ask for help soon. Until this is fixed, a restore from backup may not work. |
| Franca is DOWN (from healthchecks.io) | No heartbeat has arrived for about 15 minutes. The PC is off or asleep, Docker has stopped, or the PC has no internet connection. Check that the PC is on and connected. A message that says **UP** follows when the heartbeats arrive again. |

## Looking at the dashboard

15. On the PC, open http://127.0.0.1:8081 in a browser. It lists each check with its recent results. The dashboard cannot be opened from other devices.

## When the PC is off

16. If the PC is switched off, has no internet connection, or Docker has stopped, no alert can be sent from the PC. The heartbeats to healthchecks.io stop too, and after about 15 minutes you get the "Franca is DOWN" message from healthchecks.io through ntfy. If you pressed Enter at step 7, there is no heartbeat and no such message.
