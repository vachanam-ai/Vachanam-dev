import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlanAndPayment from "../PlanAndPayment.jsx";
import { fetchPlan } from "../../api/client.js";

vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => ({ user: { email: "owner@example.com" } }) }));
vi.mock("../../api/client.js", () => ({
  changePlan: vi.fn(),
  createAutopaySubscription: vi.fn(),
  createWhatsappAddonOrder: vi.fn(),
  fetchPlan: vi.fn(),
  verifyPayment: vi.fn(),
  verifyAutopaySubscription: vi.fn(),
}));

function renderPayment() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PlanAndPayment /></QueryClientProvider>);
}

describe("PlanAndPayment legacy-plan guard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("never quotes retired Lite pricing for a new autopay mandate", async () => {
    fetchPlan.mockResolvedValue({
      plan: "lite", status: "paused", next_base_rupees: 1999,
      autopay_enabled: false, whatsapp_included: false, whatsapp_addon: false,
    });
    renderPayment();
    expect(await screen.findByText(/Lite is a retired plan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enable autopay.*5,999/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Enable autopay.*1,999/i })).not.toBeInTheDocument();
  });
});
