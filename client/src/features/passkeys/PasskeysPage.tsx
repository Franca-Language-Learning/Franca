import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Form, Input, Label, TextField } from "react-aria-components";
import { NotSignedIn, SignInAgain } from "../../account/messages";
import {
  addPasskey,
  ApiError,
  getPasskeyRegistrationOptions,
  isNotSignedIn,
  listPasskeys,
  needsRecentSignIn,
  type Passkey,
  removePasskey,
} from "../../api/client";
import { formatDay } from "../../format";
import { createPasskey, PasskeyCancelled, PasskeyExists, passkeysSupported } from "./webauthn";

function addFailure(error: unknown): string {
  if (error instanceof PasskeyCancelled) return "No passkey was added, because the passkey window was closed or took too long. To try again, select Add a passkey.";
  if (error instanceof PasskeyExists) return "There is already a passkey for your account on this device. You can use it to sign in.";
  if (error instanceof ApiError && error.status === 403) return "You have the maximum number of passkeys. Remove one before you add another.";
  return "The passkey could not be added. Please try again.";
}

function PasskeyItem({ passkey }: { passkey: Passkey }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => removePasskey(passkey.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["passkeys"] }),
  });
  const name = passkey.label ?? "Passkey with no name";
  return (
    <li>
      <h3>{name}</h3>
      <p>
        Added on {formatDay(passkey.createdAt)}. {passkey.lastUsedAt ? `Last used on ${formatDay(passkey.lastUsedAt)}.` : "Not used yet."}
        {passkey.synced && " It is also available on your other devices that use the same password manager or account."}
      </p>
      {remove.isError && <p role="alert">The passkey could not be removed. Please try again.</p>}
      {confirming ? (
        <p>
          If you remove this passkey, you can no longer sign in with it. You can still sign in with Google.{" "}
          <Button onPress={() => remove.mutate()} isDisabled={remove.isPending}>
            Remove {name}
          </Button>{" "}
          <Button onPress={() => setConfirming(false)}>Keep it</Button>
        </p>
      ) : (
        <Button onPress={() => setConfirming(true)} aria-label={`Remove ${name}`}>
          Remove…
        </Button>
      )}
    </li>
  );
}

/** The signed-in learner's passkeys: a list with a way to add one on this device and to remove one. */
export function PasskeysPage() {
  const queryClient = useQueryClient();
  const passkeys = useQuery({ queryKey: ["passkeys"], queryFn: ({ signal }) => listPasskeys(signal) });
  const [label, setLabel] = useState("");
  const add = useMutation({
    mutationFn: async () => {
      const options = await getPasskeyRegistrationOptions();
      const answer = await createPasskey(options);
      return addPasskey(answer, label.trim() || null);
    },
    onSuccess: () => {
      setLabel("");
      return queryClient.invalidateQueries({ queryKey: ["passkeys"] });
    },
  });

  if (isNotSignedIn(passkeys.error)) return <NotSignedIn title="Passkeys" pageName="Your passkeys" />;

  return (
    <main>
      <h1>Passkeys</h1>
      <p>
        With a passkey you can sign in to Franca without Google. The passkey is stored on your phone or computer, or in
        your password manager. When you sign in, you confirm it is you in the same way you unlock your device, for
        example with your fingerprint or PIN.
      </p>

      <h2>Your passkeys</h2>
      {passkeys.isPending && <p role="status">Loading your passkeys…</p>}
      {passkeys.isError && <p role="alert">Your passkeys could not be loaded. Reload this page to try again.</p>}
      {passkeys.data?.length === 0 && <p>You have no passkeys yet.</p>}
      {passkeys.data && passkeys.data.length > 0 && (
        <ul>
          {passkeys.data.map((passkey) => (
            <PasskeyItem key={passkey.id} passkey={passkey} />
          ))}
        </ul>
      )}

      <h2>Add a passkey on this device</h2>
      {passkeysSupported() ? (
        <Form
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <TextField value={label} onChange={setLabel} maxLength={60}>
            <Label>Name for the passkey (you can leave this empty)</Label>
            <Input placeholder="For example: Work laptop" />
          </TextField>
          <Button type="submit" isDisabled={add.isPending}>
            Add a passkey
          </Button>
          {add.isPending && <p role="status">Follow the steps in the passkey window.</p>}
          {add.isSuccess && <p role="status">The passkey was added.</p>}
          {add.isError &&
            (needsRecentSignIn(add.error) ? (
              <SignInAgain action="add a passkey" pageName="Your passkeys" />
            ) : (
              <p role="alert">{addFailure(add.error)}</p>
            ))}
        </Form>
      ) : (
        <p>This browser does not support passkeys. Open this page in a recent version of Chrome, Edge, Firefox or Safari.</p>
      )}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
