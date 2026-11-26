import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Button } from "react-aria-components";
import { getHealth, getMe, signOut } from "../../api/client";

/** The first screen of milestone M0: the app's name, whether the server is running and who is signed in. */
export function HomePage() {
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => getHealth(signal) });
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal) });
  const queryClient = useQueryClient();
  // After signing out, nothing of the learner's is kept in the page: the cache is emptied and "me" is set to nobody.
  const leave = useMutation({
    mutationFn: signOut,
    onSuccess: () => {
      queryClient.clear();
      queryClient.setQueryData(["me"], null);
    },
  });

  return (
    <main>
      <h1>Franca</h1>
      {health.isError ? (
        <p role="alert">The Franca server cannot be reached. Check that Franca is running on the computer where it is installed, then reload this page.</p>
      ) : (
        <p role="status">{health.data ? `The Franca server is running (version ${health.data.version}).` : "Checking the server…"}</p>
      )}
      {me.data && (
        <>
          <p>You are signed in as {me.data.displayName}.</p>
          <ul>
            <li>
              <Link to="/passkeys">Your passkeys</Link>
            </li>
            <li>
              <Link to="/recovery-codes">Your recovery codes</Link>
            </li>
            <li>
              <Link to="/devices">Your devices</Link>
            </li>
          </ul>
          <Button onPress={() => leave.mutate()} isDisabled={leave.isPending}>
            Sign out on this device
          </Button>
          {leave.isError && <p role="alert">Signing out did not work. Please try again.</p>}
        </>
      )}
      {me.data === null && (
        <p>
          You are not signed in. <Link to="/sign-in">Sign in</Link>.
        </p>
      )}
    </main>
  );
}
