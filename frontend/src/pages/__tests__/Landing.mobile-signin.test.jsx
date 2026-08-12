import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Vinay 2026-08-12: "mobile version of our websites landing page doesn't have
// login button". Two rules combined into a dead end: `.marketing-nav-links`
// is hidden from 900px down (that block holds How it works / Pricing / Help),
// and below 640px `.marketing-signin` was hidden as well. A phone visitor
// therefore had no route to /login anywhere on the landing page — the only
// remaining nav action was "Book a demo".
//
// jsdom does not evaluate media queries, so a render test cannot see this.
// The stylesheet text is the thing that broke, so the stylesheet text is what
// this guards.

const CSS = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8");
const LANDING = readFileSync(resolve(process.cwd(), "src/pages/Landing.jsx"), "utf-8");

/** Every `selector { ... }` block whose selector list mentions the class. */
function blocksMentioning(css, className) {
  const found = [];
  const re = new RegExp(`([^{}]*\\b${className}\\b[^{}]*)\\{([^}]*)\\}`, "g");
  let m;
  while ((m = re.exec(css)) !== null) {
    found.push({ selector: m[1].trim(), body: m[2].trim() });
  }
  return found;
}

describe("landing page sign-in on mobile", () => {
  it("keeps a link to /login in the nav actions", () => {
    expect(LANDING).toMatch(/to="\/login"[^>]*className="marketing-signin"/);
  });

  it("never hides .marketing-signin at any breakpoint", () => {
    const hiding = blocksMentioning(CSS, "marketing-signin").filter((b) =>
      /display\s*:\s*none/.test(b.body),
    );
    expect(
      hiding.map((b) => `${b.selector} { ${b.body} }`),
      "the landing page's only route to /login on a phone",
    ).toEqual([]);
  });

  it("still hides the nav links on mobile, which is why sign-in must stay", () => {
    // If this ever stops being true the rule above can be revisited — until
    // then, .marketing-signin is load-bearing.
    const hidden = blocksMentioning(CSS, "marketing-nav-links").some((b) =>
      /display\s*:\s*none/.test(b.body),
    );
    expect(hidden).toBe(true);
  });

  it("detects the bug it was written for", () => {
    const broken = CSS.replace(
      ".marketing-brand small { display: none; }",
      ".marketing-brand small, .marketing-signin { display: none; }",
    );
    expect(broken).not.toBe(CSS); // the anchor still exists
    const hiding = blocksMentioning(broken, "marketing-signin").filter((b) =>
      /display\s*:\s*none/.test(b.body),
    );
    expect(hiding.length).toBe(1);
  });
});
