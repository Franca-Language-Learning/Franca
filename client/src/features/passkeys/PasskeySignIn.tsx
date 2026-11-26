import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "react-aria-components";
import { ApiError, getPasskeySignInOptions, signInWithPasskey } from "../../api/client";
import { PasskeyCancelled, passkeysSupported, signInOnDevice } from "./webauthn";

function signInFailure(error: unknown): string {
  if (error instanceof PasskeyCancelled) return "You did not sign in. The passkey window was closed or timed out.";
  if (error instanceof ApiError && error.detail === "disabled") return "This account is switched off. Ask the owner to switch it on again.";
  if (error instanceof ApiError && error.status === 401)
    return "Franca does not know this passkey. Sign in with Google, then add the passkey again on the Passkeys page.";
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
      {signIn.isPending && <p role="status">Follow the steps in your browser’s passkey window.</p>}
      {signIn.isError && <p role="alert">{signInFailure(signIn.error)}</p>}
    </div>
  );
}
