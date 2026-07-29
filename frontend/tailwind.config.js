/** Vachanam brand — monochrome "clinic desk" (BizLink-reference, 2026-07-29).
 * Colors read CSS variables (RGB triplets in index.css) so .dark on <html>
 * re-themes everything in one place; <alpha-value> keeps opacity modifiers.
 * The `teal*` names are retained (now the neutral accent scale) so the 18
 * existing pages re-theme without a rename. General Sans is the sole face. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // accent scale (name kept, value now neutral near-black)
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
        line2: v("line2"),
        // new monochrome tokens
        band: v("band"),
        panel: v("panel"),
        pill: v("pill"),
        accent: { DEFAULT: v("accent"), ink: v("accent-ink") },
        sel: { DEFAULT: v("sel"), ink: v("sel-ink"), muted: v("sel-muted"), line: v("sel-line") },
        // semantic status (separate from the accent)
        good: { DEFAULT: v("good"), bg: v("good-bg") },
        warn: { DEFAULT: v("warn"), bg: v("warn-bg") },
        danger: { DEFAULT: v("danger"), bg: v("danger-bg") },
        gold: { DEFAULT: v("gold"), soft: v("gold-soft"), ink: v("gold-ink") }
      },
      fontFamily: {
        // one face, three role aliases so existing font-display / font-brand
        // class usages keep working without a per-file rename.
        display: ["General Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        ui: ["General Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        brand: ["General Sans", "ui-sans-serif", "system-ui", "sans-serif"]
      },
      boxShadow: {
        card: "0 1px 2px rgba(20,20,18,.05), 0 10px 30px -18px rgba(20,20,18,.14)",
        lift: "0 2px 4px rgba(20,20,18,.06), 0 18px 40px -18px rgba(20,20,18,.22)"
      }
    }
  },
  plugins: []
};
