export const PLAN_CATALOG = {
  solo: {
    name: "Vachanam Voice",
    price: 1999,
    minutes: 0,
    doctors: "Unlimited doctors",
    branches: "1 branch",
    tagline: "One clinic number, complete receptionist workflow",
    popular: true,
  },
  clinic: {
    name: "Growth",
    price: 4999,
    minutes: 0,
    doctors: "10 doctors",
    branches: "1 branch",
    tagline: "For busy clinics with a larger medical team",
    popular: true,
  },
  multi: {
    name: "Scale",
    price: 6999,
    minutes: 0,
    doctors: "Unlimited doctors",
    branches: "2 branches",
    tagline: "For multi-specialty teams and growing clinic groups",
  },
  wa: {
    name: "WhatsApp",
    price: 1999,
    minutes: 0,
    doctors: "3 doctors",
    branches: "1 branch",
    tagline: "Booking and patient service in chat, without a voice line",
  },
};

export const VOICE_PLAN_KEYS = ["solo"];
// Fail closed until Meta approves Vachanam for public clinic onboarding.
// The private Venkateshwara bridge is backend-only and does not need this UI.
// One deployment flag controls every public WhatsApp entry point. Keep this
// fail-closed when the value is absent or misspelled.
export const WHATSAPP_SELF_SERVE_LIVE = import.meta.env.VITE_WHATSAPP_LIVE === "true";
export const PUBLIC_PLAN_KEYS = WHATSAPP_SELF_SERVE_LIVE
  ? [...VOICE_PLAN_KEYS, "wa"]
  : VOICE_PLAN_KEYS;
export const OVERAGE_RUPEES = 6;
export const WHATSAPP_ADDON_RUPEES = 1499;
export const ADDITIONAL_BRANCH_RUPEES = 1499;
export const ADDITIONAL_NUMBER_RUPEES = 1499;
export const TRIAL_DAYS = 14;

export const planLabel = (key, withPrice = false) => {
  const plan = PLAN_CATALOG[key];
  if (!plan) return key;
  return withPrice
    ? plan.name + " · ₹" + plan.price.toLocaleString("en-IN") + "/mo"
    : plan.name;
};
