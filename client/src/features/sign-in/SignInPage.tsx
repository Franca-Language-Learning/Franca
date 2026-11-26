import { PasskeySignIn } from "../passkeys";
/** The sign-in page. A learner signs in with Google, or with a passkey added earlier. Franca stores no password. */

const REFUSALS: Record<string, string> = {
  "not-invited":
    "There is no invitation to Franca for this Google account. Sign in with a different Google account, or ask the person who runs Franca to invite this e-mail address.",
  "email-not-verified":
    "Google has not verified the e-mail address of this account. Verify it with Google, then try again.",
  disabled: "Your account is switched off. Ask the person who runs Franca to switch it on again.",
  failed: "Signing in with Google did not work. Please try again.",
};

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
    </main>
  );
}
