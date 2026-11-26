import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AppRoot } from "../../AppRoot";
import { server } from "../../mocks/server";

const LAPTOP = { id: 12, deviceKind: "desktop", browser: "Chrome on Windows", signedInAt: "2026-12-01T09:00:00.000Z", lastUsedAt: "2026-12-03T18:20:00.000Z", current: true };
const PHONE = { id: 9, deviceKind: "phone", browser: "Safari on iPhone", signedInAt: "2026-11-28T07:45:00.000Z", lastUsedAt: "2026-12-02T07:50:00.000Z", current: false };
const TABLET = { ...PHONE, id: 7, deviceKind: "tablet", browser: "Safari on iPad" };

describe("devices page", () => {
  it("lists the devices and marks this one", async () => {
    server.use(http.get("*/api/v1/sessions", () => HttpResponse.json({ sessions: [LAPTOP, PHONE] })));
    render(<AppRoot initialPath="/devices" />);
    expect(await screen.findByRole("heading", { level: 2, name: "Computer: Chrome on Windows (this device)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Phone: Safari on iPhone" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Sign out (Computer|Phone|Tablet)/ })).toHaveLength(1);
  });

  it("signs out another device", async () => {
    let list = [LAPTOP, PHONE];
    let ended = "";
    server.use(
      http.get("*/api/v1/sessions", () => HttpResponse.json({ sessions: list })),
      http.delete("*/api/v1/sessions/:id", ({ params }) => {
        ended = String(params.id);
        list = [LAPTOP];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<AppRoot initialPath="/devices" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out Phone: Safari on iPhone" }));
    await screen.findByRole("heading", { level: 2, name: "Computer: Chrome on Windows (this device)" });
    expect(screen.queryByText(/Safari on iPhone/)).toBeNull();
    expect(ended).toBe("9");
  });

  it("signs out all other devices after the learner confirms", async () => {
    let list = [LAPTOP, PHONE, TABLET];
    server.use(
      http.get("*/api/v1/sessions", () => HttpResponse.json({ sessions: list })),
      http.post("*/api/v1/sessions/sign-out-others", () => {
        list = [LAPTOP];
        return HttpResponse.json({ signedOut: 2 });
      }),
    );
    render(<AppRoot initialPath="/devices" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out on all other devices…" }));
    expect(screen.getByText(/You will need to sign in again on the 2 other devices/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out on all other devices" }));
    expect(await screen.findByRole("status")).toHaveTextContent("The other devices were signed out.");
  });

  it("offers nothing to sign out when this is the only device", async () => {
    server.use(http.get("*/api/v1/sessions", () => HttpResponse.json({ sessions: [LAPTOP] })));
    render(<AppRoot initialPath="/devices" />);
    await screen.findByRole("heading", { level: 2, name: /this device/ });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("has no accessibility violations that axe can detect", async () => {
    server.use(http.get("*/api/v1/sessions", () => HttpResponse.json({ sessions: [LAPTOP, PHONE] })));
    const { container } = render(<AppRoot initialPath="/devices" />);
    await screen.findByRole("heading", { level: 2, name: /this device/ });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});

describe("signing out on this device", () => {
  it("is offered on the home page and shows the sign-in link afterwards", async () => {
    let signedIn = true;
    server.use(
      http.get("*/api/v1/me", () => (signedIn ? HttpResponse.json({ displayName: "Nik", role: "owner" }) : HttpResponse.json({}, { status: 401 }))),
      http.post("*/api/v1/auth/sign-out", () => {
        signedIn = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<AppRoot initialPath="/" />);
    const nav = (await screen.findByRole("link", { name: "Your devices" })).closest("ul") as HTMLElement;
    expect(within(nav).getAllByRole("link")).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });
});
