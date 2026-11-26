import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../../api/client";

/** The first screen of milestone M0: the app's name and whether the server is running. */
export function HomePage() {
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => getHealth(signal) });

  return (
    <main>
      <h1>Franca</h1>
      {health.isError ? (
        <p role="alert">Franca cannot reach its server. Check that Franca is running on your PC, then reload this page.</p>
      ) : (
        <p role="status">{health.data ? `Franca is running. Version ${health.data.version}.` : "Checking the server…"}</p>
      )}
    </main>
  );
}
