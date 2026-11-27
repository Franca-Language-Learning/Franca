# Health alerts on your phone

Franca is checked every minute, and again after the nightly update and backup (story E01-010). When something fails, a message is sent to your phone through ntfy, a free notification app. A second message is sent when the problem is over.

These checks run on the PC, so there is no alert from them when the PC itself is off. For that, a short signal, a heartbeat, is sent from the PC to a free service called healthchecks.io every five minutes. When the heartbeats stop, you get a message from healthchecks.io through ntfy (story E01-012). The heartbeat is optional. You make the account and the check before the installer runs, and connect the check to ntfy after it has run.

## Before the installer runs

1. On your phone, install the **ntfy** app from the App Store or Google Play. You do not need an account.
2. On a computer, open https://healthchecks.io.
3. Click **Sign Up**. The free plan is enough.
4. Type your e-mail address.
5. Click the button below the address. A sign-in link is sent to you by e-mail.
6. In the e-mail from healthchecks.io, click the link.
7. In your project, click **Add Check**. A new check is added to the list.
8. Click the new check's name.
9. Type `Franca` as the name.
10. Click **Save**.
11. On the check's page, click **Change Schedule**.
12. Choose a **Period** of 5 minutes.
13. Choose a **Grace Time** of 10 minutes.
14. Click **Save**. With these values, a message is sent when no heartbeat has arrived for about 15 minutes.
15. Copy the ping address from the check's page into your password manager. It is `https://hc-ping.com/` followed by a long id, such as `https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b`. It is a secret: anyone who has it can send heartbeats for your check, which would hide that the PC is off. Do not send it by e-mail or chat.

## During installation

16. When the installer asks for the healthchecks.io ping address, paste it with a right-click. It is not shown as you type. If you do not want the heartbeat, press Enter.
17. Copy the topic name that the installer shows into your password manager. It is long and random, such as `franca-k3v9x2m8q1w7`. Anyone who knows the topic name can read the alerts.
18. In the ntfy app, tap **+** (Subscribe to topic).
19. Type the topic name exactly as shown. Leave the server as `ntfy.sh`.
20. Tap **Subscribe**.
21. Check that the installer's test message arrives on your phone.

## After the installer has run

22. On healthchecks.io, open **Integrations** at the top of the page.
23. Click **Add Integration** beside **ntfy**.
24. As the topic, type the topic name from step 17. Leave the server as `https://ntfy.sh`.
25. Click **Save Integration**.
26. On the **Integrations** page, check that the Franca check is switched on for the ntfy integration.
27. Click **Test!** beside the ntfy integration.
28. Check that the test message arrives on your phone.
29. After about ten minutes, open the Franca check on healthchecks.io. Its status should be **up**, with the time of the last heartbeat. If it still says **new**, check that the PC is on and connected to the internet, and that the ping address in your password manager is the one on the check's page.

## Changing the ping address later

30. On the PC, double-click `Install-Franca.cmd` again, as in step 7 of `docs/installing-franca.md`.
31. Answer the questions as before. At the question about the Tailscale auth key, press Enter. The PC is in your tailnet already, so no new key is needed. If the installer says "Franca could not sign in to your tailnet with the saved Tailscale state", make a new auth key with steps 5 to 8 of `docs/private-network.md` and run the installer again with that key.
32. At the question about the healthchecks.io ping address, paste the new address. To switch the heartbeat off, type `off`. If you press Enter, the saved address is kept.

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
| Nightly/Restore test | The monthly restore test failed or is overdue. In the test, the latest backup is restored and checked, and Franca is started on the restored copy. Ask for help soon. Until this is fixed, a restore from backup may not work. |
| Franca is DOWN (from healthchecks.io) | No heartbeat has arrived for about 15 minutes. The PC is off or asleep. It can also mean that Docker has stopped or that the PC has no internet connection. Check that the PC is on and connected. A message that says **UP** follows when the heartbeats arrive again. |

## Looking at the dashboard

33. On the PC, open http://127.0.0.1:8081 in a browser. It lists each check with its recent results. The dashboard cannot be opened from other devices.

## When the PC is off

If the PC is switched off, no alert can be sent from the PC. The same is true when Docker has stopped or the PC has no internet connection. The heartbeats to healthchecks.io stop too, and after about 15 minutes you get the "Franca is DOWN" message from healthchecks.io through ntfy. If you pressed Enter at step 16 and no address was saved before, there is no heartbeat and no such message.
