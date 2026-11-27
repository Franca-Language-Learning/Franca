// Making recovery codes and signing in with one, in a real browser against the real server (story E02-002).
import { expect, test } from "@playwright/test";
import { expectNoAccessibilityViolations, signInAsOwner } from "./helpers";

test("the owner makes recovery codes and signs in with one", async ({ page, context }) => {
  await signInAsOwner(context);
  await page.goto("/");
  await page.getByRole("link", { name: "Your recovery codes" }).click();
  await page.getByRole("button", { name: "Make new recovery codes" }).click();
  const newCodes = page.getByRole("region", { name: "Your new recovery codes" });
  await expect(newCodes.getByRole("listitem")).toHaveCount(10);
  const codes = await newCodes.getByRole("listitem").allTextContents();
  await expectNoAccessibilityViolations(page);

  await page.goto("/");
  await page.getByRole("button", { name: "Sign out on this device" }).click();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "sign in with a recovery code" }).click();
  await page.getByLabel("E-mail address").fill("owner@example.org");
  await page.getByLabel("Recovery code").fill(codes[0]?.toLowerCase() ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("You are signed in as Nik.")).toBeVisible();
});
