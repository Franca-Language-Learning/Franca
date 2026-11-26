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
