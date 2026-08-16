import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlanAndPayment from "../PlanAndPayment.jsx";
import {
  cancelPlanChange,
  changePlan,
  createAutopaySubscription,
  fetchPlan,
  verifyAutopaySubscription,
} from "../../api/client.js";

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
  beforeEach(() => {
    vi.clearAllMocks();
    delete window.Razorpay;
  });

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

  it("offers Voice only and marks WhatsApp as coming soon", async () => {
    fetchPlan.mockResolvedValue({
      plan: "solo", status: "active", next_base_rupees: 1999,
      autopay_enabled: false, whatsapp_included: false, whatsapp_addon: false,
    });
    renderPayment();
    const plan = await screen.findByRole("combobox", { name: /Plan/i });
    expect(plan).toHaveValue("solo");
    expect(screen.queryByRole("option", { name: /WhatsApp.*1,999/i })).not.toBeInTheDocument();
    expect(await screen.findByText("Coming soon")).toBeInTheDocument();
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

  it("enables a fixed monthly mandate through subscription checkout", async () => {
    fetchPlan.mockResolvedValue({
      plan: "solo", status: "paused", next_base_rupees: 1999,
      autopay_enabled: false, whatsapp_included: false, whatsapp_addon: false,
    });
    createAutopaySubscription.mockResolvedValue({
      subscription_id: "sub_fixed_monthly", key_id: "rzp_test", amount: 199900,
    });
    verifyAutopaySubscription.mockResolvedValue({ verified: true });
    let checkoutOptions;
    window.Razorpay = function Razorpay(options) {
      checkoutOptions = options;
      this.open = () => options.handler({
        razorpay_subscription_id: "sub_fixed_monthly",
        razorpay_payment_id: "pay_authorise",
        razorpay_signature: "signed",
      });
    };

    renderPayment();
    fireEvent.click(await screen.findByRole("button", { name: /Enable autopay.*1,999/i }));

    await waitFor(() => expect(createAutopaySubscription).toHaveBeenCalledWith("solo"));
    expect(checkoutOptions.subscription_id).toBe("sub_fixed_monthly");
    expect(checkoutOptions.order_id).toBeUndefined();
    await waitFor(() => expect(verifyAutopaySubscription).toHaveBeenCalledWith({
      razorpay_subscription_id: "sub_fixed_monthly",
      razorpay_payment_id: "pay_authorise",
      razorpay_signature: "signed",
    }));
  });
});
