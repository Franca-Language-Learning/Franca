# Private network: steps in the Tailscale admin console

Franca is reached from phones and laptops over your tailnet, the private network between your devices in Tailscale. You do these steps once, in the Tailscale admin console at https://login.tailscale.com/admin, signed in with the account you made for Franca. They take about ten minutes.

## Before the installer runs

1. Open the **DNS** page. Check that **MagicDNS** is on. If it is off, click **Enable MagicDNS**.
2. On the same page, under **HTTPS Certificates**, click **Enable HTTPS** and confirm. Franca needs this to get a certificate for its Tailscale name.
3. Note the tailnet name at the top of the DNS page. It ends in `.ts.net`, for example `tail1234.ts.net`. Franca's address will be `https://franca.` followed by that name.
4. Open **Settings**, then **Keys**, and click **Generate auth key**.
5. Leave **Reusable** and **Ephemeral** off. Choose an expiry of one day. That is enough, because the key is used once, when the installer runs.
6. Click **Generate key** and copy the key. It starts with `tskey-auth-`. Keep it in your password manager until the installer asks for it. Do not send it by e-mail or chat.

## After the installer has run

7. Open the **Machines** page. There is now a machine called `franca`.
8. Click the three dots at the end of its row and choose **Disable key expiry**. Without this, Franca is cut off from the tailnet after six months, and a new key is needed.
9. On your phone, with the Tailscale app connected, open `https://franca.` followed by your tailnet name. You should see Franca's start page, with a padlock in the address bar.

## Who can reach Franca, and rejoining

- Franca cannot be reached from the internet. A device has to be in your tailnet, signed in with your Tailscale account, to open it.
- The name `franca.` plus your tailnet name is published in the public logs of HTTPS certificates. Anyone can see that a device of that name exists. Knowing the name is not enough to get in.
- If the PC has to join again, for example after a reinstall, make a new key with steps 4 to 6, run the installer again and paste the key when it asks.
