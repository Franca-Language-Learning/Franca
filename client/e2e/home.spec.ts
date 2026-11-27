import { expect, type Page, test } from "@playwright/test";
import { expectNoAccessibilityViolations } from "./helpers";

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the home page shows that the real server is running", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Franca" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(/^The Franca server is running \(version .+\)\.$/);
  await expectNoAccessibilityViolations(page);
});

test("an unknown address gets a page-not-found message with a working link home", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expectNoAccessibilityViolations(page);
  await page.getByRole("link", { name: "Go to the home page" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1, name: "Franca" })).toBeVisible();
});

test("someone who is not signed in can go to the sign-in page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/sign-in");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to Franca" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toHaveAttribute("href", "/api/v1/auth/google/start");
  await expectNoAccessibilityViolations(page);
});

for (const width of [320, 768, 1440, 2560]) {
  test(`the home page has no horizontal scroll at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("status")).toHaveText(/server is running/);
    await expectNoHorizontalScroll(page);
  });
}
