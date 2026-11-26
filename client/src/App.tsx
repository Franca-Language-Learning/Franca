import { useEffect, useState } from "react";
import { getHealth, type Health } from "./api";

type ServerState = { kind: "checking" } | { kind: "running"; health: Health } | { kind: "unreachable" };

/** The first screen of milestone M0: the app's name and whether the server is running. */
export function App() {
  const [server, setServer] = useState<ServerState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setServer({ kind: "running", health }))
      .catch(() => {
        if (!controller.signal.aborted) setServer({ kind: "unreachable" });
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>Franca</h1>
      {server.kind === "unreachable" ? (
        <p role="alert">Franca cannot reach its server. Check that Franca is running on your PC, then reload this page.</p>
      ) : (
        <p role="status">{server.kind === "checking" ? "Checking the server…" : `Franca is running. Version ${server.health.version}.`}</p>
      )}
    </main>
  );
}
