import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError, listSessions, type Session, signOutDevice, signOutOtherDevices } from "../../api/client";

const WHEN = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const DEVICE_KINDS: Record<string, string> = { desktop: "Computer", tablet: "Tablet", phone: "Phone" };

function DeviceItem({ session }: { session: Session }) {
  const queryClient = useQueryClient();
  const signOut = useMutation({
    mutationFn: () => signOutDevice(session.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const name = `${DEVICE_KINDS[session.deviceKind] ?? "Device"}: ${session.browser}`;
  return (
    <li>
      <h2>
        {name}
        {session.current && " (this device)"}
      </h2>
      <p>
        Signed in on {WHEN.format(new Date(session.signedInAt))}. Last used on {WHEN.format(new Date(session.lastUsedAt))}.
      </p>
      {!session.current && (
        <Button onPress={() => signOut.mutate()} isDisabled={signOut.isPending} aria-label={`Sign out ${name}`}>
          Sign out
        </Button>
      )}
      {signOut.isError && <p role="alert">This device could not be signed out. Please try again.</p>}
    </li>
  );
}

/** The devices the learner is signed in on, with a way to sign out one of them or all but this one. */
export function DevicesPage() {
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: ({ signal }) => listSessions(signal) });
  const [confirming, setConfirming] = useState(false);
  const signOutOthers = useMutation({
    mutationFn: signOutOtherDevices,
    onSuccess: () => {
      setConfirming(false);
      return queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  if (sessions.error instanceof ApiError && sessions.error.status === 401) {
    return (
      <main>
        <h1>Your devices</h1>
        <p>
          You are not signed in. <Link to="/sign-in">Sign in</Link> first, then open Your devices on the home page.
        </p>
      </main>
    );
  }

  const others = (sessions.data ?? []).filter((session) => !session.current).length;
  return (
    <main>
      <h1>Your devices</h1>
      <p>These are the browsers where you are signed in to Franca. If you do not recognise one, sign it out.</p>
      {sessions.isPending && <p role="status">Loading…</p>}
      {sessions.isError && <p role="alert">Your devices could not be loaded. Reload this page to try again.</p>}
      {sessions.data && (
        <ul>
          {sessions.data.map((session) => (
            <DeviceItem key={session.id} session={session} />
          ))}
        </ul>
      )}

      {others > 0 &&
        (confirming ? (
          <p>
            You will need to sign in again on {others === 1 ? "the other device" : `the ${others} other devices`}.{" "}
            <Button onPress={() => signOutOthers.mutate()} isDisabled={signOutOthers.isPending}>
              Sign out on {others === 1 ? "the other device" : "all other devices"}
            </Button>{" "}
            <Button onPress={() => setConfirming(false)}>Cancel</Button>
          </p>
        ) : (
          <Button onPress={() => setConfirming(true)}>Sign out on all other devices…</Button>
        ))}
      {signOutOthers.isSuccess && <p role="status">The other devices were signed out.</p>}
      {signOutOthers.isError && <p role="alert">The other devices could not be signed out. Please try again.</p>}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
