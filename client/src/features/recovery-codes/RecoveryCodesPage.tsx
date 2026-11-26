import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError, getRecoveryCodeStatus, makeRecoveryCodes } from "../../api/client";

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

function NewCodes({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState<boolean | null>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section aria-labelledby="new-codes">
      <h2 id="new-codes">Your new recovery codes</h2>
      <p>
        Write these codes down or keep them in your password manager now. They are shown this once. Each code can be used
        once.
      </p>
      <ol className="recovery-codes">
        {codes.map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ol>
      <Button onPress={copy}>Copy the codes</Button>
      {copied === true && <p role="status">The codes were copied.</p>}
      {copied === false && <p role="alert">The codes could not be copied. Write them down instead.</p>}
    </section>
  );
}

/** The learner's recovery codes: how many are left, and a way to make new ones. */
export function RecoveryCodesPage() {
  const queryClient = useQueryClient();
  const codeStatus = useQuery({ queryKey: ["recovery-codes"], queryFn: ({ signal }) => getRecoveryCodeStatus(signal) });
  const [confirming, setConfirming] = useState(false);
  const make = useMutation({
    mutationFn: makeRecoveryCodes,
    onSuccess: () => {
      setConfirming(false);
      return queryClient.invalidateQueries({ queryKey: ["recovery-codes"] });
    },
  });

  if (codeStatus.error instanceof ApiError && codeStatus.error.status === 401) {
    return (
      <main>
        <h1>Recovery codes</h1>
        <p>
          You are not signed in. <Link to="/sign-in">Sign in</Link> first, then come back to this page.
        </p>
      </main>
    );
  }

  const hasCodes = (codeStatus.data?.unused ?? 0) > 0;
  return (
    <main>
      <h1>Recovery codes</h1>
      <p>
        If you lose the phone with your passkey or cannot use your Google account, you can sign in with your e-mail address
        and one of these codes. Each code works once.
      </p>
      {codeStatus.isPending && <p role="status">Loading…</p>}
      {codeStatus.isError && <p role="alert">Your recovery codes could not be loaded. Reload this page to try again.</p>}
      {codeStatus.data &&
        (codeStatus.data.createdAt ? (
          <p>
            You have {codeStatus.data.unused} unused {codeStatus.data.unused === 1 ? "code" : "codes"}. They were made on{" "}
            {DATE.format(new Date(codeStatus.data.createdAt))}.
          </p>
        ) : (
          <p>You have no recovery codes yet.</p>
        ))}

      {make.data ? (
        <NewCodes codes={make.data} />
      ) : confirming ? (
        <p>
          If you make new codes, the codes you have now stop working.{" "}
          <Button onPress={() => make.mutate()} isDisabled={make.isPending}>
            Make new codes
          </Button>{" "}
          <Button onPress={() => setConfirming(false)}>Keep my codes</Button>
        </p>
      ) : (
        <Button onPress={() => (hasCodes ? setConfirming(true) : make.mutate())} isDisabled={make.isPending || codeStatus.isPending}>
          Make new recovery codes
        </Button>
      )}
      {make.isError &&
        (make.error instanceof ApiError && make.error.detail === "sign-in-again" ? (
          <p role="alert">
            To make new codes, you need to have signed in within the last 15 minutes.{" "}
            {/* A full page load, because the browser goes on to Google and back. */}
            <a href="/api/v1/auth/google/start">Sign in with Google again</a>, then open Your recovery codes on the home page.
          </p>
        ) : (
          <p role="alert">New codes could not be made. Please try again.</p>
        ))}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
