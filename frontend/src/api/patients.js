import { api } from "./client";

export const listPatients = (branchId) =>
  api.get(`/patients/branches/${branchId}/patients`).then((r) => r.data.patients);

export const editPatient = (patientId, payload) =>
  api.patch(`/patients/${patientId}`, payload).then((r) => r.data);
