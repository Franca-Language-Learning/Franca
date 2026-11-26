import { describe, expect, it } from "vitest";
import { contract, handlersFromContract } from "./handlers";

describe("mock API made from the contract", () => {
  it("has a handler for every operation in contracts/openapi.yaml", async () => {
    const operations = Object.entries(contract.paths ?? {}).flatMap(([path, item]) =>
      Object.keys(item ?? {}).map((method) => `${method.toUpperCase()} ${path}`),
    );
    const handlers = await handlersFromContract();
    expect(handlers.map((h) => `${String(h.info.method).toUpperCase()} ${String(h.info.path).replace(/^\*/, "")}`).sort()).toEqual(operations.sort());
  });
});
