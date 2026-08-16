import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mocks = vi.hoisted(() => ({
  fetchConnection: vi.fn(() => Promise.resolve({ connected: false })),
  fetchConfig: vi.fn(() => Promise.resolve({
    configured: true,
    app_id: "app-1",
    config_id: "config-v4",
    graph_version: "v25.0",
    feature_type: "whatsapp_business_app_onboarding",
  })),
  connect: vi.fn(() => Promise.resolve({ connected: true })),
  disconnect: vi.fn(),
  confirmPayment: vi.fn(() => Promise.resolve({ payment_status: "confirmed" })),
  retrySync: vi.fn(() => Promise.resolve({})),
  launch: vi.fn(() => Promise.resolve({
    code: "short-lived-code",
    waba_id: "waba-1",
    phone_number_id: "phone-1",
    business_id: "business-1",
    flow_event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
  })),
}));

vi.mock("../../api/client.js", () => ({
  fetchWaConnection: (...a) => mocks.fetchConnection(...a),
  fetchWaSignupConfig: (...a) => mocks.fetchConfig(...a),
  connectWa: (...a) => mocks.connect(...a),
  disconnectWa: (...a) => mocks.disconnect(...a),
  confirmWaPayment: (...a) => mocks.confirmPayment(...a),
  retryWaSync: (...a) => mocks.retrySync(...a),
}));
vi.mock("../../hooks/useEmbeddedSignup.js", () => ({
  default: () => ({ launch: mocks.launch, launching: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import WaConnectCard from "../WaConnectCard.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mocks.fetchConnection.mockResolvedValue({ connected: false });
  mocks.fetchConfig.mockResolvedValue({
    configured: true,
    app_id: "app-1",
    config_id: "config-v4",
    graph_version: "v25.0",
    feature_type: "whatsapp_business_app_onboarding",
  });
  mocks.launch.mockResolvedValue({
    code: "short-lived-code",
    waba_id: "waba-1",
    phone_number_id: "phone-1",
    business_id: "business-1",
    flow_event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
  });
});

function renderCard(qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  render(
    <QueryClientProvider client={qc}>
      <WaConnectCard branchId="b1" />
    </QueryClientProvider>,
  );
  return qc;
}

describe("WaConnectCard official Embedded Signup v4", () => {
  it("passes the v4 Coexistence configuration and completion payload server-side", async () => {
    renderCard();
    fireEvent.click(await screen.findByTestId("wa-connect-button"));
    await waitFor(() => expect(mocks.launch).toHaveBeenCalledWith({
      appId: "app-1",
      configId: "config-v4",
      graphVersion: "v25.0",
      featureType: "whatsapp_business_app_onboarding",
    }));
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledWith("b1", expect.objectContaining({
      code: "short-lived-code",
      flow_event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    })));
  });

  it("omits the Coexistence feature flag for a new Cloud API number", async () => {
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /new cloud api number/i }));
    await waitFor(() => expect(mocks.launch).toHaveBeenCalledWith(expect.objectContaining({
      featureType: undefined,
    })));
  });

  it("has no client-side token or asset-ID paste fallback", async () => {
    renderCard();
    await screen.findByTestId("wa-connect-button");
    expect(screen.queryByText(/access token/i)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("blocks a doomed popup when server configuration is incomplete", async () => {
    mocks.fetchConfig.mockResolvedValueOnce({ configured: false });
    renderCard();
    expect(await screen.findByTestId("wa-connect-button")).toBeDisabled();
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
  });

  it("shows Meta payment handoff and records owner acknowledgement", async () => {
    mocks.fetchConnection.mockResolvedValueOnce({
      connected: true,
      wa_verified_name: "Sunrise Dental",
      onboarding: {
        payment_status: "required",
        payment_method_url: "https://business.facebook.com/wa/manage/home/",
      },
    });
    renderCard();
    expect(await screen.findByRole("link", { name: /open whatsapp manager/i }))
      .toHaveAttribute("href", "https://business.facebook.com/wa/manage/home/");
    fireEvent.click(screen.getByRole("button", { name: /i added the payment method/i }));
    await waitFor(() => expect(mocks.confirmPayment).toHaveBeenCalledWith("b1"));
  });

  it("exposes a retry when either one-shot Coexistence sync fails", async () => {
    mocks.fetchConnection.mockResolvedValueOnce({
      connected: true,
      onboarding: {
        payment_status: "confirmed",
        mode: "coexistence",
        sync: { contacts: { status: "error" }, history: { status: "requested" } },
      },
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /retry synchronization/i }));
    await waitFor(() => expect(mocks.retrySync).toHaveBeenCalledWith("b1"));
  });

  it("requires Meta reauthorization when the business token expires", async () => {
    mocks.fetchConnection.mockResolvedValueOnce({
      connected: true,
      onboarding: {
        payment_status: "confirmed", mode: "coexistence",
        token_expires_at: "2020-01-01T00:00:00+00:00",
      },
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /reconnect with meta/i }));
    await waitFor(() => expect(mocks.launch).toHaveBeenCalledWith(expect.objectContaining({
      featureType: "whatsapp_business_app_onboarding",
    })));
  });

  it("erases cached patient chats synchronously when disconnected", async () => {
    mocks.fetchConnection.mockResolvedValueOnce({
      connected: true,
      wa_verified_name: "Sunrise Dental",
      onboarding: { payment_status: "confirmed" },
    });
    mocks.disconnect.mockResolvedValueOnce({
      connected: false, wa_status: "disconnected", conversations_deleted: 2,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["wa-chats", "b1"], [{ last_text: "private chat" }]);
    qc.setQueryData(["wa-chat", "b1", "+919812345678"], { turns: [{ text: "private chat" }] });

    renderCard(qc);
    fireEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledWith("b1"));
    expect(qc.getQueryData(["wa-chats", "b1"])).toBeUndefined();
    expect(qc.getQueryData(["wa-chat", "b1", "+919812345678"])).toBeUndefined();
  });
});
