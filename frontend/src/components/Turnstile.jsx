import { useEffect, useRef } from "react";
import { setTurnstileResetter, setTurnstileToken } from "../api/client.js";

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
 * Token lifecycle lives in api/client.js: this component feeds every fresh
 * token in via setTurnstileToken and registers a resetter; the axios
 * interceptor consumes the token on use and resets THIS widget (by id) so
 * the next submit always carries a fresh solve. `onToken` (optional) lets a
 * page disable its submit button until a token exists.
 */
export default function Turnstile({ onToken }) {
  const ref = useRef(null);
  const widgetId = useRef(null);
  const cb = useRef(onToken);
  cb.current = onToken;

  useEffect(() => {
    if (!TURNSTILE_ON) return;
    let cancelled = false;
    const emit = (t) => {
      setTurnstileToken(t);
      cb.current?.(t);
    };
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
      // interceptor resets THIS widget after consuming its token
      setTurnstileResetter(() => {
        emit("");
        window.turnstile.reset(widgetId.current);
      });
    }).catch(() => {}); // script blocked → backend fail-open policy decides
    return () => {
      cancelled = true;
      setTurnstileResetter(null);
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
