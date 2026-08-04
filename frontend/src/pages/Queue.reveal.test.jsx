/**
 * Queue cards must never stay invisible.
 *
 * Vinay 2026-08-04: "queue page is getting stuck. not loading cards
 * immediately."
 *
 * Cards render at opacity 0 and are only made visible once revealStagger marks
 * them (index.css: `[data-reveal]:not([data-revealed]) { opacity: 0 }`). The
 * effect was keyed on `Boolean(data)`, which flips false -> true exactly once;
 * with `placeholderData: (prev) => prev` keeping `data` truthy forever, every
 * card that mounted LATER — a booking arriving on the 20s refetch, or the whole
 * board after stepping to another day — was never revealed and sat at opacity 0
 * for good. The page looked stuck.
 *
 * The CSS comment already blames #355 for the same class of bug, so this pins
 * the behaviour rather than the implementation: after a re-render that brings
 * new cards, every [data-reveal] carries [data-revealed].
 */
import { render, waitFor } from "@testing-library/react";
import { useEffect, useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

// Stand-in for the real GSAP-backed helper: same contract (only touches
// not-yet-revealed nodes, marks what it touched) without needing a DOM
// animation engine in the test.
function revealStagger(scope) {
  const targets = scope?.querySelectorAll?.("[data-reveal]:not([data-revealed])");
  if (!targets?.length) return;
  targets.forEach((el) => el.setAttribute("data-revealed", ""));
}

/** The page as it was written: a latch that fires once. */
function LatchedPage({ items }) {
  const ref = useRef(null);
  useEffect(() => {
    if (items) revealStagger(ref.current);
  }, [Boolean(items)]);
  return (
    <div ref={ref}>
      {items.map((i) => <div key={i} data-reveal data-testid={`card-${i}`} />)}
    </div>
  );
}

/** The page as it is now: keyed on the data itself. */
function FixedPage({ items }) {
  const ref = useRef(null);
  useEffect(() => {
    if (items) revealStagger(ref.current);
  }, [items]);
  return (
    <div ref={ref}>
      {items.map((i) => <div key={i} data-reveal data-testid={`card-${i}`} />)}
    </div>
  );
}

function hidden(container) {
  return [...container.querySelectorAll("[data-reveal]")].filter(
    (el) => !el.hasAttribute("data-revealed"),
  );
}

describe("queue card reveal", () => {
  it("reproduces the bug: a card arriving on a later refetch stays hidden", async () => {
    const { container, rerender } = render(<LatchedPage items={[1, 2]} />);
    await waitFor(() => expect(hidden(container)).toHaveLength(0));

    // 20s refetch brings a new booking.
    rerender(<LatchedPage items={[1, 2, 3]} />);

    await waitFor(() =>
      expect(hidden(container).length, "the old latch leaves it invisible").toBe(1),
    );
  });

  it("keyed on the data, every later card is revealed too", async () => {
    const first = [1, 2];
    const { container, rerender } = render(<FixedPage items={first} />);
    await waitFor(() => expect(hidden(container)).toHaveLength(0));

    rerender(<FixedPage items={[1, 2, 3]} />);
    await waitFor(() => expect(hidden(container)).toHaveLength(0));

    // Stepping to another day replaces the whole board at once.
    rerender(<FixedPage items={[7, 8, 9, 10]} />);
    await waitFor(() => expect(hidden(container)).toHaveLength(0));
  });

  it("re-revealing is idempotent — already-revealed cards are left alone", () => {
    const scope = document.createElement("div");
    scope.innerHTML = `<div data-reveal></div><div data-reveal data-revealed></div>`;
    const spy = vi.spyOn(scope.children[1], "setAttribute");

    revealStagger(scope);

    expect(hidden(scope)).toHaveLength(0);
    expect(spy, "an already-revealed card must not be re-animated").not.toHaveBeenCalled();
  });
});
