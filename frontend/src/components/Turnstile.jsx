import { useEffect, useRef } from "react";

export const TURNSTILE_ON = Boolean(import.meta.env.VITE_TURNSTILE_SITE_KEY);
const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

let scriptPromise = null;
function loadScript() {
  if (window.turnstile) return Promise.resolve();
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      s.async = true;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return scriptPromise;
}

/**
 * Cloudflare Turnstile widget. Renders nothing when VITE_TURNSTILE_SITE_KEY
 * is unset (dev / feature off — backend skips verification too).
 *
 * Each widget owns its token. The API request carries that token explicitly,
 * then emits a consumption event so only the matching widget resets.
 */
export default function Turnstile({ onToken }) {
  const ref = useRef(null);
  const widgetId = useRef(null);
  const currentToken = useRef("");
  const cb = useRef(onToken);
  cb.current = onToken;

  useEffect(() => {
    if (!TURNSTILE_ON) return;
    let cancelled = false;
    const emit = (t) => {
      currentToken.current = t || "";
      cb.current?.(t);
    };
    const consumed = (event) => {
      if (!event.detail || event.detail !== currentToken.current) return;
      emit("");
      if (widgetId.current !== null && window.turnstile) {
        try { window.turnstile.reset(widgetId.current); } catch { /* widget gone */ }
      }
    };
    window.addEventListener("vachanam:captcha-consumed", consumed);
    loadScript().then(() => {
      if (cancelled || !ref.current || widgetId.current !== null) return;
      widgetId.current = window.turnstile.render(ref.current, {
        sitekey: SITE_KEY,
        // Follow the APP theme, not the OS one (user can toggle them apart).
        theme: document.documentElement.classList.contains("dark") ? "dark" : "light",
        callback: emit,
        "expired-callback": () => emit(""),
        "error-callback": () => emit(""),
      });
    }).catch(() => {}); // script blocked → backend fail-open policy decides
    return () => {
      cancelled = true;
      window.removeEventListener("vachanam:captcha-consumed", consumed);
      emit("");
      if (widgetId.current !== null && window.turnstile) {
        try { window.turnstile.remove(widgetId.current); } catch { /* gone */ }
        widgetId.current = null;
      }
    };
  }, []);

  if (!TURNSTILE_ON) return null;
  return <div ref={ref} className="my-3" />;
}
