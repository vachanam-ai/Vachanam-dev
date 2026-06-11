import axios from "axios";

const TOKEN_KEY = "vachanam_jwt";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export const api = axios.create({ timeout: 15000 });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
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
export const fetchMe = () => api.get("/auth/me").then((r) => r.data);

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

// ── Branch settings / team ──
export const fetchBranchSettings = (branchId) =>
  api.get(`/branches/${branchId}/settings`).then((r) => r.data);
export const updateBranchSettings = (branchId, payload) =>
  api.patch(`/branches/${branchId}/settings`, payload).then((r) => r.data);
export const setBranchVoice = (branchId, tts_voice) =>
  api.patch(`/branches/${branchId}/voice`, { tts_voice }).then((r) => r.data);
export const testCalendar = (branchId) =>
  api.post(`/branches/${branchId}/calendar-test`).then((r) => r.data);
export const fetchStaff = (branchId) =>
  api.get(`/branches/${branchId}/staff`).then((r) => r.data);
export const addStaff = (branchId, payload) =>
  api.post(`/branches/${branchId}/staff`, payload).then((r) => r.data);
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
