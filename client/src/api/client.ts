// The client for Franca's API. The types in schema.d.ts are generated from contracts/openapi.yaml by
// pnpm --filter @franca/client generate:api, so after the types are regenerated, a changed endpoint causes a type error here.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Health = components["schemas"]["Health"];

const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "http://localhost",
  // fetch is looked up on each call, so the mock API in the tests (which replaces fetch) is used.
  fetch: (request) => globalThis.fetch(request),
});

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const { data, response } = await api.GET("/api/v1/health", { signal });
  if (!data) throw new Error(`The health check returned ${response.status}`);
  return data;
}

export type Me = components["schemas"]["Me"];

/** The signed-in learner, or null when nobody is signed in on this device. */
export async function getMe(signal?: AbortSignal): Promise<Me | null> {
  const { data, response } = await api.GET("/api/v1/me", { signal });
  if (response.status === 401) return null;
  if (!data) throw new Error(`The request for the signed-in learner returned ${response.status}`);
  return data;
}

export type Passkey = components["schemas"]["PasskeyOut"];
/** The options for navigator.credentials, in their JSON form (challenge and ids as base64url text). */
export type PublicKeyOptionsJson = components["schemas"]["PublicKeyOptions"]["publicKey"];
/** The device's answer, in the JSON form of a PublicKeyCredential. */
export type CredentialJson = Record<string, unknown>;

/** An answer from the server that is not a success, with the reason the server gave (detail). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`The server answered ${status}: ${detail}`);
  }
}

/** The error for an answer that is not a success. body is the answer's JSON, as openapi-fetch read it. */
function failure(response: Response, body: unknown): ApiError {
  const detail = body && typeof body === "object" && "detail" in body && typeof body.detail === "string" ? body.detail : "";
  return new ApiError(response.status, detail);
}

export async function listPasskeys(signal?: AbortSignal): Promise<Passkey[]> {
  const { data, error, response } = await api.GET("/api/v1/passkeys", { signal });
  if (!data) throw failure(response, error);
  return data.passkeys;
}

export async function getPasskeyRegistrationOptions(): Promise<PublicKeyOptionsJson> {
  const { data, error, response } = await api.POST("/api/v1/passkeys/options");
  if (!data) throw failure(response, error);
  return data.publicKey;
}

export async function addPasskey(credential: CredentialJson, label: string | null): Promise<Passkey> {
  const { data, error, response } = await api.POST("/api/v1/passkeys", { body: { credential, label } });
  if (!data) throw failure(response, error);
  return data;
}

export async function removePasskey(passkeyId: string): Promise<void> {
  const { error, response } = await api.DELETE("/api/v1/passkeys/{passkeyId}", { params: { path: { passkeyId } } });
  if (!response.ok) throw failure(response, error);
}

export async function getPasskeySignInOptions(): Promise<PublicKeyOptionsJson> {
  const { data, error, response } = await api.POST("/api/v1/auth/passkey/options");
  if (!data) throw failure(response, error);
  return data.publicKey;
}

export async function signInWithPasskey(credential: CredentialJson): Promise<Me> {
  const { data, error, response } = await api.POST("/api/v1/auth/passkey", { body: { credential } });
  if (!data) throw failure(response, error);
  return data;
}

export type RecoveryCodeStatus = components["schemas"]["RecoveryCodeStatusOut"];

export async function getRecoveryCodeStatus(signal?: AbortSignal): Promise<RecoveryCodeStatus> {
  const { data, error, response } = await api.GET("/api/v1/recovery-codes", { signal });
  if (!data) throw failure(response, error);
  return data;
}

/** Makes ten new recovery codes. The old ones stop working. */
export async function makeRecoveryCodes(): Promise<string[]> {
  const { data, error, response } = await api.POST("/api/v1/recovery-codes");
  if (!data) throw failure(response, error);
  return data.codes;
}

export async function signInWithRecoveryCode(email: string, code: string): Promise<Me> {
  const { data, error, response } = await api.POST("/api/v1/auth/recovery-code", { body: { email, code } });
  if (!data) throw failure(response, error);
  return data;
}
