import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Billing from "../Billing.jsx";
import {
  createVoiceUsageOrder,
  fetchBillingSummary,
  fetchPlan,
  verifyPayment,
} from "../../api/client.js";

vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => ({ user: { email: "owner@example.com" } }),
}));
vi.mock("../../lib/motion.js", () => ({ revealStagger: vi.fn() }));
vi.mock("../../api/client.js", () => ({
  cancelPlanChange: vi.fn(),
  cancelSubscription: vi.fn(),
  changePlan: vi.fn(),
  createAutopaySubscription: vi.fn(),
  createVoiceUsageOrder: vi.fn(),
  createWhatsappAddonOrder: vi.fn(),
  fetchBillingSummary: vi.fn(),
  fetchPlan: vi.fn(),
  verifyAutopaySubscription: vi.fn(),
  verifyPayment: vi.fn(),
}));

const summary = {
  plan: "solo",
  plan_label: "Vachanam Voice",
  next_plan: "solo",
  next_plan_label: "Vachanam Voice",
  status: "active",
  cycle_start: "2026-08-01",
  cycle_end: "2026-09-01",
  has_billed: true,
  included_minutes: 500,
  minutes_used: 540,
  overage_minutes: 40,
  overage_rate: 6,
  overage_amount: 240,
  base_next: 1999,
  whatsapp_addon_amount: 0,
  gst_amount: 0,
  autopay_amount: 1999,
  usage_payment_estimate: 240,
  total_next: 2239,
  autopay_enabled: true,
  outstanding_usage_amount: 240,
  history: [{
    cycle_id: "cycle-one",
    cycle_start: "2026-07-01",
    cycle_end: "2026-08-01",
    plan: "solo",
    base_amount: 1999,
    minutes_used: 540,
    overage_minutes: 40,
    overage_amount: 240,
    usage_payment_amount: 240,
    total: 2239,
    status: "invoiced",
    usage_payment_due: true,
  }],
};

function renderBilling() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}><Billing /></QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("Billing payment rails", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchBillingSummary.mockResolvedValue(summary);
    fetchPlan.mockResolvedValue({
      plan: "solo", status: "active", autopay_enabled: true,
      whatsapp_included: false, whatsapp_addon: false,
    });
    createVoiceUsageOrder.mockResolvedValue({
      order_id: "order_usage", key_id: "rzp_test", amount: 24000, currency: "INR",
    });
    verifyPayment.mockResolvedValue({ verified: true });
  });

  it("does not imply metered usage is part of fixed autopay", async () => {
    renderBilling();
    expect(await screen.findByText("Two charges, clearly separated")).toBeInTheDocument();
    expect(screen.getByText(/Only the monthly platform fee is on autopay today/i)).toBeInTheDocument();
    expect(screen.getAllByText("₹1,999").length).toBeGreaterThan(0);
    expect(screen.getAllByText("₹240").length).toBeGreaterThan(0);
  });

  it("shows unlimited trial usage as free and never billable", async () => {
    fetchBillingSummary.mockResolvedValue({
      ...summary,
      status: "trial",
      has_billed: false,
      trial_unlimited: true,
      trial_ends_at: "2026-08-30T12:00:00Z",
      included_minutes: 0,
      minutes_used: 1250,
      overage_minutes: 0,
      overage_amount: 0,
      outstanding_usage_amount: 0,
      history: [],
    });
    fetchPlan.mockResolvedValue({
      plan: "solo", status: "trial", trial_unlimited: true,
      trial_ends_at: "2026-08-30T12:00:00Z", autopay_enabled: false,
      next_base_rupees: 1999, whatsapp_included: false, whatsapp_addon: false,
    });

    renderBilling();

    expect(await screen.findByText("Every call is free during your trial")).toBeInTheDocument();
    expect(screen.getByText("Free trial minutes")).toBeInTheDocument();
    expect(screen.getAllByText("1,250")).toHaveLength(2);
    expect(screen.getAllByText("₹0").length).toBeGreaterThan(0);
    expect(screen.getByText(/no automatic conversion/i)).toBeInTheDocument();
  });

  it("pays the exact closed-cycle usage order and verifies it", async () => {
    let options;
    window.Razorpay = function Razorpay(value) {
      options = value;
      this.open = () => value.handler({
        razorpay_order_id: "order_usage",
        razorpay_payment_id: "pay_usage",
        razorpay_signature: "signed",
      });
    };
    renderBilling();

    fireEvent.click(await screen.findByRole("button", { name: "Pay ₹240" }));

    await waitFor(() => expect(createVoiceUsageOrder).toHaveBeenCalledWith("cycle-one"));
    expect(options.order_id).toBe("order_usage");
    expect(options.subscription_id).toBeUndefined();
    await waitFor(() => expect(verifyPayment).toHaveBeenCalledWith({
      razorpay_order_id: "order_usage",
      razorpay_payment_id: "pay_usage",
      razorpay_signature: "signed",
    }));
  });
});
