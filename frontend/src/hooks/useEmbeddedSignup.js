import { useCallback, useEffect, useRef, useState } from "react";

const SDK_ID = "facebook-jssdk";
const FINISH_EVENTS = new Set([
  "FINISH",
  "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
]);

function isFacebookOrigin(origin) {
  try {
    const host = new URL(origin).hostname;
    return host === "facebook.com" || host.endsWith(".facebook.com");
  } catch {
    return false;
  }
}

function loadSdk() {
  if (window.FB) return Promise.resolve(window.FB);
  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SDK_ID);
    const ready = () => window.FB ? resolve(window.FB) : reject(new Error("sdk_blocked"));
    window.fbAsyncInit = ready;
    if (existing) {
      existing.addEventListener("load", ready, { once: true });
      existing.addEventListener("error", () => reject(new Error("sdk_blocked")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.id = SDK_ID;
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => reject(new Error("sdk_blocked"));
    document.body.appendChild(script);
  });
}

export default function useEmbeddedSignup() {
  const [launching, setLaunching] = useState(false);
  const pendingSession = useRef(null);

  useEffect(() => {
    function onMessage(event) {
      if (!isFacebookOrigin(event.origin)) return;
      let payload = event.data;
      if (typeof payload === "string") {
        try { payload = JSON.parse(payload); } catch { return; }
      }
      if (payload?.type !== "WA_EMBEDDED_SIGNUP" || !pendingSession.current) return;
      if (FINISH_EVENTS.has(payload.event)) {
        const data = payload.data || {};
        if (!data.waba_id || !data.phone_number_id) {
          pendingSession.current.reject(new Error("incomplete"));
        } else {
          pendingSession.current.resolve({
            waba_id: String(data.waba_id),
            phone_number_id: String(data.phone_number_id),
            business_id: data.business_id ? String(data.business_id) : null,
            flow_event: payload.event,
          });
        }
      } else if (payload.event === "CANCEL" || payload.event === "ERROR") {
        pendingSession.current.reject(new Error("cancelled"));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const launch = useCallback(async ({ appId, configId, graphVersion, featureType }) => {
    if (!appId || !configId) throw new Error("not_configured");
    setLaunching(true);
    let timer;
    try {
      const FB = await loadSdk();
      FB.init({ appId, autoLogAppEvents: true, cookie: true, xfbml: false, version: graphVersion });

      const sessionPromise = new Promise((resolve, reject) => {
        pendingSession.current = { resolve, reject };
        timer = window.setTimeout(() => reject(new Error("incomplete")), 15000);
      });
      const codePromise = new Promise((resolve, reject) => {
        const extras = { setup: {} };
        if (featureType) {
          extras.featureType = featureType;
          extras.sessionInfoVersion = "3";
        }
        FB.login(
          (response) => response?.authResponse?.code
            ? resolve(response.authResponse.code)
            : reject(new Error("cancelled")),
          {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras,
          },
        );
      });

      const [code, session] = await Promise.all([codePromise, sessionPromise]);
      return { code, ...session };
    } finally {
      window.clearTimeout(timer);
      pendingSession.current = null;
      setLaunching(false);
    }
  }, []);

  return { launch, launching };
}
