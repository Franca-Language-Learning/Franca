import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { NotSignedIn } from "../../account/messages";
import { isNotSignedIn, listSessions, type Session, signOutDevice, signOutOtherDevices } from "../../api/client";

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
        <Button onPress={() => signOut.mutate()} isDisabled={signOut.isPending} aria-label={`Sign out on ${name}`}>
          Sign out
        </Button>
      )}
      {signOut.isError && <p role="alert">Signing out on that device did not work. Please try again.</p>}
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

  if (isNotSignedIn(sessions.error)) return <NotSignedIn title="Your devices" pageName="Your devices" />;

  const others = (sessions.data ?? []).filter((session) => !session.current).length;
  return (
    <main>
      <h1>Your devices</h1>
      <p>These are the devices where you are signed in to Franca. A device with two browsers is listed twice. If you do not recognise a device, use its Sign out button.</p>
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
      {signOutOthers.isSuccess && <p role="status">You are now signed out on all other devices.</p>}
      {signOutOthers.isError && <p role="alert">Signing out on other devices did not work. Please try again.</p>}

      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </main>
  );
}
