import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Form, Input, Label, TextField } from "react-aria-components";
import {
  addPasskey,
  ApiError,
  getPasskeyRegistrationOptions,
  listPasskeys,
  type Passkey,
  removePasskey,
} from "../../api/client";
import { createPasskey, PasskeyCancelled, PasskeyExists, passkeysSupported } from "./webauthn";

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

function day(iso: string): string {
  return DATE.format(new Date(iso));
}

function addFailure(error: unknown): string {
  if (error instanceof PasskeyCancelled) return "No passkey was added. The passkey window was closed or timed out.";
  if (error instanceof PasskeyExists) return "This device has a passkey for your account already.";
  if (error instanceof ApiError && error.status === 403) return "You have the most passkeys allowed. Remove one before you add another.";
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
        Added on {day(passkey.createdAt)}. {passkey.lastUsedAt ? `Last used on ${day(passkey.lastUsedAt)}.` : "Not used yet."}
        {passkey.synced && " It is synced to your other devices by your password manager or account."}
      </p>
      {remove.isError && <p role="alert">The passkey could not be removed. Please try again.</p>}
      {confirming ? (
        <p>
          After you remove it, you cannot sign in with this passkey.{" "}
          <Button onPress={() => remove.mutate()} isDisabled={remove.isPending}>
            Remove {name}
          </Button>{" "}
          <Button onPress={() => setConfirming(false)}>Keep it</Button>
        </p>
      ) : (
        <Button onPress={() => setConfirming(true)} aria-label={`Remove ${name}…`}>
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

  if (passkeys.error instanceof ApiError && passkeys.error.status === 401) {
    return (
      <main>
        <h1>Passkeys</h1>
        <p>
          You are not signed in. <Link to="/sign-in">Sign in</Link> first, then come back to this page.
        </p>
      </main>
    );
  }

  return (
    <main>
      <h1>Passkeys</h1>
      <p>
        With a passkey you can sign in to Franca without Google. The passkey is kept by your phone, computer or password
        manager, and you confirm it with your fingerprint, face or screen lock.
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
            <Input placeholder="For example: Phone" />
          </TextField>
          <Button type="submit" isDisabled={add.isPending}>
            Add a passkey
          </Button>
          {add.isPending && <p role="status">Follow the steps in your browser’s passkey window.</p>}
          {add.isSuccess && <p role="status">The passkey was added.</p>}
          {add.isError && <p role="alert">{addFailure(add.error)}</p>}
        </Form>
      ) : (
        <p>This browser cannot make passkeys. Open this page in a recent version of Chrome, Edge, Firefox or Safari.</p>
      )}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
