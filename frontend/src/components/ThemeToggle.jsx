import { useState } from "react";

/* Sun/moon theme toggle — the two icons cross-fade + rotate through each
   other; choice persists in localStorage and is applied pre-paint by the
   inline script in index.html (no flash of wrong theme). */
export default function ThemeToggle({ float = false }) {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark")
  );
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("vachanam-theme", next ? "dark" : "light"); } catch { /* private mode */ }
  };
  return (
    <button type="button" onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      className={`grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full border border-hairline bg-surface/70 text-teal backdrop-blur transition-colors duration-200 hover:bg-teal-mint ${
        float ? "fixed right-4 top-4 z-50 shadow-card" : "relative"}`}>
      {/* sun */}
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" aria-hidden
        className={`absolute transition-all duration-300 ease-out ${
          dark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100"}`}>
        <circle cx="12" cy="12" r="4.5" />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
          <line key={a} x1="12" y1="2.5" x2="12" y2="4.5" transform={`rotate(${a} 12 12)`} />
        ))}
      </svg>
      {/* moon */}
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden
        className={`absolute transition-all duration-300 ease-out ${
          dark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0"}`}>
        <path d="M20.3 14.6A8.5 8.5 0 0 1 9.4 3.7a8.5 8.5 0 1 0 10.9 10.9Z" />
      </svg>
    </button>
  );
}
