// The browser's passkey calls (WebAuthn), with the options and answers in the JSON form that the server uses.
// The server sends challenges and ids as base64url text; the browser takes and gives them as bytes.
import type { CredentialJson, PublicKeyOptionsJson } from "../../api/client";

/** The person closed the browser's passkey window, or it timed out. */
export class PasskeyCancelled extends Error {}
/** This device has a passkey for this learner already. */
export class PasskeyExists extends Error {}

interface Descriptor {
  id: string;
  type: "public-key";
  transports?: AuthenticatorTransport[];
}

export function passkeysSupported(): boolean {
  return typeof globalThis.PublicKeyCredential === "function" && typeof globalThis.navigator?.credentials?.create === "function";
}

export function fromBase64url(text: string): ArrayBuffer {
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export function toBase64url(buffer: ArrayBuffer | null | undefined): string {
  if (!buffer) return "";
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] {
  return ((list as Descriptor[] | undefined) ?? []).map((d) => ({ ...d, id: fromBase64url(d.id) }));
}

function translate(error: unknown): unknown {
  if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "AbortError")) return new PasskeyCancelled(error.message);
  if (error instanceof DOMException && error.name === "InvalidStateError") return new PasskeyExists(error.message);
  return error;
}

function common(credential: PublicKeyCredential) {
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
}

/** Makes a passkey on this device (navigator.credentials.create) and returns the answer for the server. */
export async function createPasskey(options: PublicKeyOptionsJson): Promise<CredentialJson> {
  const json = options as Record<string, unknown> & { challenge: string; user: { id: string; name: string; displayName: string } };
  const publicKey = {
    ...json,
    challenge: fromBase64url(json.challenge),
    user: { ...json.user, id: fromBase64url(json.user.id) },
    excludeCredentials: descriptors(json.excludeCredentials),
  } as PublicKeyCredentialCreationOptions;
  let credential: PublicKeyCredential;
  try {
    credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential;
  } catch (error) {
    throw translate(error);
  }
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    ...common(credential),
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: typeof response.getTransports === "function" ? response.getTransports() : [],
    },
  };
}

/** Asks the device for one of its passkeys for this site (navigator.credentials.get) and returns the answer. */
export async function signInOnDevice(options: PublicKeyOptionsJson): Promise<CredentialJson> {
  const json = options as Record<string, unknown> & { challenge: string };
  const publicKey = {
    ...json,
    challenge: fromBase64url(json.challenge),
    allowCredentials: descriptors(json.allowCredentials),
  } as PublicKeyCredentialRequestOptions;
  let credential: PublicKeyCredential;
  try {
    credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential;
  } catch (error) {
    throw translate(error);
  }
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    ...common(credential),
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: toBase64url(response.userHandle),
    },
  };
}
