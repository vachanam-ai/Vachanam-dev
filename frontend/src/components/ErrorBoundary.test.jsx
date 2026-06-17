import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary.jsx";

// A child that throws during render — the exact failure mode the boundary exists
// to catch (FIXLOG #138: an uncaught render throw used to white-screen the app).
function Boom() {
  throw new Error("kaboom");
}

afterEach(cleanup);

describe("ErrorBoundary", () => {
  it("renders children normally when nothing throws", () => {
    render(
      <ErrorBoundary>
        <div>healthy content</div>
      </ErrorBoundary>
    );
    expect(screen.getByText("healthy content")).toBeInTheDocument();
  });

  it("shows the friendly fallback — never a stack trace — when a child throws", () => {
    // React logs the caught error to console.error; silence it so the test
    // output stays clean (the boundary's own console.error is also covered).
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );

    // User sees the calm card, not a white screen and not the raw error.
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
    // The thrown message must NOT be rendered to the user.
    expect(screen.queryByText(/kaboom/)).not.toBeInTheDocument();
    // The boundary logged the real error somewhere developers can see it.
    expect(spy).toHaveBeenCalled();

    spy.mockRestore();
  });

  it("reload button is wired (calls window.location.reload)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    // jsdom's location.reload is non-configurable in some versions — redefine it.
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload },
      writable: true,
    });

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByRole("button", { name: /reload/i }));
    expect(reload).toHaveBeenCalled();

    spy.mockRestore();
  });
});
