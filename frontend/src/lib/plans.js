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
export const PUBLIC_PLAN_KEYS = [...VOICE_PLAN_KEYS, "wa"];
export const OVERAGE_RUPEES = 6;
export const WHATSAPP_ADDON_RUPEES = 1499;
export const ADDITIONAL_BRANCH_RUPEES = 1499;
export const ADDITIONAL_NUMBER_RUPEES = 1499;
export const TRIAL_MINUTES = 30;
export const FOUNDING_CREDIT_MINUTES = 500;

export const planLabel = (key, withPrice = false) => {
  const plan = PLAN_CATALOG[key];
  if (!plan) return key;
  return withPrice
    ? plan.name + " · ₹" + plan.price.toLocaleString("en-IN") + "/mo"
    : plan.name;
};
