import { api } from "./client";

export const listPatients = (branchId) =>
  api.get(`/patients/branches/${branchId}/patients`).then((r) => r.data.patients);

export const editPatient = (patientId, payload) =>
  api.patch(`/patients/${patientId}`, payload).then((r) => r.data);

export const deletePatient = (patientId, branchId) =>
  api.delete(`/patients/${patientId}`, { params: { branch_id: branchId } })
    .then((r) => r.data);

export const fetchUpcoming = (branchId, { doctorId, onDate, days = 15 } = {}) =>
  api.get(`/patients/branches/${branchId}/upcoming`, {
    params: {
      days,
      ...(doctorId ? { doctor_id: doctorId } : {}),
      ...(onDate ? { on_date: onDate } : {})
    }
  }).then((r) => r.data);

export const importPatients = (branchId, file) => {
  const form = new FormData();
  form.append("file", file);
  return api.post(`/patients/branches/${branchId}/patients/import`, form)
    .then((r) => r.data);
};
