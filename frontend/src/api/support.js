import { api } from "./client";

export const getKb = () => api.get("/support/kb").then((r) => r.data);

export const sendChat = ({ question, history = [], ticketId = null }) =>
  api
    .post("/support/chat", { question, history, ticket_id: ticketId })
    .then((r) => r.data);

export const listTickets = () => api.get("/support/tickets").then((r) => r.data);

export const getTicketMessages = (id) =>
  api.get(`/support/tickets/${id}/messages`).then((r) => r.data);
