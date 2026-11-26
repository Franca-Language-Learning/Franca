// A stand-in for the browser's passkey calls (navigator.credentials) in tests. jsdom has no WebAuthn.
import { vi } from "vitest";

const bytes = (text: string) => new TextEncoder().encode(text).buffer;

/** Installs fake navigator.credentials.create and .get, and returns them so a test can check or change them. */
export function installFakeWebAuthn() {
  const credential = (response: Record<string, unknown>) => ({
    id: "cred-1",
    rawId: bytes("cred-1"),
    type: "public-key",
    authenticatorAttachment: "platform",
    getClientExtensionResults: () => ({}),
    response,
  });
  const create = vi.fn(async (_options: CredentialCreationOptions) =>
    credential({
      clientDataJSON: bytes("client-data"),
      attestationObject: bytes("attestation"),
      getTransports: () => ["internal"],
    }),
  );
  const get = vi.fn(async (_options: CredentialRequestOptions) =>
    credential({
      clientDataJSON: bytes("client-data"),
      authenticatorData: bytes("authenticator-data"),
      signature: bytes("signature"),
      userHandle: bytes("user"),
    }),
  );
  vi.stubGlobal("PublicKeyCredential", function PublicKeyCredential() {});
  Object.defineProperty(globalThis.navigator, "credentials", { value: { create, get }, configurable: true });
  return { create, get };
}

export function removeFakeWebAuthn() {
  vi.unstubAllGlobals();
  Object.defineProperty(globalThis.navigator, "credentials", { value: undefined, configurable: true });
}
