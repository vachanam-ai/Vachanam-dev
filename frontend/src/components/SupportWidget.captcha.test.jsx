import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Regression for FIXLOG #413: on the public landing page (no login) the chat
// bubble opened but every message died with 403 "captcha_failed" — the
// anonymous /support/chat requires a Turnstile token and the widget never
// rendered the captcha. Anonymous + TURNSTILE_ON must show the captcha and
// keep Send disabled until it solves; a signed-in user must see no captcha.

let token = null;
vi.mock("../api/client", () => ({ getToken: () => token }));
vi.mock("../api/support", () => ({ sendChat: vi.fn() }));
vi.mock("./Turnstile.jsx", () => ({
  TURNSTILE_ON: true,
  default: ({ onToken }) => (
    <button data-testid="captcha" onClick={() => onToken("tok")}>solve</button>
  ),
}));

import SupportWidget from "./SupportWidget.jsx";

// jsdom has no Element.scrollTo; the widget calls it on every message change
Element.prototype.scrollTo = () => {};

afterEach(cleanup);

function openWidget() {
  render(
    <MemoryRouter>
      <SupportWidget />
    </MemoryRouter>
  );
  fireEvent.click(screen.getByLabelText("Open support chat"));
}

describe("SupportWidget captcha gate (#413)", () => {
  it("anonymous: captcha shown, Send disabled until solved", () => {
    token = null;
    openWidget();
    expect(screen.getByTestId("captcha")).toBeTruthy();
    const input = screen.getByPlaceholderText("Type your question…");
    fireEvent.change(input, { target: { value: "hello" } });
    expect(screen.getByLabelText("Send").disabled).toBe(true);
    fireEvent.click(screen.getByTestId("captcha")); // solves → token set
    expect(screen.getByLabelText("Send").disabled).toBe(false);
  });

  it("signed-in: no captcha, Send enabled with text", () => {
    token = "jwt";
    openWidget();
    expect(screen.queryByTestId("captcha")).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Type your question…"), {
      target: { value: "hello" },
    });
    expect(screen.getByLabelText("Send").disabled).toBe(false);
  });
});
