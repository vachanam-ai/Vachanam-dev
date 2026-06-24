import { api } from "./client";

export const listTreatmentPatients = (branchId, { doctorId, status = "all" } = {}) =>
  api.get(`/treatment/branches/${branchId}/treatment-patients`, {
    params: { doctor_id: doctorId, status },
  }).then((r) => r.data.patients);

export const listNotes = (patientId, branchId) =>
  api.get(`/treatment/patients/${patientId}/treatment-notes`, {
    params: { branch_id: branchId },
  }).then((r) => r.data);

export const createNote = (patientId, payload) =>
  api.post(`/treatment/patients/${patientId}/treatment-notes`, payload).then((r) => r.data);

export const editNote = (noteId, payload) =>
  api.patch(`/treatment/treatment-notes/${noteId}`, payload).then((r) => r.data);

export const listFollowups = (patientId, branchId) =>
  api.get(`/treatment/patients/${patientId}/followups`, { params: { branch_id: branchId } })
     .then((r) => r.data.thread);

export const replyToPatient = (patientId, payload) =>
  api.post(`/treatment/patients/${patientId}/followups`, payload).then((r) => r.data);
