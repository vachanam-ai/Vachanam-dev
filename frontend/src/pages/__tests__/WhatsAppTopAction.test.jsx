import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// Vinay 2026-08-09: "add +template button in place of + walk-in when we open
// whatsapp page". The top-bar action is global chrome, so it followed the
// owner onto the templates screen and offered an unrelated destination.

const fetchWaTemplates = vi.fn(() => Promise.resolve([]));
const fetchBranchSettings = vi.fn(() =>
  Promise.resolve({ name: "Venkateshwara Clinic", whatsapp_status: "connected" }),
);
const fetchWaConnection = vi.fn(() => Promise.resolve({ connected: true }));

vi.mock("../../api/client.js", () => ({
  fetchWaTemplates: (...a) => fetchWaTemplates(...a),
  fetchBranchSettings: (...a) => fetchBranchSettings(...a),
  fetchWaConnection: (...a) => fetchWaConnection(...a),
  fetchWaSignupConfig: () => Promise.resolve({ configured: false }),
  createWaTemplate: vi.fn(),
  deleteWaTemplate: vi.fn(),
  installWaSystemTemplates: vi.fn(),
  connectWa: vi.fn(),
  confirmWaPayment: vi.fn(),
  retryWaSync: vi.fn(),
  disconnectWa: vi.fn(),
}));
vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => ({ branchId: "b1", role: "org_admin" }),
}));
vi.mock("../../hooks/useEmbeddedSignup.js", () => ({
  default: () => ({ launch: vi.fn(), launching: false }),
}));

import WhatsApp from "../WhatsApp.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderAt(path) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={qc}>
        <Routes>
          <Route path="/whatsapp" element={<WhatsApp />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("WhatsApp templates — ?new=1 opens the editor", () => {
  it("opens the editor when the top-bar action lands with ?new=1", async () => {
    renderAt("/whatsapp?new=1");
    expect(await screen.findByLabelText(/message body/i)).toBeInTheDocument();
  });

  it("stays closed on a plain visit", async () => {
    renderAt("/whatsapp");
    await screen.findByText(/Press/i);
    expect(screen.queryByLabelText(/message body/i)).toBeNull();
  });

  it("clears the param on cancel, so a refresh doesn't reopen it", async () => {
    renderAt("/whatsapp?new=1");
    await screen.findByLabelText(/message body/i);
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(screen.queryByLabelText(/message body/i)).toBeNull();
  });
});
