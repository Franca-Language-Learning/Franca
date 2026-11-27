import { Link } from "@tanstack/react-router";
import { ACCOUNT_SWITCHED_OFF } from "../../account/messages";
import { PasskeySignIn } from "../passkeys";

const REFUSALS: Record<string, string> = {
  "not-invited":
    "There is no invitation to Franca for this Google account. Sign in with a different Google account, or ask the person who runs Franca to invite this e-mail address.",
  "email-not-verified":
    "Google has not verified the e-mail address of this account. Verify it with Google, then try again.",
  disabled: ACCOUNT_SWITCHED_OFF,
  failed: "Signing in with Google did not work. Please try again.",
};

/** The sign-in page. A learner signs in with Google, or with a passkey added earlier. Franca stores no password. error
 * is the reason a sign-in with Google was refused. It is read from the address /sign-in?error=..., where the browser is
 * sent back by the server. */
export function SignInPage({ error }: { error?: string }) {
  const refusal = error ? REFUSALS[error] : undefined;
  return (
    <main>
      <h1>Sign in to Franca</h1>
      {refusal && <p role="alert">{refusal}</p>}
      <p>You sign in with your Google account, or with a passkey if you have added one. You do not need a Franca password.</p>
      {/* A full page load, because the browser goes on to Google and back. */}
      <p>
        <a href="/api/v1/auth/google/start">Sign in with Google</a>
      </p>
      <PasskeySignIn />
      <p>
        If you lose your phone or cannot use your Google account, you can{" "}
        <Link to="/sign-in/recovery-code">sign in with a recovery code</Link>.
      </p>
    </main>
  );
}
