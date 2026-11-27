import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AppRoot } from "../../AppRoot";
import { server } from "../../mocks/server";
import { expectNoAxeViolations } from "../../testing/axe";

describe("sign-in page", () => {
  it("has a link that starts the sign-in with Google", async () => {
    render(<AppRoot initialPath="/sign-in" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in to Franca" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toHaveAttribute("href", "/api/v1/auth/google/start");
  });

  it.each([
    ["not-invited", "There is no invitation to Franca for this Google account."],
    ["email-not-verified", "Google has not verified the e-mail address of this account."],
    ["disabled", "Your account is switched off."],
    ["failed", "Signing in with Google did not work."],
  ])("explains why a sign-in was refused (%s)", async (error, message) => {
    render(<AppRoot initialPath={`/sign-in?error=${error}`} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("shows no message for an unknown reason", async () => {
    render(<AppRoot initialPath="/sign-in?error=something-else" />);
    await screen.findByRole("heading", { level: 1, name: "Sign in to Franca" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("has no accessibility violations that axe can detect", async () => {
    const { container } = render(<AppRoot initialPath="/sign-in?error=not-invited" />);
    await screen.findByRole("alert");
    await expectNoAxeViolations(container);
  });
});

describe("home page and the signed-in learner", () => {
  it("names the signed-in learner", async () => {
    server.use(http.get("*/api/v1/me", () => HttpResponse.json({ displayName: "Nik", role: "owner" })));
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByText("You are signed in as Nik.")).toBeInTheDocument();
  });

  it("offers the sign-in page to someone who is not signed in", async () => {
    server.use(http.get("*/api/v1/me", () => HttpResponse.json({ detail: "Not signed in" }, { status: 401 })));
    render(<AppRoot initialPath="/" />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });
});
