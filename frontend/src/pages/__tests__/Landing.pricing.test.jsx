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
    expect(screen.getByText(/first 500 voice minutes free/i)).toHaveTextContent("12 places left");
    expect(screen.getByRole("link", { name: /start with voice/i })).toHaveAttribute("href", "/register?plan=solo");
  });

  it("calculates the standard monthly voice bill without hiding the line items", () => {
    renderPricing();
    const slider = screen.getByRole("slider", { name: /estimated voice minutes/i });

    expect(slider).toHaveValue("300");
    expect(screen.getByText("₹3,799")).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "500" } });

    expect(slider).toHaveValue("500");
    expect(screen.getByText("500 min × ₹6")).toBeInTheDocument();
    expect(screen.getByText("₹4,999")).toBeInTheDocument();
  });

  it("keeps the WhatsApp add-on distinct from the standalone plan", () => {
    renderPricing();

    expect(screen.getByRole("heading", { name: "WhatsApp add-on" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "WhatsApp only" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /choose whatsapp/i })).toHaveAttribute("href", "/register?plan=wa");
    expect(screen.getByText(/meta message fees are paid directly by the clinic/i)).toBeInTheDocument();
  });
});
