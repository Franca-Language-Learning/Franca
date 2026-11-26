// Adding a passkey and signing in with it, in a real browser against the real server (story E02-001).
// Chromium's virtual authenticator stands in for the phone or laptop that keeps the passkey.
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/** Signs the owner in by writing a session to the test database, because the browser tests have no Google. */
function ownerSessionToken(): string {
  const code = [
    "from franca import identity",
    "from franca.platform import load_settings, make_engine, utc_now",
    "engine = make_engine(load_settings().database_path)",
    "with engine.begin() as c:",
    "    owner = identity.sign_in_with_google(c, subject='e2e-owner', email='owner@example.org', email_verified=True, name='Nik', owner_email='owner@example.org', now=utc_now())",
    "    print(identity.start_session(c, owner, 'playwright', utc_now()))",
  ].join("\n");
  return execFileSync("uv", ["run", "python", "-c", code], {
    cwd: "../server",
    env: { ...process.env, PYTHONPATH: "src", FRANCA_DATABASE_PATH: "e2e.db" },
    encoding: "utf-8",
  }).trim();
}

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
  await context.addCookies([{ name: "franca_session", value: ownerSessionToken(), domain: "localhost", path: "/", httpOnly: true }]);
  await addVirtualAuthenticator(page);

  await page.goto("/passkeys");
  await page.getByLabel(/Name for the passkey/).fill("Laptop");
  await page.getByRole("button", { name: "Add a passkey" }).click();
  await expect(page.getByText("The passkey was added.")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "Laptop" })).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations).toEqual([]);

  await page.goto("/");
  await page.getByRole("button", { name: "Sign out on this device" }).click();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("You are signed in as Nik.")).toBeVisible();
});
