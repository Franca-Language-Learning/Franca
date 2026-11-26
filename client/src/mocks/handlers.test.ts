import { describe, expect, it } from "vitest";
import { contract, handlersFromContract, responseExample } from "./handlers";

describe("mock API made from the contract", () => {
  it("has a handler for every operation in contracts/openapi.yaml", () => {
    const operations = Object.entries(contract.paths).flatMap(([path, item]) =>
      Object.keys(item).map((method) => `${method.toUpperCase()} ${path.replace(/\{(\w+)\}/g, ":$1")}`),
    );
    const handlers = handlersFromContract().map((h) => `${String(h.info.method).toUpperCase()} ${String(h.info.path)}`);
    expect(handlers.sort()).toEqual(operations.sort());
  });

  it("answers with the example from the response schema", () => {
    const operation = contract.paths["/api/v1/health"]?.get;
    expect(operation && responseExample(operation)).toEqual({ status: "ok", version: "0.1.0" });
  });

  it("finds no example when a response schema has none", () => {
    expect(responseExample({ responses: { "200": { content: { "application/json": { schema: { type: "object" } } } } } })).toBeUndefined();
  });
});
