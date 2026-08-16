import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import useEmbeddedSignup from "../useEmbeddedSignup.js";

function fbFor(event, data, capture) {
  return {
    init: vi.fn(),
    login: vi.fn((callback, options) => {
      capture(options);
      callback({ authResponse: { code: "thirty-second-code" } });
      window.dispatchEvent(new MessageEvent("message", {
        origin: "https://www.facebook.com",
        data: JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event, data }),
      }));
    }),
  };
}

afterEach(() => {
  delete window.FB;
  vi.restoreAllMocks();
});

describe("useEmbeddedSignup v4", () => {
  it("joins the authorization code with the Coexistence session event", async () => {
    let loginOptions;
    window.FB = fbFor("FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", {
      waba_id: "waba-1", phone_number_id: "phone-1", business_id: "business-1",
    }, (value) => { loginOptions = value; });
    const { result } = renderHook(() => useEmbeddedSignup());
    let session;
    await act(async () => {
      session = await result.current.launch({
        appId: "app", configId: "config", graphVersion: "v25.0",
        featureType: "whatsapp_business_app_onboarding",
      });
    });
    expect(loginOptions.extras).toMatchObject({
      featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3",
    });
    expect(session).toMatchObject({
      code: "thirty-second-code", waba_id: "waba-1", phone_number_id: "phone-1",
      flow_event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    });
  });

  it("uses standard Embedded Signup without Coexistence extras for a new number", async () => {
    let loginOptions;
    window.FB = fbFor("FINISH", {
      waba_id: "waba-2", phone_number_id: "phone-2",
    }, (value) => { loginOptions = value; });
    const { result } = renderHook(() => useEmbeddedSignup());
    await act(async () => {
      await result.current.launch({ appId: "app", configId: "config", graphVersion: "v25.0" });
    });
    expect(loginOptions.extras).toEqual({ setup: {} });
  });

  it("ignores forged completion events from non-Facebook origins", async () => {
    window.FB = {
      init: vi.fn(),
      login: vi.fn((callback) => {
        callback({ authResponse: { code: "code" } });
        window.dispatchEvent(new MessageEvent("message", {
          origin: "https://evil.example",
          data: JSON.stringify({
            type: "WA_EMBEDDED_SIGNUP", event: "FINISH",
            data: { waba_id: "stolen", phone_number_id: "stolen" },
          }),
        }));
        window.dispatchEvent(new MessageEvent("message", {
          origin: "https://facebook.com",
          data: JSON.stringify({
            type: "WA_EMBEDDED_SIGNUP", event: "FINISH",
            data: { waba_id: "real", phone_number_id: "real" },
          }),
        }));
      }),
    };
    const { result } = renderHook(() => useEmbeddedSignup());
    let session;
    await act(async () => {
      session = await result.current.launch({ appId: "app", configId: "config", graphVersion: "v25.0" });
    });
    expect(session.waba_id).toBe("real");
  });
});
