/** Vachanam brand — extracted from vachanam.in (teal/cream/ink + Spectral/Outfit).
 * Colors read CSS variables (RGB triplets in index.css) so .dark on <html>
 * re-themes everything in one place; <alpha-value> keeps opacity modifiers. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        teal: {
          DEFAULT: v("teal"),
          deep: v("teal-deep"),
          light: v("teal-light"),
          pale: v("teal-pale"),
          mint: v("teal-mint")
        },
        ink: { DEFAULT: v("ink"), soft: v("ink-soft") },
        slate: { DEFAULT: v("slate"), light: v("slate-light") },
        cream: v("cream"),
        surface: v("surface"),
        hairline: v("hairline"),
        gold: { DEFAULT: v("gold"), soft: v("gold-soft"), ink: v("gold-ink") },
        danger: v("danger")
      },
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        ui: ["Outfit", "system-ui", "sans-serif"],
        brand: ["Pacifico", "cursive"]
      },
      boxShadow: {
        card: "0 1px 2px rgba(26,46,46,.05), 0 8px 24px -12px rgba(0,107,107,.18)",
        lift: "0 2px 4px rgba(26,46,46,.06), 0 16px 40px -16px rgba(0,107,107,.28)"
      }
    }
  },
  plugins: []
};
