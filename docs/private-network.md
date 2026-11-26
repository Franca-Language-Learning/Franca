# Private network: steps in the Tailscale admin console

Franca is reached from phones and laptops over your tailnet, the private network between your devices in Tailscale. You do these steps once, in the Tailscale admin console at https://login.tailscale.com/admin, signed in with the account you made for Franca. They take about fifteen minutes.

## Before the installer runs

1. Open the **DNS** page. Check that **MagicDNS** is on. If it is off, click **Enable MagicDNS**.
2. On the same page, under **HTTPS Certificates**, click **Enable HTTPS** and confirm. Franca needs this to get a certificate for its Tailscale name.
3. Note the tailnet name at the top of the DNS page. It ends in `.ts.net`, for example `tail1234.ts.net`. Franca's address will be `https://franca.` followed by that name.
4. Open the **Access controls** page and choose the JSON editor. Replace all of the text with the policy below and click **Save**.

   ```json
   {
     // Franca (docs/private-network.md in the Franca repository).
     "tagOwners": {
       "tag:franca": ["autogroup:admin"]
     },
     "grants": [
       // Each person's own devices can reach each other.
       {"src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["*"]},
       // Everyone in the tailnet can reach Franca's HTTPS port, and nothing else on the PC.
       {"src": ["autogroup:member"], "dst": ["tag:franca"], "ip": ["tcp:443"]}
     ],
     "ssh": [
       {"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}
     ]
   }
   ```

   There is no rule that starts from `tag:franca`, so Franca cannot open a connection to any of your devices.
5. Open **Settings**, then **Keys**, and click **Generate auth key**.
6. Leave **Reusable** and **Ephemeral** off. Choose an expiry of one day. That is enough, because the key is used once, when the installer runs.
7. Switch **Tags** on and choose `tag:franca`.
8. Click **Generate key** and copy the key. It starts with `tskey-auth-`. Keep it in your password manager until the installer asks for it. Do not send it by e-mail or chat.

## After the installer has run

9. Open the **Machines** page. There is now a machine called `franca` with the tag `tag:franca`. A tagged machine does not expire, so it stays in the tailnet without a new key.
10. On your phone, with the Tailscale app connected, open `https://franca.` followed by your tailnet name. You should see Franca's start page, with a padlock in the address bar.

## Who can reach Franca, and rejoining

- Franca cannot be reached from the internet. A device has to be in your tailnet, signed in with a Tailscale account in it, to open it.
- When another learner joins your tailnet, their devices can reach Franca and each other, and not yours.
- The name `franca.` plus your tailnet name is published in the public logs of HTTPS certificates. Anyone can see that a device of that name exists. Knowing the name is not enough to get in.
- If the PC has to join again, for example after a reinstall, make a new key with steps 5 to 8, run the installer again and paste the key when it asks.
