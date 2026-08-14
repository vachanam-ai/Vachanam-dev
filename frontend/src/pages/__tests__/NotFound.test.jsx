import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Vinay 2026-08-14. The catch-all route used to <Navigate> an unknown URL to
// the dashboard, so a dead or mistyped link looked like it had worked — the
// user landed on a real page and assumed that was the destination. A stale
// bookmarked link was indistinguishable from a working one.

const mockAuth = vi.fn(() => ({ user: null, role: null }));

vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => mockAuth(),
  roleHome: () => "/queue",
}));

afterEach(cleanup);

function renderAt(path) {
  return import("../NotFound.jsx").then(({ default: NotFound }) =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </MemoryRouter>,
    ),
  );
}

describe("404 page", () => {
  it("says the page does not exist", async () => {
    await renderAt("/nonsense");
    expect(screen.getByText("404")).toBeTruthy();
    expect(screen.getByText(/doesn't exist/i)).toBeTruthy();
  });

  it("reassures that the clinic account is fine", async () => {
    // A clinic owner hitting a dead link should not think their data is gone.
    await renderAt("/nonsense");
    expect(screen.getByText(/Nothing has\s+gone wrong/i)).toBeTruthy();
  });

  it("offers home and the help centre", async () => {
    await renderAt("/nonsense");
    expect(screen.getByRole("link", { name: /Back to home/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Help centre/i })).toBeTruthy();
  });

  it("sends a signed-in user to their own role's home", async () => {
    mockAuth.mockReturnValueOnce({ user: { user_id: "u" }, role: "receptionist" });
    await renderAt("/nonsense");
    const back = screen.getByRole("link", { name: /Back to your dashboard/i });
    expect(back.getAttribute("href")).toBe("/queue");
  });
});

describe("routing", () => {
  const APP = readFileSync(resolve(process.cwd(), "src/App.jsx"), "utf-8");

  it("renders NotFound on the catch-all instead of redirecting", () => {
    expect(APP).toMatch(/path="\*" element=\{<NotFound \/>\}/);
    // The old behaviour, specifically: it must not come back.
    expect(APP).not.toMatch(/path="\*" element=\{<Navigate/);
  });
});

describe("legal links", () => {
  const LANDING = readFileSync(resolve(process.cwd(), "src/pages/Landing.jsx"), "utf-8");

  it("links the refund policy Razorpay requires", () => {
    // /refunds existed on the backend since launch but nothing linked to it,
    // which for a payment gateway is the same as not publishing it.
    expect(LANDING).toContain("/refunds");
  });

  it("still links privacy and terms", () => {
    expect(LANDING).toContain("/privacy");
    expect(LANDING).toContain("/terms");
  });
});
