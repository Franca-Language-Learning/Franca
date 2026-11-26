import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoot } from "../../AppRoot";
import { server } from "../../mocks/server";
import { installFakeWebAuthn, removeFakeWebAuthn } from "../../mocks/webauthn";
import { fromBase64url, toBase64url } from "./webauthn";

const PHONE = { id: "cGhvbmU", label: "Phone", createdAt: "2026-12-01T09:00:00.000Z", lastUsedAt: null, synced: true };
const OPTIONS = {
  publicKey: {
    rp: { id: "localhost", name: "Franca" },
    user: { id: "dXNlcg", name: "Nik", displayName: "Nik" },
    challenge: "Y2hhbGxlbmdl",
    pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    excludeCredentials: [{ id: "cGhvbmU", type: "public-key" }],
  },
};

describe("base64url", () => {
  it("turns text into bytes and back", () => {
    for (const text of ["", "YQ", "YWI", "YWJj", "-_8"]) expect(toBase64url(fromBase64url(text))).toBe(text);
  });
});

describe("passkeys page", () => {
  let fake: ReturnType<typeof installFakeWebAuthn>;
  beforeEach(() => {
    fake = installFakeWebAuthn();
  });
  afterEach(() => removeFakeWebAuthn());

  it("lists the learner's passkeys", async () => {
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [PHONE] })));
    render(<AppRoot initialPath="/passkeys" />);
    const item = (await screen.findByRole("heading", { level: 3, name: "Phone" })).closest("li") as HTMLElement;
    expect(item).toHaveTextContent("Added on 1 Dec 2026. Not used yet.");
    expect(item).toHaveTextContent("also available on your other devices");
  });

  it("says so when there are no passkeys", async () => {
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [] })));
    render(<AppRoot initialPath="/passkeys" />);
    expect(await screen.findByText("You have no passkeys yet.")).toBeInTheDocument();
  });

  it("adds a passkey made on this device, with the name the learner typed", async () => {
    let sent: { credential: Record<string, unknown>; label: string | null } | undefined;
    server.use(
      http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [] })),
      http.post("*/api/v1/passkeys/options", () => HttpResponse.json(OPTIONS)),
      http.post("*/api/v1/passkeys", async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return HttpResponse.json(PHONE, { status: 201 });
      }),
    );
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.type(await screen.findByLabelText(/Name for the passkey/), "Phone");
    await userEvent.click(screen.getByRole("button", { name: "Add a passkey" }));

    expect(await screen.findByText("The passkey was added.")).toBeInTheDocument();
    const publicKey = fake.create.mock.calls[0]?.[0].publicKey as PublicKeyCredentialCreationOptions;
    expect(toBase64url(publicKey.challenge as ArrayBuffer)).toBe("Y2hhbGxlbmdl");
    expect(toBase64url(publicKey.user.id as ArrayBuffer)).toBe("dXNlcg");
    expect(toBase64url(publicKey.excludeCredentials?.[0]?.id as ArrayBuffer)).toBe("cGhvbmU");
    expect(sent?.label).toBe("Phone");
    expect(sent?.credential).toMatchObject({
      id: "cred-1",
      type: "public-key",
      response: { clientDataJSON: toBase64url(new TextEncoder().encode("client-data").buffer), transports: ["internal"] },
    });
  });

  it("asks for a new sign-in when the last one was more than 15 minutes ago", async () => {
    server.use(
      http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [] })),
      http.post("*/api/v1/passkeys/options", () => HttpResponse.json({ detail: "sign-in-again" }, { status: 403 })),
    );
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You signed in more than 15 minutes ago");
    expect(within(alert).getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/sign-in");
  });

  it("explains a passkey window that was closed", async () => {
    fake.create.mockRejectedValueOnce(new DOMException("closed", "NotAllowedError"));
    server.use(
      http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [] })),
      http.post("*/api/v1/passkeys/options", () => HttpResponse.json(OPTIONS)),
    );
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No passkey was added, because");
  });

  it("explains that this device has a passkey already", async () => {
    fake.create.mockRejectedValueOnce(new DOMException("exists", "InvalidStateError"));
    server.use(
      http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [PHONE] })),
      http.post("*/api/v1/passkeys/options", () => HttpResponse.json(OPTIONS)),
    );
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("There is already a passkey for your account on this device.");
  });

  it("removes a passkey after the learner confirms", async () => {
    let removed = "";
    let list = [PHONE];
    server.use(
      http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: list })),
      http.delete("*/api/v1/passkeys/:id", ({ params }) => {
        removed = String(params.id);
        list = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Phone" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove Phone" }));

    expect(await screen.findByText("You have no passkeys yet.")).toBeInTheDocument();
    expect(removed).toBe("cGhvbmU");
  });

  it("keeps the passkey when the learner changes their mind", async () => {
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [PHONE] })));
    render(<AppRoot initialPath="/passkeys" />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Phone" }));
    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.getByRole("button", { name: "Remove Phone" })).toBeInTheDocument();
  });

  it("sends someone who is not signed in to the sign-in page", async () => {
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ detail: "Not signed in" }, { status: 401 })));
    render(<AppRoot initialPath="/passkeys" />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });

  it("says so in a browser without passkeys", async () => {
    removeFakeWebAuthn();
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [] })));
    render(<AppRoot initialPath="/passkeys" />);
    expect(await screen.findByText(/This browser does not support passkeys/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a passkey" })).toBeNull();
  });

  it("has no accessibility violations that axe can detect", async () => {
    server.use(http.get("*/api/v1/passkeys", () => HttpResponse.json({ passkeys: [PHONE] })));
    const { container } = render(<AppRoot initialPath="/passkeys" />);
    await screen.findByRole("heading", { level: 3, name: "Phone" });
    await userEvent.click(within(container).getByRole("button", { name: "Remove Phone" }));
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});

describe("signing in with a passkey", () => {
  let fake: ReturnType<typeof installFakeWebAuthn>;
  beforeEach(() => {
    fake = installFakeWebAuthn();
  });
  afterEach(() => removeFakeWebAuthn());

  const signInOptions = { publicKey: { challenge: "Y2hhbGxlbmdl", rpId: "localhost", allowCredentials: [], userVerification: "preferred" } };

  it("signs in and goes to the home page", async () => {
    let sent: Record<string, unknown> | undefined;
    server.use(
      http.post("*/api/v1/auth/passkey/options", () => HttpResponse.json(signInOptions)),
      http.post("*/api/v1/auth/passkey", async ({ request }) => {
        sent = ((await request.json()) as { credential: Record<string, unknown> }).credential;
        return HttpResponse.json({ displayName: "Nik", role: "owner" });
      }),
      http.get("*/api/v1/me", () => HttpResponse.json({ displayName: "Nik", role: "owner" })),
    );
    render(<AppRoot initialPath="/sign-in" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));

    expect(await screen.findByText("You are signed in as Nik.")).toBeInTheDocument();
    expect(toBase64url(fake.get.mock.calls[0]?.[0].publicKey?.challenge as ArrayBuffer)).toBe("Y2hhbGxlbmdl");
    expect(sent).toMatchObject({ id: "cred-1", response: { userHandle: toBase64url(new TextEncoder().encode("user").buffer) } });
  });

  it.each([
    [{ detail: "passkey-unknown" }, 401, "This passkey is not linked to a Franca account."],
    [{ detail: "passkey-not-accepted" }, 401, "This passkey was not accepted."],
    [{ detail: "disabled" }, 401, "Your account is switched off."],
    [{ detail: "no-passkey-options" }, 400, "Signing in with a passkey did not work."],
  ])("explains a refusal (%j)", async (body, status, message) => {
    server.use(
      http.post("*/api/v1/auth/passkey/options", () => HttpResponse.json(signInOptions)),
      http.post("*/api/v1/auth/passkey", () => HttpResponse.json(body, { status })),
    );
    render(<AppRoot initialPath="/sign-in" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("asks the device to stop offering a passkey that Franca does not have", async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    vi.stubGlobal("PublicKeyCredential", Object.assign(function PublicKeyCredential() {}, { signalUnknownCredential }));
    server.use(
      http.post("*/api/v1/auth/passkey/options", () => HttpResponse.json(signInOptions)),
      http.post("*/api/v1/auth/passkey", () => HttpResponse.json({ detail: "passkey-unknown" }, { status: 401 })),
    );
    render(<AppRoot initialPath="/sign-in" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));
    await screen.findByRole("alert");
    expect(signalUnknownCredential).toHaveBeenCalledWith({ rpId: "localhost", credentialId: "cred-1" });
  });

  it("explains a passkey window that was closed", async () => {
    fake.get.mockRejectedValueOnce(new DOMException("closed", "NotAllowedError"));
    server.use(http.post("*/api/v1/auth/passkey/options", () => HttpResponse.json(signInOptions)));
    render(<AppRoot initialPath="/sign-in" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You are not signed in, because the passkey window was closed");
  });

  it("is not offered in a browser without passkeys", async () => {
    removeFakeWebAuthn();
    render(<AppRoot initialPath="/sign-in" />);
    await screen.findByRole("heading", { level: 1, name: "Sign in to Franca" });
    expect(screen.queryByRole("button", { name: "Sign in with a passkey" })).toBeNull();
  });
});
