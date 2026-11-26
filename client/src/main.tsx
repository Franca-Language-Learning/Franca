import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppRoot } from "./AppRoot";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no element with id root");
createRoot(root).render(
  <StrictMode>
    <AppRoot />
  </StrictMode>,
);
