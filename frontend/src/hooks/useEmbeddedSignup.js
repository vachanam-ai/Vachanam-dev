import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Meta WhatsApp Embedded Signup, wrapped as one `launch()` call.
 *
 * The clinic owner presses one button and walks through Meta's own popup —
 * they pick (or create) their WhatsApp Business Account and confirm the phone
 * number they ALREADY use. Nothing is typed into Vachanam: no phone_number_id,
 * no WABA id, no access token. That hand-copying (scripts/wa_link_branch.py)
 * is what this replaces.
 *
 * Two things come back, from two different places, and BOTH are required:
 *
 *   1. `code`  — from FB.login's callback. A one-time authorization code that
 *                only our server can spend, because spending it needs
 *                meta_app_secret. This is why response_type is 'code' and
 *                override_default_response_type is true: the default is an
 *                access token delivered to the BROWSER, which would put a
 *                long-lived clinic credential in client-side JS. It must never
 *                be a token here.
 *
 *   2. `waba_id` + `phone_number_id` — from a window 'message' event Meta
 *                posts during the flow (event: 'FINISH', sessionInfoVersion 3).
 *                They are NOT in the login callback, so the listener has to be
 *                attached before the popup opens and both halves joined after.
 *
 * The two arrive independently and in no guaranteed order, so `launch()`
 * resolves only once both are in hand, and rejects if the owner closes the
 * popup (Meta then calls back with no authResponse).
 */

const SDK_ID = "facebook-jssdk";

function loadSdk(graphVersion) {
  if (window.FB) return Promise.resolve(window.FB);
  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SDK_ID);
    const onReady = () => resolve(window.FB);

    window.fbAsyncInit = function fbAsyncInit() {
      // appId is set per-launch (it comes from the server), so init() runs
      // again in launch() once we know it. This early init only guarantees
      // window.FB exists.
      onReady();
    };
    if (existing) {
      // A previous mount already injected the tag; FB may still be parsing.
      existing.addEventListener("load", onReady, { once: true });
      existing.addEventListener("error", () => reject(new Error("sdk_blocked")), { once: true });
      return;
    }
    const js = document.createElement("script");
    js.id = SDK_ID;
    js.src = `https://connect.facebook.net/en_US/sdk.js`;
    js.async = true;
    js.defer = true;
    js.crossOrigin = "anonymous";
    // An ad blocker or a strict corporate network blocks connect.facebook.net
    // outright. Surfacing that as its own error beats a popup that never opens.
    js.onerror = () => reject(new Error("sdk_blocked"));
    document.body.appendChild(js);
    void graphVersion;
  });
}

export default function useEmbeddedSignup() {
  const [launching, setLaunching] = useState(false);
  const sessionRef = useRef(null);

  // Attached for the whole lifetime of the component, not just during the
  // popup: Meta can post the session_info message a beat before or after the
  // login callback fires, and a listener added too late misses it entirely.
  useEffect(() => {
    function onMessage(event) {
      if (!/^https:\/\/(www\.)?facebook\.com$/.test(event.origin)) return;
      let payload = event.data;
      if (typeof payload === "string") {
        try {
          payload = JSON.parse(payload);
        } catch {
          return; // Facebook posts plenty of non-JSON chatter on this channel.
        }
      }
      if (payload?.type !== "WA_EMBEDDED_SIGNUP") return;
      if (payload?.event === "FINISH" || payload?.event === "FINISH_ONLY_WABA") {
        const d = payload.data || {};
        sessionRef.current = {
          waba_id: d.waba_id ?? null,
          phone_number_id: d.phone_number_id ?? null,
        };
      }
      if (payload?.event === "CANCEL" || payload?.event === "ERROR") {
        sessionRef.current = null;
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const launch = useCallback(async ({ appId, configId, graphVersion }) => {
    if (!appId || !configId) throw new Error("not_configured");
    setLaunching(true);
    sessionRef.current = null;
    try {
      const FB = await loadSdk(graphVersion);
      FB.init({ appId, cookie: true, xfbml: false, version: graphVersion });

      const code = await new Promise((resolve, reject) => {
        FB.login(
          (response) => {
            const c = response?.authResponse?.code;
            if (c) resolve(c);
            else reject(new Error("cancelled"));
          },
          {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras: { setup: {}, sessionInfoVersion: "3" },
          },
        );
      });

      const session = sessionRef.current;
      if (!session?.waba_id || !session?.phone_number_id) {
        // The owner authorised but never finished choosing a number — sending
        // a half-connect to the server would store a WABA we cannot send from.
        throw new Error("incomplete");
      }
      return { code, ...session };
    } finally {
      setLaunching(false);
    }
  }, []);

  return { launch, launching };
}
