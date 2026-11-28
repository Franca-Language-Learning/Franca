import fc from "fast-check";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/server";
import { ApiError, cookieValue, getHealth, getMe, isNotSignedIn, needsRecentSignIn, signOut } from "./client";

// A cookie value is made of the characters that RFC 6265 allows (cookie-octet), which include "=".
const cookieOctet = fc.constantFrom(
  ...Array.from({ length: 0x7e - 0x21 + 1 }, (_, i) => String.fromCharCode(0x21 + i)).filter((character) => !'",;\\'.includes(character)),
);
const cookieValueText = fc.string({ unit: cookieOctet, minLength: 1, maxLength: 40, size: "max" });

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

  it("sends the cookie's value unchanged for any value made of RFC 6265 cookie-octet characters", async () => {
    const otherCookies = fc.uniqueArray(fc.tuple(fc.stringMatching(/^x[a-z0-9]{0,7}$/), cookieValueText), {
      maxLength: 3,
      size: "max",
      selector: ([name]) => name,
    });
    await fc.assert(
      fc.asyncProperty(cookieValueText, otherCookies, async (token, others) => {
        const names = ["franca_csrf", ...others.map(([name]) => name)];
        for (const [name, value] of others) document.cookie = `${name}=${value}; path=/`;
        document.cookie = `franca_csrf=${token}; path=/`;
        let sent: string | null = null;
        server.use(
          http.post("*/api/v1/auth/sign-out", ({ request }) => {
            sent = request.headers.get("X-CSRF-Token");
            return new HttpResponse(null, { status: 204 });
          }),
        );
        try {
          await signOut();
          expect(sent).toBe(token);
        } finally {
          for (const name of names) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
        }
      }),
      { numRuns: 50 },
    );
  });
});

describe("cookieValue", () => {
  // The other names include names that start or end with franca_csrf, such as franca_csrf_old.
  const otherName = fc.oneof(
    fc.stringMatching(/^x[a-z0-9]{0,7}$/),
    fc.stringMatching(/^franca_csrf[a-z0-9_]{1,4}$/),
    fc.stringMatching(/^[a-z]{1,4}franca_csrf$/),
  );
  const otherCookies = fc.uniqueArray(fc.tuple(otherName, cookieValueText), { maxLength: 4, size: "max", selector: ([name]) => name });

  it("finds the value of the named cookie at any place in the list", () => {
    fc.assert(
      fc.property(cookieValueText, otherCookies, fc.nat(), (token, others, place) => {
        const cookies = others.map(([name, value]) => `${name}=${value}`);
        cookies.splice(place % (cookies.length + 1), 0, `franca_csrf=${token}`);
        expect(cookieValue(cookies.join("; "), "franca_csrf")).toBe(token);
      }),
      { numRuns: 200 },
    );
  });
});
