import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Manual connect (Vinay, 2026-08-09: "need a way to add number directly from
// clinic page"). Embedded Signup can't run until the Meta app is published
// Live, so until then the popup button is a dead end and the only path was a
// super_admin curl.

const fetchWaConnection = vi.fn(() => Promise.resolve({ connected: false }));
const fetchWaSignupConfig = vi.fn(() => Promise.resolve({ configured: false }));
const connectWa = vi.fn();
const connectWaManual = vi.fn(() => Promise.resolve({ wa_status: "connected" }));
const disconnectWa = vi.fn();

vi.mock("../../api/client.js", () => ({
  fetchWaConnection: (...a) => fetchWaConnection(...a),
  fetchWaSignupConfig: (...a) => fetchWaSignupConfig(...a),
  connectWa: (...a) => connectWa(...a),
  connectWaManual: (...a) => connectWaManual(...a),
  disconnectWa: (...a) => disconnectWa(...a),
}));
vi.mock("../../hooks/useEmbeddedSignup.js", () => ({
  default: () => ({ launch: vi.fn(), launching: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import WaConnectCard from "../WaConnectCard.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WaConnectCard branchId="b1" />
    </QueryClientProvider>,
  );
}

const VALID = {
  waba_id: "555000111",
  phone_number_id: "555000222",
  access_token: "EAAG" + "x".repeat(40),
};

async function openForm() {
  renderCard();
  fireEvent.click(await screen.findByTestId("wa-manual-toggle"));
  return {
    waba: screen.getByTestId("wa-manual-waba"),
    phone: screen.getByTestId("wa-manual-phone"),
    token: screen.getByTestId("wa-manual-token"),
    submit: screen.getByTestId("wa-manual-submit"),
  };
}

function fill(f, values) {
  fireEvent.change(f.waba, { target: { value: values.waba_id } });
  fireEvent.change(f.phone, { target: { value: values.phone_number_id } });
  fireEvent.change(f.token, { target: { value: values.access_token } });
}

describe("WaConnectCard — manual connect", () => {
  it("posts the three ids the clinic pasted", async () => {
    const f = await openForm();
    fill(f, VALID);
    fireEvent.click(f.submit);
    await waitFor(() => expect(connectWaManual).toHaveBeenCalledWith("b1", VALID));
  });

  it("offers the manual path even when Embedded Signup is unconfigured", async () => {
    // The whole reason it exists: with configured:false the popup button is
    // disabled, so without this the card would have no working action at all.
    renderCard();
    expect(await screen.findByTestId("wa-connect-button")).toBeDisabled();
    expect(screen.getByTestId("wa-manual-toggle")).toBeEnabled();
  });

  it("keeps submit disabled until all three fields are usable", async () => {
    const f = await openForm();
    expect(f.submit).toBeDisabled();

    fill(f, { ...VALID, waba_id: "not-numeric" });
    expect(f.submit).toBeDisabled();

    fill(f, { ...VALID, access_token: "short" });
    expect(f.submit).toBeDisabled();

    fill(f, VALID);
    expect(f.submit).toBeEnabled();
  });

  it("names the mistake when the phone NUMBER is pasted into the ID field", async () => {
    // What actually happened: Meta shows "+1 555 665 9281" in large type with
    // the ID in small text under it. A silently disabled button told him
    // nothing.
    const f = await openForm();
    fireEvent.change(f.phone, { target: { value: "+1 (555) 665-9281" } });
    expect(screen.getByTestId("wa-manual-phone-note").textContent)
      .toMatch(/phone number, not its ID/i);
    expect(f.submit).toBeDisabled();

    fireEvent.change(f.phone, { target: { value: "555000222" } });
    expect(screen.getByTestId("wa-manual-phone-note").textContent)
      .not.toMatch(/not its ID/i);
  });

  it("shows a hint, not an error, on an untouched field", async () => {
    const f = await openForm();
    expect(screen.getByTestId("wa-manual-waba-note").className).not.toMatch(/danger/);
    expect(screen.queryByTestId("wa-manual-token-note")).toBeNull();
    fireEvent.change(f.token, { target: { value: "short" } });
    expect(screen.getByTestId("wa-manual-token-note").textContent).toMatch(/too short/i);
  });

  it("never renders the token in readable text", async () => {
    const f = await openForm();
    fill(f, VALID);
    // The one place the token exists in the browser — a screen share or a
    // support call must not expose it.
    expect(f.token).toHaveAttribute("type", "password");
    expect(document.body.textContent).not.toContain(VALID.access_token);
  });

  it("shows the server's reason when the connect is refused", async () => {
    const { toast } = await import("sonner");
    connectWaManual.mockRejectedValueOnce({
      response: { data: { detail: "This WhatsApp Business Account is already connected to another clinic." } },
    });
    const f = await openForm();
    fill(f, VALID);
    fireEvent.click(f.submit);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This WhatsApp Business Account is already connected to another clinic.",
      ),
    );
  });

  it("hides the manual form once the branch is connected", async () => {
    fetchWaConnection.mockResolvedValueOnce({ connected: true, wa_verified_name: "Sunrise Dental" });
    renderCard();
    await screen.findByTestId("wa-connected");
    expect(screen.queryByTestId("wa-manual-toggle")).toBeNull();
  });
});
