import { useState } from "react";
import { Moon, Sun } from "@phosphor-icons/react";

export default function ThemeToggle({ float = false }) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("vachanam-theme", next ? "dark" : "light"); } catch { /* private mode */ }
  };
  return (
    <button type="button" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      className={`grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-hairline bg-surface/75 text-teal backdrop-blur transition-colors hover:bg-teal-mint ${float ? "fixed right-4 top-4 z-50 shadow-card" : "relative"}`}>
      <Sun size={18} weight="duotone" aria-hidden className={`absolute transition-all duration-300 ${dark ? "rotate-0 scale-100 opacity-100" : "rotate-90 scale-0 opacity-0"}`} />
      <Moon size={18} weight="fill" aria-hidden className={`absolute transition-all duration-300 ${dark ? "-rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100"}`} />
    </button>
  );
}
