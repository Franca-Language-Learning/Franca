// The devices page, in a real browser against the real server (story E02-003): signing out one other device, and
// signing out all other devices. Each device is a separate browser context with its own session cookie.
import { randomUUID } from "node:crypto";
import { type Browser, expect, type Page, test } from "@playwright/test";
import { expectNoAccessibilityViolations, signInAsLearner } from "./helpers";

const COMPUTER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0";
const PHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const TABLET =
  "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

/** A learner of their own for each test, so that sessions from other tests, or from an earlier try of this test, are
 * not on the list. */
function newLearner() {
  return { email: `devices-${randomUUID()}@example.org`, name: "Sam" };
}

/** Opens a page in a new browser context, signed in as the learner on another device. */
async function otherDevice(browser: Browser, learner: { email: string; name: string }, userAgent: string): Promise<Page> {
  const context = await browser.newContext();
  await signInAsLearner(context, { ...learner, userAgent });
  return context.newPage();
}

async function expectSignedOut(page: Page) {
  await page.goto("/devices");
  await expect(page.getByText("You are not signed in.")).toBeVisible();
}

test("the learner signs out on one other device", async ({ page, context, browser }) => {
  const learner = newLearner();
  await signInAsLearner(context, { ...learner, userAgent: COMPUTER });
  const phone = await otherDevice(browser, learner, PHONE);

  await page.goto("/");
  await page.getByRole("link", { name: "Your devices" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your devices" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Computer: Firefox on Windows (this device)", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Phone: Safari on iPhone", exact: true })).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page.getByRole("button", { name: "Sign out on Phone: Safari on iPhone" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Phone: Safari on iPhone", exact: true })).toHaveCount(0);
  await expect(page.getByRole("listitem")).toHaveCount(1);
  await expectSignedOut(phone);
});

test("the learner signs out on all other devices", async ({ page, context, browser }) => {
  const learner = newLearner();
  await signInAsLearner(context, { ...learner, userAgent: COMPUTER });
  const phone = await otherDevice(browser, learner, PHONE);
  const tablet = await otherDevice(browser, learner, TABLET);

  await page.goto("/devices");
  await expect(page.getByRole("listitem")).toHaveCount(3);
  await page.getByRole("button", { name: "Sign out on all other devices…" }).click();
  await expect(page.getByText("You will need to sign in again on the 2 other devices.")).toBeVisible();
  await expectNoAccessibilityViolations(page);

  await page.getByRole("button", { name: "Sign out on all other devices", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("You are now signed out on all other devices.");
  await expect(page.getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 2, name: "Computer: Firefox on Windows (this device)", exact: true })).toBeVisible();
  await expectNoAccessibilityViolations(page);
  await expectSignedOut(phone);
  await expectSignedOut(tablet);
});
