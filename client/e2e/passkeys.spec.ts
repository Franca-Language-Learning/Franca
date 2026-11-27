// Adding a passkey and signing in with it, in a real browser against the real server (story E02-001).
// Chromium's virtual authenticator stands in for the phone or laptop that keeps the passkey.
import { expect, type Page, test } from "@playwright/test";
import { expectNoAccessibilityViolations, signInAsOwner } from "./helpers";

async function addVirtualAuthenticator(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
}

test("the owner adds a passkey and then signs in with it", async ({ page, context }) => {
  await signInAsOwner(context);
  await addVirtualAuthenticator(page);

  await page.goto("/passkeys");
  await page.getByLabel(/Name for the passkey/).fill("Laptop");
  await page.getByRole("button", { name: "Add a passkey" }).click();
  await expect(page.getByText("The passkey was added.")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "Laptop" })).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page.goto("/");
  await page.getByRole("button", { name: "Sign out on this device" }).click();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("You are signed in as Nik.")).toBeVisible();
});
