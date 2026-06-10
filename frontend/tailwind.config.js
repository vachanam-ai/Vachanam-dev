/** Vachanam brand — extracted from vachanam.in (teal/cream/ink + Spectral/Outfit). */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        teal: {
          DEFAULT: "#006B6B",
          deep: "#004F4F",
          light: "#008F8F",
          pale: "#E0F2F1",
          mint: "#F0FAFA"
        },
        ink: { DEFAULT: "#1A2E2E", soft: "#2D4444" },
        slate: { DEFAULT: "#708090", light: "#A0ADB8" },
        cream: "#FAFCFC",
        hairline: "#D0E4E4",
        gold: { DEFAULT: "#f0c674", soft: "#fff4d6", ink: "#5a4500" },
        danger: "#a51d2d"
      },
      fontFamily: {
        display: ["Spectral", "Georgia", "serif"],
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
