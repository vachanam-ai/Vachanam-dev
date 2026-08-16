import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const fetchWaConnection = vi.fn();
const fetchWaChats = vi.fn();
const fetchWaChat = vi.fn();

vi.mock("../../api/client.js", () => ({
  fetchWaConnection: (...args) => fetchWaConnection(...args),
  fetchWaChats: (...args) => fetchWaChats(...args),
  fetchWaChat: (...args) => fetchWaChat(...args),
}));
vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => ({ branchId: "b1", role: "org_admin" }),
}));

import { WhatsAppChatsLive as WhatsAppChats } from "../WhatsAppChats.jsx";

beforeEach(() => {
  fetchWaConnection.mockResolvedValue({ connected: false, wa_status: "disconnected" });
  fetchWaChats.mockResolvedValue([]);
  fetchWaChat.mockResolvedValue({ phone_last4: "7554", turns: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage({ cachedChats = [] } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["wa-chats", "b1"], cachedChats);
  return render(
    <QueryClientProvider client={client}>
      <WhatsAppChats />
    </QueryClientProvider>,
  );
}

describe("WhatsApp chats connection boundary", () => {
  it("never mounts cached patient text after WhatsApp is disconnected", async () => {
    renderPage({
      cachedChats: [{
        phone: "+919812347554",
        phone_last4: "7554",
        last_role: "bot",
        last_text: "private appointment conversation",
      }],
    });

    expect(await screen.findByTestId("wa-chats-disconnected")).toBeInTheDocument();
    expect(screen.queryByText(/private appointment conversation/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/7554/)).not.toBeInTheDocument();
    expect(fetchWaChats).not.toHaveBeenCalled();
  });

  it("loads conversations only after the server confirms the connection", async () => {
    fetchWaConnection.mockResolvedValue({ connected: true, wa_status: "connected" });
    fetchWaChats.mockResolvedValue([{
      phone: "+919812347554",
      phone_last4: "7554",
      last_role: "patient",
      last_text: "Is the doctor available?",
    }]);
    renderPage();

    await waitFor(() => expect(fetchWaChats).toHaveBeenCalledWith("b1"));
    expect(await screen.findByText("Is the doctor available?")).toBeInTheDocument();
  });
});
