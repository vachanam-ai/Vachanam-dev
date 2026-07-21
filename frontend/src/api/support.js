import { api, captchaConfig } from "./client";

export const getKb = () => api.get("/support/kb").then((r) => r.data);

export const sendChat = ({ question, history = [], ticketId = null, captcha = "" }) =>
  api
    // 30s: a Neon cold-wake + Gemini call can overrun the client's global 15s
    // and surface as a bogus "something went wrong" (2026-07-12).
    .post(
      "/support/chat",
      { question, history, ticket_id: ticketId },
      captchaConfig(captcha, { timeout: 30000 })
    )
    .then((r) => r.data);

export const listTickets = () => api.get("/support/tickets").then((r) => r.data);

export const getTicketMessages = (id) =>
  api.get(`/support/tickets/${id}/messages`).then((r) => r.data);

// Clinic user actions
export const replyToTicket = (id, body) =>
  api.post(`/support/tickets/${id}/messages`, { body }).then((r) => r.data);
export const rateTicket = (id, score, comment = null) =>
  api.post(`/support/tickets/${id}/csat`, { score, comment }).then((r) => r.data);
export const submitContact = (payload, captcha = "") =>
  api.post("/support/contact", payload, captchaConfig(captcha)).then((r) => r.data);

// Support-staff dashboard
export const adminListTickets = (params = {}) =>
  api.get("/support/admin/tickets", { params }).then((r) => r.data);
export const adminGetMessages = (id) =>
  api.get(`/support/admin/tickets/${id}/messages`).then((r) => r.data);
export const adminReply = (id, body) =>
  api.post(`/support/admin/tickets/${id}/reply`, { body }).then((r) => r.data);
export const adminPatchTicket = (id, patch) =>
  api.patch(`/support/admin/tickets/${id}`, patch).then((r) => r.data);
export const adminMacros = () => api.get("/support/admin/macros").then((r) => r.data);

// Staff provisioning (super_admin only)
export const listStaff = () => api.get("/support/admin/staff").then((r) => r.data);
export const createStaff = (payload) =>
  api.post("/support/admin/staff", payload).then((r) => r.data);
export const deleteStaff = (id) =>
  api.delete(`/support/admin/staff/${id}`).then((r) => r.data);
