import gsap from "gsap";

/** Staggered entrance for everything marked [data-reveal] inside `scope`.
 *  One orchestrated load beats scattered micro-motion. */
export function revealStagger(scope) {
  const targets = scope?.querySelectorAll?.("[data-reveal]");
  if (!targets?.length) return;
  gsap.fromTo(
    targets,
    { opacity: 0, y: 14 },
    { opacity: 1, y: 0, duration: 0.55, ease: "power3.out", stagger: 0.07, clearProps: "transform" }
  );
}

/** Count a numeral element up to `value` (Spectral tabular nums hold width). */
export function countUp(el, value, { duration = 0.9, suffix = "" } = {}) {
  if (!el) return;
  const obj = { v: 0 };
  gsap.to(obj, {
    v: value,
    duration,
    ease: "power2.out",
    onUpdate: () => {
      el.textContent = Math.round(obj.v).toString() + suffix;
    }
  });
}

/** Soft press-confirm pulse on a card row after an optimistic action. */
export function pulseRow(el) {
  if (!el) return;
  gsap.fromTo(
    el,
    { backgroundColor: "rgba(224,242,241,0.9)" },
    { backgroundColor: "rgba(255,255,255,0)", duration: 0.8, ease: "power2.out", clearProps: "backgroundColor" }
  );
}
