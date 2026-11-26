// Making recovery codes and signing in with one, in a real browser against the real server (story E02-002).
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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

test("the owner makes recovery codes and signs in with one", async ({ page, context }) => {
  await context.addCookies([{ name: "franca_session", value: ownerSessionToken(), domain: "localhost", path: "/", httpOnly: true }]);
  await page.goto("/");
  await page.getByRole("link", { name: "Your recovery codes" }).click();
  await page.getByRole("button", { name: "Make new recovery codes" }).click();
  const newCodes = page.getByRole("region", { name: "Your new recovery codes" });
  await expect(newCodes.getByRole("listitem")).toHaveCount(10);
  const codes = await newCodes.getByRole("listitem").allTextContents();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations).toEqual([]);

  await page.request.post("/api/v1/auth/sign-out");
  await context.clearCookies();
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Sign in with a recovery code" }).click();
  await page.getByLabel("E-mail address").fill("owner@example.org");
  await page.getByLabel("Recovery code").fill(codes[0]?.toLowerCase() ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("You are signed in as Nik.")).toBeVisible();
});
