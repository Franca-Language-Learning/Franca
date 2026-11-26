import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/server";
import { getHealth } from "./client";

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
});
