// Mock API handlers made from contracts/openapi.yaml, so the client can be built and tested without the server
// (story E13-001). Each operation is answered with the example in its success response's schema; the server's
// tests check that every response has one. In a test, a handler can be replaced with server.use(...) to return
// a specific answer.
import { type HttpHandler, HttpResponse, http } from "msw";
import { parse } from "yaml";
import contractText from "../../../contracts/openapi.yaml?raw";

interface Schema {
  $ref?: string;
  examples?: unknown[];
  [key: string]: unknown;
}

interface Operation {
  responses?: Record<string, { content?: Record<string, { schema?: Schema }> }>;
}

interface Contract {
  paths: Record<string, Record<string, Operation>>;
  components?: { schemas?: Record<string, Schema> };
}

export const contract = parse(contractText) as Contract;

const METHODS = { get: http.get, post: http.post, put: http.put, patch: http.patch, delete: http.delete } as const;

function resolve(schema: Schema | undefined): Schema | undefined {
  const name = schema?.$ref?.split("/").pop();
  return name ? contract.components?.schemas?.[name] : schema;
}

/** The first example of the operation's first 2xx JSON response, or undefined when there is none. */
export function responseExample(operation: Operation): unknown {
  const success = Object.entries(operation.responses ?? {}).find(([status]) => status.startsWith("2"));
  return resolve(success?.[1].content?.["application/json"]?.schema)?.examples?.[0];
}

export function handlersFromContract(): HttpHandler[] {
  return Object.entries(contract.paths).flatMap(([path, operations]) =>
    Object.entries(operations).flatMap(([method, operation]) => {
      const route = METHODS[method as keyof typeof METHODS];
      if (!route) return [];
      const example = responseExample(operation);
      return [
        route(path.replace(/\{(\w+)\}/g, ":$1"), () =>
          example === undefined
            ? HttpResponse.json({ detail: "The contract has no example for this response" }, { status: 501 })
            : HttpResponse.json(example as Parameters<typeof HttpResponse.json>[0]),
        ),
      ];
    }),
  );
}
