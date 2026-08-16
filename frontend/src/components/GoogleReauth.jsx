import { useEffect, useRef } from "react";
import { gsiTheme, watchTheme } from "../lib/gsiTheme.js";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

// Destructive account deletion needs a fresh Google ID token. Typing DELETE
// is only a UI guard; it cannot authenticate a Google-only owner.
export default function GoogleReauth({ onToken, disabled }) {
  const holder = useRef(null);
  const handler = useRef(onToken);
  handler.current = onToken;

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return undefined;
    let cancelled = false;

    const paint = () => {
      if (cancelled || !holder.current || !window.google?.accounts?.id) return;
      holder.current.innerHTML = "";
      window.google.accounts.id.renderButton(holder.current, {
        theme: gsiTheme(),
        size: "large",
        shape: "pill",
        width: Math.min(320, holder.current.offsetWidth || 320),
        text: "continue_with",
      });
    };
    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) {
        window.setTimeout(mount, 150);
        return;
      }
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => response?.credential && handler.current?.(response.credential),
      });
      paint();
    };

    mount();
    const stopWatching = watchTheme(paint);
    return () => {
      cancelled = true;
      stopWatching?.();
    };
  }, []);

  if (!GOOGLE_CLIENT_ID) {
    return <p className="font-ui text-xs text-danger">Google re-verification is not configured.</p>;
  }

  return (
    <div
      ref={holder}
      aria-label="Confirm with Google"
      style={disabled ? { pointerEvents: "none", opacity: 0.5 } : undefined}
    />
  );
}
