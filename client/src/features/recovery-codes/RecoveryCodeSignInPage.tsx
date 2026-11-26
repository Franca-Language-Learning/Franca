import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button, FieldError, Form, Input, Label, Text, TextField } from "react-aria-components";
import { ApiError, signInWithRecoveryCode } from "../../api/client";

function failure(error: unknown): string {
  if (error instanceof ApiError && error.detail === "too-many-attempts")
    return "There were too many wrong codes. Wait 15 minutes, then try again.";
  if (error instanceof ApiError && error.detail === "disabled") return "Your account is switched off. Ask the person who runs Franca to switch it on again.";
  if (error instanceof ApiError && error.status === 401)
    return "The e-mail address or the code is not right, or the code has been used already. Check both and try again.";
  return "Signing in did not work. Please try again.";
}

/** Signing in with an e-mail address and a recovery code. */
export function RecoveryCodeSignInPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const signIn = useMutation({
    mutationFn: () => signInWithRecoveryCode(email.trim(), code),
    onSuccess: async (me) => {
      queryClient.setQueryData(["me"], me);
      await navigate({ to: "/" });
    },
  });
  return (
    <main>
      <h1>Sign in with a recovery code</h1>
      <p>Use the e-mail address of your Google account and one of the recovery codes you made earlier.</p>
      <Form
        onSubmit={(event) => {
          event.preventDefault();
          signIn.mutate();
        }}
      >
        <TextField type="email" value={email} onChange={setEmail} isRequired autoComplete="email" maxLength={254}>
          <Label>E-mail address</Label>
          <Input />
          <FieldError>Type your e-mail address.</FieldError>
        </TextField>
        <TextField value={code} onChange={setCode} isRequired autoComplete="one-time-code" maxLength={40}>
          <Label>Recovery code</Label>
          {/* No spelling check: some browsers send the text of a field to an online spelling service. */}
          <Input spellCheck={false} autoCorrect="off" autoCapitalize="characters" />
          <Text slot="description">A code looks like ABCDE-FGHJK.</Text>
          <FieldError>Type one of your recovery codes.</FieldError>
        </TextField>
        <Button type="submit" isDisabled={signIn.isPending}>
          Sign in
        </Button>
        {signIn.isPending && <p role="status">Checking the code…</p>}
        {signIn.isError && <p role="alert">{failure(signIn.error)}</p>}
      </Form>
      <p>
        <Link to="/sign-in">Back to the sign-in page</Link>
      </p>
    </main>
  );
}
