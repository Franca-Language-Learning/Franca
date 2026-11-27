import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/server";
import { ApiError, getHealth, getMe, isNotSignedIn, needsRecentSignIn, signOut } from "./client";

describe("API client", () => {
  it("reads the health response as described in the contract", async () => {
    server.use(http.get("*/api/v1/health", () => HttpResponse.json({ status: "ok", version: "0.1.0" })));
    await expect(getHealth()).resolves.toEqual({ status: "ok", version: "0.1.0" });
  });

  it("gets a response from the mock API made from the contract", async () => {
    const health = await getHealth();
    expect(typeof health.status).toBe("string");
    expect(typeof health.version).toBe("string");
  });

  it("throws when the server answers with an error", async () => {
    server.use(http.get("*/api/v1/health", () => new HttpResponse(null, { status: 503 })));
    await expect(getHealth()).rejects.toThrow("503");
  });

  it("throws an ApiError with the status for each call, including the health check and the signed-in learner", async () => {
    server.use(
      http.get("*/api/v1/health", () => HttpResponse.json({ detail: "The database is busy. Please try again." }, { status: 503 })),
      http.get("*/api/v1/me", () => HttpResponse.json({ detail: "The database is busy. Please try again." }, { status: 503 })),
    );
    for (const call of [getHealth, getMe]) {
      const error = await call().catch((thrown: unknown) => thrown);
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 503, detail: "The database is busy. Please try again." });
    }
  });

  it("tells a signed-out answer and a sign-in-again answer from other errors", () => {
    expect(isNotSignedIn(new ApiError(401, "Not signed in"))).toBe(true);
    expect(isNotSignedIn(new ApiError(403, "sign-in-again"))).toBe(false);
    expect(isNotSignedIn(new Error("401"))).toBe(false);
    expect(needsRecentSignIn(new ApiError(403, "sign-in-again"))).toBe(true);
    expect(needsRecentSignIn(new ApiError(403, "Only the owner can invite learners"))).toBe(false);
  });
});

describe("anti-forgery token", () => {
  it("sends the token from the franca_csrf cookie with a request that changes something", async () => {
    document.cookie = "franca_csrf=test-token; path=/";
    let sent: string | null = null;
    server.use(
      http.post("*/api/v1/auth/sign-out", ({ request }) => {
        sent = request.headers.get("X-CSRF-Token");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await signOut();
    expect(sent).toBe("test-token");
    document.cookie = "franca_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("asks for the health check first when the browser has no token cookie yet", async () => {
    const asked: string[] = [];
    server.use(
      http.get("*/api/v1/health", () => {
        asked.push("health");
        document.cookie = "franca_csrf=fresh-token; path=/";
        return HttpResponse.json({ status: "ok", version: "0.1.0" });
      }),
      http.post("*/api/v1/auth/sign-out", ({ request }) => {
        asked.push(`sign-out ${request.headers.get("X-CSRF-Token")}`);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await signOut();
    expect(asked).toEqual(["health", "sign-out fresh-token"]);
    document.cookie = "franca_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });
});
