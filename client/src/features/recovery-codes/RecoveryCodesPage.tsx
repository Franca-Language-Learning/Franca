import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { NotSignedIn, SignInAgain } from "../../account/messages";
import { getRecoveryCodeStatus, isNotSignedIn, makeRecoveryCodes, needsRecentSignIn } from "../../api/client";
import { formatDay } from "../../format";

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
        Write these codes down or keep them in your password manager now. You will not see them again after you leave
        this page. A code can be used one time.
      </p>
      <ol className="recovery-codes">
        {codes.map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ol>
      <Button onPress={copy}>Copy the codes</Button>
      {copied === true && (
        <p role="status">
          The codes have been copied. Paste them into your password manager. Then copy something else, so that the codes
          are not left on the clipboard.
        </p>
      )}
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

  if (isNotSignedIn(codeStatus.error)) return <NotSignedIn title="Recovery codes" pageName="Your recovery codes" />;

  const hasCodes = (codeStatus.data?.unused ?? 0) > 0;
  return (
    <main>
      <h1>Recovery codes</h1>
      <p>
        If you lose the phone with your passkey or cannot use your Google account, you can sign in with your e-mail address
        and a recovery code. A code can be used one time.
      </p>
      {codeStatus.isPending && <p role="status">Loading…</p>}
      {codeStatus.isError && <p role="alert">Your recovery codes could not be loaded. Reload this page to try again.</p>}
      {codeStatus.data &&
        (codeStatus.data.createdAt && codeStatus.data.unused === 0 ? (
          <p>You have used all your recovery codes. You can make new ones below.</p>
        ) : codeStatus.data.createdAt ? (
          <p>
            You have {codeStatus.data.unused} unused {codeStatus.data.unused === 1 ? "code" : "codes"}, made on{" "}
            {formatDay(codeStatus.data.createdAt)}.
          </p>
        ) : (
          <p>You have no recovery codes yet.</p>
        ))}

      {make.data ? (
        <NewCodes codes={make.data} />
      ) : confirming ? (
        <p>
          If you make new codes, the codes you have now will stop working.{" "}
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
        (needsRecentSignIn(make.error) ? (
          <SignInAgain action="make new codes" pageName="Your recovery codes" />
        ) : (
          <p role="alert">New codes could not be made. Please try again.</p>
        ))}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
