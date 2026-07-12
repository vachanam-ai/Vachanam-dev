/** The Google Sign-In button is an iframe — CSS can't touch it. Ask Google
 *  for the dark variant when the app is dark, and re-render on toggle. */
export const gsiTheme = () =>
  document.documentElement.classList.contains("dark") ? "filled_black" : "outline";

/** Calls onChange whenever the root .dark class flips (ThemeToggle). */
export function watchTheme(onChange) {
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => mo.disconnect();
}
