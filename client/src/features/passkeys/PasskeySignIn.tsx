import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "react-aria-components";
import { ApiError, getPasskeySignInOptions, signInWithPasskey } from "../../api/client";
import { PasskeyCancelled, passkeysSupported, signInOnDevice } from "./webauthn";

function signInFailure(error: unknown): string {
  if (error instanceof PasskeyCancelled) return "You are not signed in, because the passkey window was closed or took too long. To try again, select Sign in with a passkey.";
  if (error instanceof ApiError && error.detail === "disabled") return "Your account is switched off. Ask the person who runs Franca to switch it on again.";
  if (error instanceof ApiError && error.status === 401)
    return "This passkey is not linked to a Franca account. Sign in with Google, then add a new passkey on the Passkeys page.";
  return "Signing in with a passkey did not work. Please try again.";
}

/** A button that signs in with a passkey on this device. Nothing is shown in a browser without passkeys. */
export function PasskeySignIn() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const signIn = useMutation({
    mutationFn: async () => signInWithPasskey(await signInOnDevice(await getPasskeySignInOptions())),
    onSuccess: async (me) => {
      queryClient.setQueryData(["me"], me);
      await navigate({ to: "/" });
    },
  });
  if (!passkeysSupported()) return null;
  return (
    <div>
      <Button onPress={() => signIn.mutate()} isDisabled={signIn.isPending}>
        Sign in with a passkey
      </Button>
      {signIn.isPending && <p role="status">Follow the steps in the passkey window.</p>}
      {signIn.isError && <p role="alert">{signInFailure(signIn.error)}</p>}
    </div>
  );
}
