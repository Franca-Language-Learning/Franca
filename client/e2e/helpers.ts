// Helpers for the browser tests: the accessibility check, and a signed-in owner without Google.
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import { type BrowserContext, expect, type Page } from "@playwright/test";

/** The WCAG 2.2 AA rules, and the rules of the earlier versions that it includes. */
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

export async function expectNoAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(results.violations).toEqual([]);
}

/** Writes a session for the owner to the test database and returns its token. There is no Google sign-in in the browser
 * tests. */
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

/** Signs the owner in: a session is written to the test database, and the browser gets its cookie. */
export async function signInAsOwner(context: BrowserContext) {
  await context.addCookies([{ name: "franca_session", value: ownerSessionToken(), domain: "localhost", path: "/", httpOnly: true }]);
}
