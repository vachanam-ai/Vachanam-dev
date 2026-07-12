import gsap from "gsap";

/** Staggered entrance for everything marked [data-reveal] inside `scope`.
 *  One orchestrated load beats scattered micro-motion.
 *  #355: animated nodes get [data-revealed] so (a) re-running only reveals
 *  NEW nodes (cards that mount after their query lands) and (b) the CSS
 *  pre-hide releases them — before this, a card mounting after the one-shot
 *  reveal stayed at opacity 0 forever (invisible, space reserved). */
export function revealStagger(scope) {
  const targets = scope?.querySelectorAll?.("[data-reveal]:not([data-revealed])");
  if (!targets?.length) return;
  targets.forEach((el) => el.setAttribute("data-revealed", ""));
  gsap.fromTo(
    targets,
    { opacity: 0, y: 14 },
    { opacity: 1, y: 0, duration: 0.55, ease: "power3.out", stagger: 0.07, clearProps: "transform" }
  );
}

/** Reveal ONE late-mounting element (a card that renders only once its own
 *  query resolves). Idempotent via the same [data-revealed] mark. */
export function revealNow(el) {
  if (!el || el.hasAttribute("data-revealed")) return;
  el.setAttribute("data-revealed", "");
  gsap.fromTo(
    el,
    { opacity: 0, y: 14 },
    { opacity: 1, y: 0, duration: 0.55, ease: "power3.out", clearProps: "transform" }
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
