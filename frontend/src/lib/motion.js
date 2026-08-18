/** Product pages render immediately. `data-revealed` remains as the stable
 * contract for late-mounting cards, without loading GSAP or delaying work. */
export function revealStagger(scope) {
  const targets = scope?.querySelectorAll?.("[data-reveal]:not([data-revealed])");
  if (!targets?.length) return;
  targets.forEach((el) => el.setAttribute("data-revealed", ""));
}

/** Reveal one late-mounting element. */
export function revealNow(el) {
  if (!el || el.hasAttribute("data-revealed")) return;
  el.setAttribute("data-revealed", "");
}

/** Paint data immediately; clinic staff should never wait for a count-up. */
export function countUp(el, value, { suffix = "" } = {}) {
  if (!el) return;
  el.textContent = Math.round(value).toString() + suffix;
}

/** Keep short action feedback using the native browser animation API. */
export function pulseRow(el) {
  if (!el || !el.animate || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  el.animate(
    [{ backgroundColor: "rgba(236,238,225,0.9)" }, { backgroundColor: "rgba(236,238,225,0)" }],
    { duration: 450, easing: "cubic-bezier(.22,1,.36,1)" },
  );
}
