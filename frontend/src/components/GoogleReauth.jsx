import { useEffect, useRef } from "react";
import { gsiTheme, watchTheme } from "../lib/gsiTheme.js";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

/**
 * Step-up re-authentication with Google, for actions a stolen session must not
 * be able to perform on its own.
 *
 * The Jul-25 security review made DELETE /auth/delete-account require a FRESH
 * Google ID token for password-less accounts — a typed "DELETE" is a UI guard,
 * not authentication. The frontend was never taught to produce one, so it kept
 * posting {confirm:"DELETE"} and the API kept answering
 * 401 "Google re-verification required to delete". Clinic deletion was
 * impossible from the UI for three weeks (found 2026-08-14).
 *
 * Renders Google's own button; `onToken` receives a fresh credential (an ID
 * token whose audience is our client id, which is what the backend verifies).
 */
export default function GoogleReauth({ onToken, disabled, text = "continue_with" }) {
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
        text,
      });
    };

    const mount = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) return void setTimeout(mount, 150);
      // initialize() is global to the GIS script. Settings and Login are never
      // mounted together, so re-initializing here simply rebinds the callback
      // to this component for as long as it is on screen.
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp) => {
          if (resp?.credential) handler.current?.(resp.credential);
        },
      });
      paint();
    };

    mount();
    const stopWatch = watchTheme(paint);
    return () => {
      cancelled = true;
      stopWatch?.();
    };
  }, [text]);

  if (!GOOGLE_CLIENT_ID) {
    return (
      <p className="font-ui text-xs text-danger">
        Google sign-in isn&apos;t configured in this build, so re-verification
        can&apos;t run. Set a password on your account, or contact support.
      </p>
    );
  }

  return (
    <div
      ref={holder}
      aria-label="Confirm with Google"
      style={disabled ? { pointerEvents: "none", opacity: 0.5 } : undefined}
    />
  );
}
