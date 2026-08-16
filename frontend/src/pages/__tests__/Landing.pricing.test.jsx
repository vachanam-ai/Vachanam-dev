import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@gsap/react", () => ({ useGSAP: vi.fn() }));
vi.mock("gsap", () => ({ default: { registerPlugin: vi.fn() } }));
vi.mock("gsap/ScrollTrigger", () => ({ ScrollTrigger: {} }));

import { PricingSection } from "../Landing.jsx";

function renderPricing(props = {}) {
  return render(
    <MemoryRouter>
      <PricingSection {...props} />
    </MemoryRouter>,
  );
}

describe("landing pricing", () => {
  it("presents the fixed fee and metered voice price as one offer", () => {
    renderPricing({ foundingOfferOn: true, slotsLeft: 12 });

    expect(screen.getByRole("heading", { name: /one fixed fee/i })).toBeInTheDocument();
    expect(screen.getByLabelText("₹1,999 per month plus ₹6 per voice minute")).toBeInTheDocument();
    expect(screen.getByText(/no voice-minute cap/i)).toHaveTextContent("12 of the first 100 places remain");
    expect(screen.getByRole("link", { name: /start 14 days free/i })).toHaveAttribute("href", "/register?plan=solo");
  });

  it("calculates the standard monthly voice bill without hiding the line items", () => {
    renderPricing();
    const slider = screen.getByRole("slider", { name: /estimated voice minutes/i });

    expect(slider).toHaveValue("300");
    expect(slider).toHaveAttribute("max", "5000");
    expect(screen.getByText("₹3,799")).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "500" } });

    expect(slider).toHaveValue("500");
    expect(screen.getByText("500 min × ₹6")).toBeInTheDocument();
    expect(screen.getByText("₹4,999")).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "5000" } });

    expect(slider).toHaveValue("5000");
    expect(screen.getByText("5,000 min × ₹6")).toBeInTheDocument();
    expect(screen.getByText("₹31,999")).toBeInTheDocument();
  });

  it("recommends the Voice add-on bundle without hiding the chat-only tradeoff", () => {
    renderPricing();

    expect(screen.getByRole("heading", { name: "Voice + WhatsApp" })).toBeInTheDocument();
    expect(screen.getByText("₹3,498")).toBeInTheDocument();
    expect(screen.getByText("₹1,999 Voice + ₹1,499 WhatsApp add-on")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /start voice now/i })).toHaveAttribute("href", "/register?plan=solo");
    expect(screen.getByRole("heading", { name: "WhatsApp only" })).toBeInTheDocument();
    expect(screen.getByText("No phone line or call handling")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /choose whatsapp only/i })).not.toBeInTheDocument();
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/meta message fees are paid directly by the clinic/i)).toBeInTheDocument();
  });
});
