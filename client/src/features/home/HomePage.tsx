import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../../api/client";

/** The first screen of milestone M0: the app's name and whether the server is running. */
export function HomePage() {
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => getHealth(signal) });

  return (
    <main>
      <h1>Franca</h1>
      {health.isError ? (
        <p role="alert">The Franca server is not responding. Check that it is running on your PC, then reload this page.</p>
      ) : (
        <p role="status">{health.data ? `The Franca server is running (version ${health.data.version}).` : "Checking the server…"}</p>
      )}
    </main>
  );
}
