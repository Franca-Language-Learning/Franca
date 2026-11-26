// The client for Franca's API. The types in schema.d.ts are generated from contracts/openapi.yaml by
// pnpm --filter @franca/client generate:api, so after the types are regenerated, a changed endpoint causes a type error here.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Health = components["schemas"]["Health"];

const BASE_URL = globalThis.location?.origin ?? "http://localhost";
// Over https the cookie is called __Host-franca_csrf, so another computer in the same tailnet cannot set it.
const ANTI_FORGERY_COOKIES = ["__Host-franca_csrf", "franca_csrf"];
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function readCookie(name: string): string | undefined {
  const cookies = typeof document === "undefined" ? "" : document.cookie;
  return cookies
    .split(";")
    .map((part) => part.trim().split("="))
    .find(([key]) => key === name)?.[1];
}

function antiForgeryToken(): string | undefined {
  for (const name of ANTI_FORGERY_COOKIES) {
    const value = readCookie(name);
    if (value) return value;
  }
  return undefined;
}

/** A request that changes something carries the anti-forgery token from the franca_csrf cookie in the X-CSRF-Token
 * header (story E02-003). The server gives the cookie with any answer, so if the browser has none yet, the health
 * check is asked for first. */
async function withAntiForgeryToken(request: Request): Promise<Request> {
  if (SAFE_METHODS.has(request.method)) return request;
  if (!antiForgeryToken()) await globalThis.fetch(new Request(new URL("/api/v1/health", BASE_URL)));
  const token = antiForgeryToken();
  if (!token) return request;
  const headers = new Headers(request.headers);
  headers.set("X-CSRF-Token", token);
  return new Request(request, { headers });
}

const api = createClient<paths>({
  baseUrl: BASE_URL,
  // fetch is looked up on each call, so the mock API in the tests (which replaces fetch) is used.
  fetch: async (request) => globalThis.fetch(await withAntiForgeryToken(request)),
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

export type Session = components["schemas"]["SessionOut"];

export async function listSessions(signal?: AbortSignal): Promise<Session[]> {
  const { data, error, response } = await api.GET("/api/v1/sessions", { signal });
  if (!data) throw failure(response, error);
  return data.sessions;
}

export async function signOutDevice(sessionId: number): Promise<void> {
  const { error, response } = await api.DELETE("/api/v1/sessions/{sessionId}", { params: { path: { sessionId } } });
  if (!response.ok) throw failure(response, error);
}

/** Signs out every device except this one, and returns how many were signed out. */
export async function signOutOtherDevices(): Promise<number> {
  const { data, error, response } = await api.POST("/api/v1/sessions/sign-out-others");
  if (!data) throw failure(response, error);
  return data.signedOut;
}

/** Signs out on this device. */
export async function signOut(): Promise<void> {
  const { error, response } = await api.POST("/api/v1/auth/sign-out");
  if (!response.ok) throw failure(response, error);
}
