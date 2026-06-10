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
export const fetchMe = () => api.get("/auth/me").then((r) => r.data);

// ── Queue (receptionist) ──
export const fetchTodayQueue = (branchId) =>
  api.get(`/queue/${branchId}/today`).then((r) => r.data);
export const markAttended = (branchId, tokenId) =>
  api.patch(`/queue/${branchId}/token/${tokenId}/attend`).then((r) => r.data);
export const markNoShow = (branchId, tokenId) =>
  api.patch(`/queue/${branchId}/token/${tokenId}/no-show`).then((r) => r.data);

// ── Doctors ──
export const fetchDoctors = (branchId) =>
  api.get(`/doctors`, { params: { branch_id: branchId } }).then((r) => r.data);
export const stopWalkinsToday = (doctorId, branchId) =>
  api
    .post(`/doctors/${doctorId}/stop-walkins-today`, null, { params: { branch_id: branchId } })
    .then((r) => r.data);

// ── Availability (doctor self-service) ──
export const fetchUnavailability = (doctorId, branchId) =>
  api
    .get(`/availability/${doctorId}`, { params: { branch_id: branchId } })
    .then((r) => r.data);

// ── Admin (super_admin only — no clinic PII by design) ──
export const adminPing = () => api.get("/admin/ping").then((r) => r.data);
