// Mock API handlers made from contracts/openapi.yaml, so the client can be built and tested without the server
// (story E13-001). In a test, a handler can be replaced with server.use(...) to return a specific answer.
import { fromOpenApi } from "@mswjs/source/open-api";
import type { HttpHandler } from "msw";
import { parse } from "yaml";
import contractText from "../../../contracts/openapi.yaml?raw";

type Contract = Parameters<typeof fromOpenApi>[0] & { paths?: Record<string, Record<string, unknown> | undefined> };

export const contract = parse(contractText) as Contract;

export function handlersFromContract(): Promise<HttpHandler[]> {
  return fromOpenApi(contract);
}
