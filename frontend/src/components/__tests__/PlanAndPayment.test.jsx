import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlanAndPayment from "../PlanAndPayment.jsx";
import { cancelPlanChange, changePlan, fetchPlan } from "../../api/client.js";

vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => ({ user: { email: "owner@example.com" } }) }));
vi.mock("../../api/client.js", () => ({
  changePlan: vi.fn(),
  cancelPlanChange: vi.fn(),
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
    expect(await screen.findByText(/This is a retired plan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Move to Vachanam Voice/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Enable autopay.*1,999/i })).toBeInTheDocument();
  });

  it("shows both public plans and the current price", async () => {
    fetchPlan.mockResolvedValue({
      plan: "solo", status: "active", next_base_rupees: 1999,
      autopay_enabled: false, whatsapp_included: false, whatsapp_addon: true,
    });
    renderPayment();
    const plan = await screen.findByRole("combobox", { name: /Plan/i });
    expect(plan).toHaveValue("solo");
    expect(screen.getByRole("option", { name: /WhatsApp.*1,999/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Change plan/i })).toBeDisabled();
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("can cancel a scheduled change while the current plan is retired", async () => {
    fetchPlan.mockResolvedValue({
      plan: "lite", pending_plan: "solo", pending_plan_effective: "2026-09-11",
      status: "active", next_base_rupees: 1999, autopay_enabled: false,
      whatsapp_included: false, whatsapp_addon: true,
    });
    cancelPlanChange.mockResolvedValue({
      plan: "lite", pending_plan: null, status: "active", whatsapp_addon: true,
    });
    renderPayment();
    fireEvent.click(await screen.findByRole("button", { name: /Cancel scheduled change/i }));
    await waitFor(() => expect(cancelPlanChange).toHaveBeenCalledTimes(1));
  });
});
