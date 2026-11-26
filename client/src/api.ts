// Calls to Franca's API. The types follow contracts/openapi.yaml; from story E01-002 they are generated from it.

export interface Health {
  status: string;
  version: string;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/v1/health", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`The health check returned ${response.status}`);
  return (await response.json()) as Health;
}
