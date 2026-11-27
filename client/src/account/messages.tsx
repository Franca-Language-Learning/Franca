// Sign-in messages that are used on several pages. The text is the same on each page, apart from the page's name and
// what the learner was doing.
import { Link } from "@tanstack/react-router";

export const ACCOUNT_SWITCHED_OFF = "Your account is switched off. Ask the person who runs Franca to switch it on again.";

/** The page for someone who is not signed in: the page's heading and a link to the sign-in page. pageName is the
 * name of the link to this page on the home page. */
export function NotSignedIn({ title, pageName }: { title: string; pageName: string }) {
  return (
    <main>
      <h1>{title}</h1>
      <p>
        You are not signed in. <Link to="/sign-in">Sign in</Link> first, then open “{pageName}” on the home page.
      </p>
    </main>
  );
}

/** The alert for a step that needs a sign-in in the last 15 minutes, such as adding a passkey. action is the end of
 * the sentence "before you can ...". */
export function SignInAgain({ action, pageName }: { action: string; pageName: string }) {
  return (
    <p role="alert">
      You signed in more than 15 minutes ago, so you need to sign in again before you can {action}.{" "}
      <Link to="/sign-in">Sign in again</Link>, then open “{pageName}” on the home page.
    </p>
  );
}
