import axios from "axios";

const TOKEN_KEY = "vachanam_jwt";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// In dev, VITE_API_URL is unset → baseURL "" → relative paths hit the Vite proxy
// (/auth,/api,… → uvicorn:8000). In prod (Cloudflare Pages, a static CDN with no
// backend on its origin) set VITE_API_URL to the API host (e.g.
// https://api.vachanam.in) so calls go cross-origin to Render. CORS is allowed
// there via the backend's FRONTEND_URL. Trailing slash trimmed to avoid “//path”.
export const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
export const api = axios.create({ baseURL: API_BASE, timeout: 15000, withCredentials: true });

// A Turnstile token belongs to one widget and one request. Keeping it in the
// request config prevents simultaneous forms from consuming each other's
// single-use tokens.
export const captchaConfig = (token, extra = {}) => {
  if (!token) return extra;
  return {
    ...extra,
    headers: { ...(extra.headers || {}), "X-Turnstile-Token": token },
    _turnstileTokenUsed: token
  };
};

const notifyCaptchaConsumed = (config) => {
  const token = config?._turnstileTokenUsed;
  if (token) window.dispatchEvent(new CustomEvent("vachanam:captcha-consumed", { detail: token }));
};

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => {
    notifyCaptchaConsumed(res.config);
    return res;
  },
  (err) => {
    notifyCaptchaConsumed(err.config);
    if (err.response?.status === 401) {
      clearToken();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(err);
  }
);

// ── Auth ──
export const loginWithGoogle = (id_token) =>
  api.post("/auth/google", { id_token }).then((r) => r.data);
export const loginWithPassword = (email, password, captchaToken) =>
  api.post("/auth/login", { email, password }, captchaConfig(captchaToken)).then((r) => r.data);
export const registerClinic = (payload, captchaToken) =>
  api.post("/auth/register", payload, captchaConfig(captchaToken)).then((r) => r.data);
export const requestOtp = (payload, captchaToken) =>
  api.post("/auth/request-otp", payload, captchaConfig(captchaToken)).then((r) => r.data);
export const forgotPassword = (email, captchaToken) =>
  api.post("/auth/forgot-password", { email }, captchaConfig(captchaToken)).then((r) => r.data);
export const resetPassword = (email, code, new_password) =>
  api.post("/auth/reset-password", { email, code, new_password }).then((r) => r.data);
export const fetchMe = () =>
  api.get("/auth/me").then((r) => {
    const d = r.data;
    // Guard: if the wrong backend (a misrouted proxy, another app on the port)
    // answers /auth/me with a 200 HTML body, axios hands us that string. Treat
    // anything that is not a real user object as logged-OUT — otherwise a
    // truthy garbage "user" renders an empty shell forever with no redirect.
    if (!d || typeof d !== "object" || !d.user_id || !d.role) {
      throw new Error("Unexpected /auth/me response — not a Vachanam session");
    }
    return d;
  });
export const logoutSession = () => api.post("/auth/logout");

// ── Plan / billing (clinic owner) ──
export const fetchPlan = () => api.get("/api/plan").then((r) => r.data);
export const changePlan = (plan) =>
  api.post("/api/plan-change", { plan }).then((r) => r.data);
export const cancelPlanChange = () =>
  api.post("/api/plan-change/cancel").then((r) => r.data);
export const createPaymentOrder = (plan) =>
  api.post("/api/create-order", { plan }).then((r) => r.data);
export const createAutopaySubscription = (plan) =>
  api.post("/api/create-subscription", { plan }).then((r) => r.data);
export const verifyPayment = (payload) =>
  api.post("/api/verify-payment", payload).then((r) => r.data);
export const verifyAutopaySubscription = (payload) =>
  api.post("/api/verify-subscription", payload).then((r) => r.data);
export const saveGstin = (gstin) =>
  api.post("/api/billing/gstin", { gstin }).then((r) => r.data);

// ── Analytics (owner) ──
export const fetchAnalytics = (branchId, days = 14) =>
  api.get("/analytics/overview", { params: { branch_id: branchId, days } }).then((r) => r.data);

export const fetchCallQuality = (branchId, days = 14) =>
  api
    .get("/analytics/call-quality", { params: { branch_id: branchId, days } })
    .then((r) => r.data);

// ── Caller messages for the doctor (#349) ──
export const fetchMessages = (branchId) =>
  api.get(`/branches/${branchId}/messages`).then((r) => r.data);
export const resolveMessage = (branchId, messageId) =>
  api.patch(`/branches/${branchId}/messages/${messageId}`).then((r) => r.data);

// ── Questions the AI could not answer → doctor answers → patient gets a callback ──
export const fetchQuestions = (branchId) =>
  api.get(`/branches/${branchId}/questions`).then((r) => r.data);
export const answerQuestion = (branchId, questionId, answer, addToFaq) =>
  api
    .post(`/branches/${branchId}/questions/${questionId}/answer`, {
      answer,
      add_to_faq: addToFaq,
    })
    .then((r) => r.data);
// Drop a question without answering — nothing reaches the caller (2026-08-04).
export const dismissQuestion = (branchId, questionId) =>
  api
    .post(`/branches/${branchId}/questions/${questionId}/dismiss`)
    .then((r) => r.data);

// ── WhatsApp post-visit ratings (WA T9) ──
export const fetchRatingsSummary = (branchId) =>
  api.get(`/branches/${branchId}/ratings/summary`).then((r) => r.data);

// ── Queue (receptionist) ──
export const fetchTodayQueue = (branchId, date) =>
  // `date` (YYYY-MM-DD) omitted = the branch's today. Bookings land days ahead
  // when a doctor publishes a week of sessions, and this is the only view of
  // them, so the desk has to be able to step off today.
  api.get(`/queue/${branchId}/today`, date ? { params: { date } } : undefined)
    .then((r) => r.data);
export const markAttended = (branchId, tokenId) =>
  api.patch(`/queue/${branchId}/token/${tokenId}/attend`).then((r) => r.data);
export const markNoShow = (branchId, tokenId) =>
  api.patch(`/queue/${branchId}/token/${tokenId}/no-show`).then((r) => r.data);

// ── Doctors ── (paths match backend/routers/doctors.py exactly)
export const fetchDoctors = (branchId) =>
  api.get(`/doctors/${branchId}`).then((r) => r.data);
export const stopWalkinsToday = (doctorId, branchId) =>
  api.patch(`/doctors/${branchId}/${doctorId}/stop-walkins-today`).then((r) => r.data);

// ── Availability (receptionist + owner) ──
export const fetchUnavailability = (branchId, doctorId, from, to) =>
  api
    .get(`/availability/${branchId}/${doctorId}`, { params: { from, to } })
    .then((r) => r.data);
export const markUnavailable = (branchId, doctorId, payload) =>
  api.post(`/availability/${branchId}/${doctorId}`, payload).then((r) => r.data);
export const previewAffected = (branchId, doctorId, from, to) =>
  api
    .get(`/availability/${branchId}/${doctorId}/affected`, { params: { from, to } })
    .then((r) => r.data);
export const fetchUpcomingLeave = (branchId, days = 30) =>
  api.get(`/availability/${branchId}/leave/upcoming`, { params: { days } })
    .then((r) => r.data);
export const fetchDoctorSchedules = (branchId, doctorId, from, to) =>
  api.get(`/availability/${branchId}/${doctorId}/schedule`, { params: { from, to } })
    .then((r) => r.data);
export const publishDoctorSchedule = (branchId, doctorId, date, payload) =>
  api.put(`/availability/${branchId}/${doctorId}/schedule/${date}`, payload)
    .then((r) => r.data);
export const deleteDoctorSchedule = (branchId, doctorId, date) =>
  api.delete(`/availability/${branchId}/${doctorId}/schedule/${date}`);

// WhatsApp add-on (₹1,499/mo). One-off charge for the rest of this cycle; from
// the next renewal it is bundled into the plan invoice, so there is never a
// second subscription to manage.
export const createWhatsappAddonOrder = () =>
  api.post("/api/whatsapp-addon/order").then((r) => r.data);

// ── Branch settings / team ──
export const fetchBranchSettings = (branchId) =>
  api.get(`/branches/${branchId}/settings`).then((r) => r.data);
export const updateBranchSettings = (branchId, payload) =>
  api.patch(`/branches/${branchId}/settings`, payload).then((r) => r.data);
export const setBranchVoice = (branchId, tts_voice, language) => {
  const body = {};
  if (tts_voice != null) body.tts_voice = tts_voice;
  if (language != null) body.language = language;
  return api.patch(`/branches/${branchId}/voice`, body).then((r) => r.data);
};
export const getBranchVoices = (branchId, language) =>
  api
    .get(`/branches/${branchId}/voices`, { params: language ? { language } : {} })
    .then((r) => r.data);
export const fetchVoiceClones = (branchId) =>
  api.get(`/branches/${branchId}/voice-clones`).then((r) => r.data);
export const createVoiceClone = (branchId, formData) =>
  api.post(`/branches/${branchId}/voice-clones`, formData, {
    timeout: 45000,
  }).then((r) => r.data);
export const importVoiceClone = (branchId, payload) =>
  api.post("/branches/" + branchId + "/voice-clones/import", payload, {
    timeout: 20000,
  }).then((r) => r.data);
export const activateVoiceClone = (branchId, cloneId) =>
  api.post(`/branches/${branchId}/voice-clones/${cloneId}/activate`).then((r) => r.data);
export const previewVoiceClone = (branchId, cloneId) =>
  api.post(`/branches/${branchId}/voice-clones/${cloneId}/preview`, null, {
    responseType: "blob",
    timeout: 45000,
  }).then((r) => r.data);
export const deleteVoiceClone = (branchId, cloneId) =>
  api.delete(`/branches/${branchId}/voice-clones/${cloneId}`).then((r) => r.data);
export const getBranchFaq = (branchId) =>
  api.get(`/branches/${branchId}/faq`).then((r) => r.data);
export const saveBranchFaq = (branchId, faq) =>
  api.put(`/branches/${branchId}/faq`, { faq }).then((r) => r.data);
export const testCalendar = (branchId) =>
  api.post(`/branches/${branchId}/calendar-test`).then((r) => r.data);

// ── WhatsApp templates (WA MVP1 Task 10) — clinic-authored, per-WABA ──
export const fetchWaTemplates = (branchId) =>
  api.get(`/branches/${branchId}/whatsapp/templates`).then((r) => r.data);
export const createWaTemplate = (branchId, payload) =>
  api.post(`/branches/${branchId}/whatsapp/templates`, payload).then((r) => r.data);
export const installWaSystemTemplates = (branchId) =>
  api.post(`/branches/${branchId}/whatsapp/templates/system`).then((r) => r.data);
export const deleteWaTemplate = (branchId, name) =>
  api.delete(`/branches/${branchId}/whatsapp/templates/${encodeURIComponent(name)}`).then((r) => r.data);
// ── WhatsApp Embedded Signup — clinic connects its OWN WABA in one click ──
export const fetchWaConnection = (branchId) =>
  api.get(`/branches/${branchId}/whatsapp/connect`).then((r) => r.data);
export const fetchWaSignupConfig = (branchId) =>
  api.get(`/branches/${branchId}/whatsapp/signup-config`).then((r) => r.data);
export const connectWa = (branchId, payload) =>
  api.post(`/branches/${branchId}/whatsapp/connect`, payload).then((r) => r.data);
export const connectWaManual = (branchId, payload) =>
  api.post(`/branches/${branchId}/whatsapp/connect/manual`, payload).then((r) => r.data);
export const disconnectWa = (branchId) =>
  api.delete(`/branches/${branchId}/whatsapp/connect`).then((r) => r.data);

export const fetchWaChats = (branchId) =>
  api.get(`/branches/${branchId}/whatsapp/chats`).then((r) => r.data);
export const fetchWaChat = (branchId, phone) =>
  api.get(`/branches/${branchId}/whatsapp/chats/${encodeURIComponent(phone)}`).then((r) => r.data);

export const fetchStaff = (branchId) =>
  api.get(`/branches/${branchId}/staff`).then((r) => r.data);
export const addStaff = (branchId, payload) =>
  api.post(`/branches/${branchId}/staff`, payload).then((r) => r.data);
export const removeStaff = (branchId, userId) =>
  api.delete(`/branches/${branchId}/staff/${userId}`).then((r) => r.data);
export const deleteAccount = (payload) =>
  api.post("/auth/delete-account", payload).then((r) => r.data);
export const createDoctor = (branchId, payload) =>
  api.post(`/doctors/${branchId}`, payload).then((r) => r.data);
export const updateDoctor = (branchId, doctorId, payload) =>
  api.patch(`/doctors/${branchId}/${doctorId}`, payload).then((r) => r.data);
export const deleteDoctor = (branchId, doctorId) =>
  api.delete(`/doctors/${branchId}/${doctorId}`);

// ── Admin (super_admin only — no clinic PII by design) ──
export const adminPing = () => api.get("/admin/ping").then((r) => r.data);
export const fetchOwners = () => api.get("/admin/owners").then((r) => r.data);
export const addOwner = (payload) => api.post("/admin/owners", payload).then((r) => r.data);
export const fetchClients = () => api.get("/admin/clients").then((r) => r.data);
export const fetchAdminOverview = () => api.get("/admin/overview").then((r) => r.data);
export const fetchAdminMonitoring = (days = 14) =>
  api.get("/admin/monitoring", { params: { days } }).then((r) => r.data);
export const fetchHealthBoard = () =>
  api.get("/admin/health-board").then((r) => r.data);
export const setOrgStatus = (orgId, status) =>
  api.post(`/admin/orgs/${orgId}/status`, { status }).then((r) => r.data);
export const startOrgPilot = (orgId) =>
  api.post(`/admin/orgs/${orgId}/pilot`).then((r) => r.data);
export const setOrgPlan = (orgId, plan) =>
  api.post(`/admin/orgs/${orgId}/plan`, { plan }).then((r) => r.data);
export const setOrgHardBlock = (orgId, enabled) =>
  api.post(`/admin/orgs/${orgId}/hard-block`, { enabled }).then((r) => r.data);
export const setOrgMinutes = (orgId, adjustment) =>
  api.post(`/admin/orgs/${orgId}/minutes`, { adjustment }).then((r) => r.data);
export const deleteOrg = (orgId) =>
  api.delete(`/admin/orgs/${orgId}`).then((r) => r.data);

// ── Billing page (clinic owner) ──
export const fetchBillingSummary = () =>
  api.get("/api/billing/summary").then((r) => r.data);
export const cancelSubscription = (cancel = true) =>
  api.post("/api/plan-cancel", { cancel }).then((r) => r.data);
