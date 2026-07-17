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
export const api = axios.create({ baseURL: API_BASE, timeout: 15000 });

// Cloudflare Turnstile token (bot protection). Pages set it via the widget;
// the interceptor attaches it only on the four protected auth endpoints.
// Tokens are SINGLE-USE: once attached, the token is cleared and the widget
// reset here — pages never manage token lifecycle themselves. (Reusing a
// token gets Cloudflare's "timeout-or-duplicate" rejection → 403.)
let turnstileToken = "";
let turnstileReset = null;
export const setTurnstileToken = (t) => { turnstileToken = t || ""; };
export const setTurnstileResetter = (fn) => { turnstileReset = fn; };
const TURNSTILE_PATHS = new Set([
  "/auth/login", "/auth/register", "/auth/request-otp", "/auth/forgot-password",
  // Public support surface: backend requires Turnstile for ANONYMOUS callers
  // on these (authed callers skip it server-side; the header is ignored then).
  "/support/chat", "/support/contact",
]);

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (turnstileToken && TURNSTILE_PATHS.has(config.url)) {
    config.headers["X-Turnstile-Token"] = turnstileToken;
    turnstileToken = ""; // consumed — a second submit needs a fresh solve
    try { turnstileReset?.(); } catch { /* widget unmounted */ }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
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
export const loginWithPassword = (email, password) =>
  api.post("/auth/login", { email, password }).then((r) => r.data);
export const registerClinic = (payload) =>
  api.post("/auth/register", payload).then((r) => r.data);
export const requestOtp = (payload) =>
  api.post("/auth/request-otp", payload).then((r) => r.data);
export const forgotPassword = (email) =>
  api.post("/auth/forgot-password", { email }).then((r) => r.data);
export const resetPassword = (email, code, new_password) =>
  api.post("/auth/reset-password", { email, code, new_password }).then((r) => r.data);
export const fetchMe = () => api.get("/auth/me").then((r) => r.data);

// ── Plan / billing (clinic owner) ──
export const fetchPlan = () => api.get("/api/plan").then((r) => r.data);
export const changePlan = (plan) =>
  api.post("/api/plan-change", { plan }).then((r) => r.data);
export const createPaymentOrder = (plan) =>
  api.post("/api/create-order", { plan }).then((r) => r.data);
export const verifyPayment = (payload) =>
  api.post("/api/verify-payment", payload).then((r) => r.data);
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

// ── WhatsApp post-visit ratings (WA T9) ──
export const fetchRatingsSummary = (branchId) =>
  api.get(`/branches/${branchId}/ratings/summary`).then((r) => r.data);

// ── Queue (receptionist) ──
export const fetchTodayQueue = (branchId) =>
  api.get(`/queue/${branchId}/today`).then((r) => r.data);
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
export const cloneBranchVoice = (branchId, displayName, file, language) => {
  const fd = new FormData();
  fd.append("display_name", displayName);
  fd.append("file", file);
  if (language) fd.append("language", language);
  return api
    .post(`/branches/${branchId}/voice-clone`, fd, {
      headers: { "Content-Type": "multipart/form-data" }
    })
    .then((r) => r.data);
};
export const deleteBranchVoiceClone = (branchId) =>
  api.delete(`/branches/${branchId}/voice-clone`).then((r) => r.data);
export const getBranchFaq = (branchId) =>
  api.get(`/branches/${branchId}/faq`).then((r) => r.data);
export const saveBranchFaq = (branchId, faq) =>
  api.put(`/branches/${branchId}/faq`, { faq }).then((r) => r.data);
export const registerClonedVoice = (branchId, payload) =>
  api.post(`/branches/${branchId}/cloned-voices`, payload).then((r) => r.data);
export const removeClonedVoice = (branchId, voiceId) =>
  api.delete(`/branches/${branchId}/cloned-voices/${voiceId}`).then((r) => r.data);
export const testCalendar = (branchId) =>
  api.post(`/branches/${branchId}/calendar-test`).then((r) => r.data);
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
export const setOrgPlan = (orgId, plan) =>
  api.post(`/admin/orgs/${orgId}/plan`, { plan }).then((r) => r.data);
export const setOrgHardBlock = (orgId, enabled) =>
  api.post(`/admin/orgs/${orgId}/hard-block`, { enabled }).then((r) => r.data);
export const setOrgMinutes = (orgId, adjustment) =>
  api.post(`/admin/orgs/${orgId}/minutes`, { adjustment }).then((r) => r.data);
export const deleteOrg = (orgId) =>
  api.delete(`/admin/orgs/${orgId}`).then((r) => r.data);
