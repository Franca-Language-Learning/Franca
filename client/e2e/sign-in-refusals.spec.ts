// The messages for a refused sign-in, in a real browser against the real server (stories E02-001 and E02-002).
// There is no Google in the browser tests, so the sign-in page for each refusal from Google sign-in is opened at the
// address the server sends the browser to: /sign-in?error=<reason>. The reasons are the ones in
// server/src/franca/api/auth.py.
import { expect, test } from "@playwright/test";
import { expectNoAccessibilityViolations } from "./helpers";

const GOOGLE_REFUSALS = [
  { reason: "not-invited", message: /^There is no invitation to Franca for this Google account\./ },
  { reason: "email-not-verified", message: /^Google has not verified the e-mail address of this account\./ },
  { reason: "disabled", message: /^Your account is switched off\./ },
  { reason: "failed", message: /^Signing in with Google did not work\./ },
];

for (const { reason, message } of GOOGLE_REFUSALS) {
  test(`the sign-in page says why a Google sign-in was refused with "${reason}"`, async ({ page }) => {
    await page.goto(`/sign-in?error=${reason}`);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in to Franca" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveText(message);
    await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });
}

test("the sign-in page shows no message for an unknown reason in the address", async ({ page }) => {
  await page.goto("/sign-in?error=something-else");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to Franca" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("the recovery-code form shows a message when the server does not accept the code", async ({ page }) => {
  await page.goto("/sign-in/recovery-code");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in with a recovery code" })).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page.getByLabel("E-mail address").fill(`stranger-${Date.now()}@example.org`);
  await page.getByLabel("Recovery code").fill("ABCDE-FGHJK");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "The e-mail address or the code is not right, or the code has been used already. Check both and try again.",
  );
  await expect(page).toHaveURL("/sign-in/recovery-code");
  await expectNoAccessibilityViolations(page);
});
