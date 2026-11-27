// Helpers for the browser tests: the accessibility check, and signed-in learners without Google.
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import { type BrowserContext, expect, type Page } from "@playwright/test";

/** The WCAG 2.2 AA rules, and the rules of the earlier versions that it includes. */
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

export async function expectNoAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(results.violations).toEqual([]);
}

/** Who a session in the test database is for, and the User-Agent stored with it. The devices page names a device by
 * this User-Agent, not by the browser the test runs in. */
interface SessionFor {
  email: string;
  name: string;
  userAgent: string;
}

const OWNER: SessionFor = { email: "owner@example.org", name: "Nik", userAgent: "playwright" };

/** Writes a session to the test database and returns its token. There is no Google sign-in in the browser tests, so
 * the server's sign-in function is called with what Google would have sent. A learner who has not been invited yet is
 * invited by the owner and then signed in. The e-mail address is used as the Google subject id, so a second call for
 * the same address gives a second session for the same learner. Browser tests in other files run at the same moment.
 * When two of them sign the owner in for the first time together, one gets an IntegrityError, and its sign-in is tried
 * again (three tries in all). */
function sessionToken(learner: SessionFor): string {
  const code = [
    "import json, sys",
    "from sqlalchemy.exc import IntegrityError",
    "from franca import identity",
    "from franca.platform import load_settings, make_engine, utc_now",
    "learner = json.loads(sys.argv[1])",
    "owner_email = 'owner@example.org'",
    "engine = make_engine(load_settings().database_path)",
    "def google(c, email, name):",
    "    subject = 'e2e-owner' if email == owner_email else email",
    "    return identity.sign_in_with_google(c, subject=subject, email=email, email_verified=True, name=name, owner_email=owner_email, now=utc_now())",
    "for attempt in range(3):",
    "    try:",
    "        with engine.begin() as c:",
    "            owner = google(c, owner_email, 'Nik')",
    "            try:",
    "                signed_in = google(c, learner['email'], learner['name'])",
    "            except identity.SignInRefused:",
    "                identity.invite(c, owner, learner['email'], utc_now())",
    "                signed_in = google(c, learner['email'], learner['name'])",
    "            print(identity.start_session(c, signed_in, learner['userAgent'], utc_now()))",
    "        break",
    "    except IntegrityError:",
    "        if attempt == 2:",
    "            raise",
  ].join("\n");
  return execFileSync("uv", ["run", "python", "-c", code, JSON.stringify(learner)], {
    cwd: "../server",
    env: { ...process.env, PYTHONPATH: "src", FRANCA_DATABASE_PATH: "e2e.db" },
    encoding: "utf-8",
  }).trim();
}

async function addSessionCookie(context: BrowserContext, token: string) {
  await context.addCookies([{ name: "franca_session", value: token, domain: "localhost", path: "/", httpOnly: true }]);
}

/** Signs the owner in: a session is written to the test database, and the browser gets its cookie. */
export async function signInAsOwner(context: BrowserContext) {
  await addSessionCookie(context, sessionToken(OWNER));
}

/** Signs a learner in on one device, after an invitation from the owner if there is none yet: a session is written to
 * the test database, and the browser gets its cookie. Call it once for each device, with the same address and a different User-Agent. */
export async function signInAsLearner(context: BrowserContext, learner: SessionFor) {
  await addSessionCookie(context, sessionToken(learner));
}
