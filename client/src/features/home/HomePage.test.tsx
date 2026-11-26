import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AppRoot } from "../../AppRoot";
import { server } from "../../mocks/server";

function serverAnswers(version = "0.1.0") {
  server.use(http.get("*/api/v1/health", () => HttpResponse.json({ status: "ok", version })));
}

describe("home page", () => {
  it("names the app in a level-one heading", async () => {
    serverAnswers();
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Franca" })).toBeInTheDocument();
  });

  it("tells the learner the server's version when the server is running", async () => {
    serverAnswers("0.1.0");
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByText("The Franca server is running (version 0.1.0).")).toBeInTheDocument();
  });

  it("tells the learner when the server cannot be reached", async () => {
    server.use(http.get("*/api/v1/health", () => HttpResponse.error()));
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The Franca server is not responding.");
  });

  it("announces the status politely to screen readers while it checks", async () => {
    server.use(http.get("*/api/v1/health", () => new Promise<never>(() => {})));
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Checking the server");
  });

  it("has no accessibility violations that axe can detect", async () => {
    serverAnswers();
    const { container } = render(<AppRoot initialPath="/" />);
    await screen.findByText(/server is running/);
    // jsdom has no canvas, so colour contrast is checked in the browser tests (story E17-005) instead.
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
