import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

function mockFetch(response: Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(() => response));
}

describe("App", () => {
  it("names the app in a level-one heading", () => {
    mockFetch(new Promise(() => {}));
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Franca" })).toBeInTheDocument();
  });

  it("tells the learner the server's version when the server is running", async () => {
    mockFetch(Promise.resolve(Response.json({ status: "ok", version: "0.1.0" })));
    render(<App />);
    expect(await screen.findByText("Franca is running. Version 0.1.0.")).toBeInTheDocument();
  });

  it("tells the learner when the server cannot be reached", async () => {
    mockFetch(Promise.reject(new TypeError("Failed to fetch")));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Franca cannot reach its server.");
  });

  it("announces the status politely to screen readers", () => {
    mockFetch(new Promise(() => {}));
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking the server");
  });

  it("has no accessibility violations that axe can detect", async () => {
    mockFetch(Promise.resolve(Response.json({ status: "ok", version: "0.1.0" })));
    const { container } = render(<App />);
    await screen.findByText(/Franca is running/);
    // jsdom has no canvas, so colour contrast is checked in the browser tests (story E17-005) instead.
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
