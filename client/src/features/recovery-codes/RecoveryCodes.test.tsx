import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AppRoot } from "../../AppRoot";
import { server } from "../../mocks/server";

const CODES = ["ABCDE-FGHJK", "MNPQR-STUVW", "XYZ23-45678", "9ABCD-EFGHJ", "KMNPQ-RSTUV", "WXYZ2-34567", "89ABC-DEFGH", "JKMNP-QRSTU", "VWXYZ-23456", "789AB-CDEFG"];

describe("recovery codes page", () => {
  it("says how many codes are left", async () => {
    server.use(http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused: 9, createdAt: "2026-12-01T09:00:00.000Z" })));
    render(<AppRoot initialPath="/recovery-codes" />);
    expect(await screen.findByText("You have 9 unused codes, made on 1 Dec 2026.")).toBeInTheDocument();
  });

  it("makes codes at once for a learner who has none, and shows them", async () => {
    let unused = 0;
    server.use(
      http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused, createdAt: unused ? "2026-12-01T09:00:00.000Z" : null })),
      http.post("*/api/v1/recovery-codes", () => {
        unused = 10;
        return HttpResponse.json({ codes: CODES }, { status: 201 });
      }),
    );
    render(<AppRoot initialPath="/recovery-codes" />);
    expect(await screen.findByText("You have no recovery codes yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Make new recovery codes" }));

    const list = await screen.findByRole("list");
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(CODES);
    expect(await screen.findByText(/You have 10 unused codes/)).toBeInTheDocument();
  });

  it("says so when all codes are used", async () => {
    server.use(http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused: 0, createdAt: "2026-12-01T09:00:00.000Z" })));
    render(<AppRoot initialPath="/recovery-codes" />);
    expect(await screen.findByText("You have used all your recovery codes. You can make new ones below.")).toBeInTheDocument();
  });

  it("asks before replacing codes the learner has", async () => {
    let made = false;
    server.use(
      http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused: 4, createdAt: "2026-12-01T09:00:00.000Z" })),
      http.post("*/api/v1/recovery-codes", () => {
        made = true;
        return HttpResponse.json({ codes: CODES }, { status: 201 });
      }),
    );
    render(<AppRoot initialPath="/recovery-codes" />);
    await userEvent.click(await screen.findByRole("button", { name: "Make new recovery codes" }));
    expect(screen.getByText(/the codes you have now will stop working/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep my codes" }));
    expect(made).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Make new recovery codes" }));
    await userEvent.click(screen.getByRole("button", { name: "Make new codes" }));
    expect(await screen.findByRole("heading", { name: "Your new recovery codes" })).toBeInTheDocument();
    expect(made).toBe(true);
  });

  it("asks for a new sign-in when the last one was more than 15 minutes ago", async () => {
    server.use(
      http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused: 0, createdAt: null })),
      http.post("*/api/v1/recovery-codes", () => HttpResponse.json({ detail: "sign-in-again" }, { status: 403 })),
    );
    render(<AppRoot initialPath="/recovery-codes" />);
    await userEvent.click(await screen.findByRole("button", { name: "Make new recovery codes" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/sign-in");
  });

  it("has no accessibility violations that axe can detect", async () => {
    server.use(
      http.get("*/api/v1/recovery-codes", () => HttpResponse.json({ unused: 0, createdAt: null })),
      http.post("*/api/v1/recovery-codes", () => HttpResponse.json({ codes: CODES }, { status: 201 })),
    );
    const { container } = render(<AppRoot initialPath="/recovery-codes" />);
    await userEvent.click(await screen.findByRole("button", { name: "Make new recovery codes" }));
    await screen.findByRole("heading", { name: "Your new recovery codes" });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});

describe("signing in with a recovery code", () => {
  it("is linked from the sign-in page", async () => {
    render(<AppRoot initialPath="/sign-in" />);
    expect(await screen.findByRole("link", { name: "sign in with a recovery code" })).toHaveAttribute("href", "/sign-in/recovery-code");
  });

  it("signs in and goes to the home page", async () => {
    let sent: unknown;
    server.use(
      http.post("*/api/v1/auth/recovery-code", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ displayName: "Nik", role: "owner" });
      }),
      http.get("*/api/v1/me", () => HttpResponse.json({ displayName: "Nik", role: "owner" })),
    );
    render(<AppRoot initialPath="/sign-in/recovery-code" />);
    await userEvent.type(await screen.findByLabelText(/E-mail address/), " nik@example.org ");
    await userEvent.type(screen.getByLabelText(/Recovery code/), "abcde-fghjk");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("You are signed in as Nik.")).toBeInTheDocument();
    expect(sent).toEqual({ email: "nik@example.org", code: "abcde-fghjk" });
  });

  it.each([
    [{ detail: "recovery-code-not-accepted" }, 401, "The e-mail address or the code is not right"],
    [{ detail: "too-many-attempts" }, 429, "Wait 15 minutes"],
    [{ detail: "disabled" }, 401, "Your account is switched off."],
  ])("explains a refusal (%j)", async (body, status, message) => {
    server.use(http.post("*/api/v1/auth/recovery-code", () => HttpResponse.json(body, { status })));
    render(<AppRoot initialPath="/sign-in/recovery-code" />);
    await userEvent.type(await screen.findByLabelText(/E-mail address/), "nik@example.org");
    await userEvent.type(screen.getByLabelText(/Recovery code/), "AAAAA-AAAAA");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("has no accessibility violations that axe can detect", async () => {
    const { container } = render(<AppRoot initialPath="/sign-in/recovery-code" />);
    await screen.findByRole("heading", { level: 1, name: "Sign in with a recovery code" });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
