import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AppRoot } from "./AppRoot";
import { server } from "./mocks/server";

describe("routes", () => {
  it("shows the home page at /", async () => {
    server.use(http.get("*/api/v1/health", () => HttpResponse.json({ status: "ok", version: "0.1.0" })));
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Franca" })).toBeInTheDocument();
  });

  it("shows a page-not-found message with a link home for an unknown address", async () => {
    render(<AppRoot initialPath="/no-such-page" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  });
});
