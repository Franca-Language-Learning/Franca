import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function expectNoAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations).toEqual([]);
}

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

test("an unknown address shows a page-not-found message with a working link home", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expectNoAccessibilityViolations(page);
  await page.getByRole("link", { name: "Go to the home page" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1, name: "Franca" })).toBeVisible();
});

for (const width of [320, 768, 1440, 2560]) {
  test(`nothing is wider than the window at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("status")).toHaveText(/server is running/);
    await expectNoHorizontalScroll(page);
  });
}
