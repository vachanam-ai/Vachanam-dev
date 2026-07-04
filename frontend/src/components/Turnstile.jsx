import { useEffect, useRef } from "react";

export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

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
 * onToken(token) fires on solve and onToken("") on expiry, so the caller
 * always holds a current token to send as X-Turnstile-Token.
 */
export default function Turnstile({ onToken }) {
  const ref = useRef(null);
  const widgetId = useRef(null);
  const cb = useRef(onToken);
  cb.current = onToken;

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    let cancelled = false;
    loadScript().then(() => {
      if (cancelled || !ref.current || widgetId.current !== null) return;
      widgetId.current = window.turnstile.render(ref.current, {
        sitekey: TURNSTILE_SITE_KEY,
        callback: (t) => cb.current(t),
        "expired-callback": () => cb.current(""),
        "error-callback": () => cb.current(""),
      });
    }).catch(() => {}); // script blocked → backend fail-open policy decides
    return () => {
      cancelled = true;
      if (widgetId.current !== null && window.turnstile) {
        try { window.turnstile.remove(widgetId.current); } catch { /* gone */ }
        widgetId.current = null;
      }
    };
  }, []);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={ref} className="my-3" />;
}

/** Reset the (single) widget after a failed submit — tokens are single-use. */
export function resetTurnstile() {
  if (TURNSTILE_SITE_KEY && window.turnstile) {
    try { window.turnstile.reset(); } catch { /* not rendered */ }
  }
}
