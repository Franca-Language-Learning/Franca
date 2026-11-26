/** The sign-in page. Signing in happens at Google; Franca stores no password. */

const REFUSALS: Record<string, string> = {
  "not-invited":
    "This Google account has no invitation to Franca. Ask the owner to invite the e-mail address of the account you used.",
  "email-not-verified":
    "Google has not verified the e-mail address of this account. Verify it with Google, then try again.",
  disabled: "This account is switched off. Ask the owner to switch it on again.",
  failed: "Signing in with Google did not work. Please try again.",
};

export function SignInPage({ error }: { error?: string }) {
  const refusal = error ? REFUSALS[error] : undefined;
  return (
    <main>
      <h1>Sign in to Franca</h1>
      {refusal && <p role="alert">{refusal}</p>}
      <p>You sign in with your Google account. Franca does not keep a password for you.</p>
      {/* A full page load, because the browser goes on to Google and back. */}
      <a href="/api/v1/auth/google/start">Sign in with Google</a>
    </main>
  );
}
