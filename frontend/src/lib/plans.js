export const PLAN_CATALOG = {
  solo: {
    name: "Basic",
    price: 5999,
    minutes: 400,
    doctors: "3 doctors",
    branches: "1 branch",
    tagline: "For independent clinics building a reliable front desk",
  },
  clinic: {
    name: "Growth",
    price: 10999,
    minutes: 1500,
    doctors: "10 doctors",
    branches: "1 branch",
    tagline: "For busy clinics that need voice and WhatsApp together",
    popular: true,
  },
  multi: {
    name: "Scale",
    price: 21999,
    minutes: 3000,
    doctors: "Unlimited doctors",
    branches: "2 branches",
    tagline: "For multi-specialty teams and growing clinic groups",
  },
  wa: {
    name: "WhatsApp",
    price: 1499,
    minutes: 0,
    doctors: "3 doctors",
    branches: "1 branch",
    tagline: "Booking and patient service in chat, without a voice line",
  },
};

export const VOICE_PLAN_KEYS = ["solo", "clinic", "multi"];
export const PUBLIC_PLAN_KEYS = [...VOICE_PLAN_KEYS, "wa"];
export const OVERAGE_RUPEES = 6;
export const WHATSAPP_ADDON_RUPEES = 1499;
export const ADDITIONAL_BRANCH_RUPEES = 6999;
export const ADDITIONAL_NUMBER_RUPEES = 2499;
export const TRIAL_MINUTES = 30;

export const planLabel = (key, withPrice = false) => {
  const plan = PLAN_CATALOG[key];
  if (!plan) return key;
  return withPrice
    ? plan.name + " · ₹" + plan.price.toLocaleString("en-IN") + "/mo"
    : plan.name;
};
