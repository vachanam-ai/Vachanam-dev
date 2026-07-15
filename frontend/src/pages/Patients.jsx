import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../hooks/useAuth.jsx";
import { toast } from "sonner";
import { listPatients, editPatient, deletePatient, fetchUpcoming } from "../api/patients.js";
import { fetchDoctors } from "../api/client.js";

export default function Patients() {
  const { branchId } = useAuth();
  const qc = useQueryClient();

  const { data: patients = [], isLoading } = useQuery({
    queryKey: ["patients", branchId],
    queryFn: () => listPatients(branchId),
    enabled: Boolean(branchId)
  });

  const [editing, setEditing] = useState(null); // patient id being edited
  const [deleting, setDeleting] = useState(null); // patient pending delete confirm
  const [form, setForm] = useState({ name: "", age: "", phone: "" });
  const [err, setErr] = useState("");

  const del = useMutation({
    mutationFn: (p) => deletePatient(p.id, branchId),
    onSuccess: () => {
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["patients", branchId] });
      toast.success("Patient data erased");
    },
    onError: () => toast.error("Could not erase — try again")
  });

  const mut = useMutation({
    mutationFn: ({ id, payload }) => editPatient(id, payload),
    onSuccess: () => {
      setEditing(null);
      setErr("");
      qc.invalidateQueries({ queryKey: ["patients", branchId] });
    },
    onError: (e) =>
      setErr(
        e?.response?.status === 409
          ? "Another patient already has this name + number"
          : "Could not save — check the details"
      )
  });

  const startEdit = (p) => {
    setErr("");
    setEditing(p.id);
    setForm({ name: p.name || "", age: p.age ?? "", phone: p.phone || "" });
  };

  const cancelEdit = () => {
    setEditing(null);
    setErr("");
  };

  const save = (p) => {
    setErr("");
    // B24: validate age client-side. Number("abc") is NaN which JSON-serializes
    // to null — the backend then treats it as "no change", so a typo was
    // silently dropped under a success toast. Reject a non-numeric / out-of-range
    // age here instead.
    const payload = { branch_id: branchId, name: form.name };
    if (form.age !== "") {
      const age = Number(form.age);
      if (!Number.isInteger(age) || age < 0 || age > 120) {
        setErr("Age must be a whole number between 0 and 120.");
        return;
      }
      payload.age = age;
    }
    if (form.phone !== "") payload.phone = form.phone;
    mut.mutate({ id: p.id, payload });
  };

  if (!branchId)
    return <p className="font-ui text-slate">No branch linked to your account yet.</p>;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <p className="eyebrow">Records</p>
        <h1 className="section-title text-2xl">Patient information</h1>
      </div>

      <UpcomingAppointments branchId={branchId} />

      {err && <p className="font-ui text-sm text-red-600">{err}</p>}

      {/* Erase confirmation — permanent, so it interrupts */}
      {deleting && (
        <div className="card space-y-3 border-danger/40 p-4">
          <p className="font-ui text-sm">
            Permanently erase <span className="font-semibold">{deleting.name}</span>
            {deleting.phone ? ` (${deleting.phone})` : ""}? Their name, phone and
            visit notes are deleted and any scheduled follow-up calls stop. Anonymous
            booking counts remain in analytics. <span className="font-medium">This
            cannot be undone.</span>
          </p>
          <div className="flex gap-2">
            <button
              className="btn-danger"
              onClick={() => del.mutate(deleting)}
              disabled={del.isPending}
            >
              {del.isPending ? "Erasing…" : "Erase permanently"}
            </button>
            <button className="btn-ghost" onClick={() => setDeleting(null)} disabled={del.isPending}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        {isLoading ? (
          <p className="px-4 py-6 font-ui text-sm text-slate">Loading patients…</p>
        ) : patients.length === 0 ? (
          <p className="px-4 py-6 font-ui text-sm text-slate">No patients yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full font-ui text-sm">
              <thead className="border-b border-hairline bg-teal-mint/60 text-left">
                <tr>
                  <th className="p-3 font-medium">Name</th>
                  <th className="p-3 font-medium">Age</th>
                  <th className="p-3 font-medium">Phone</th>
                  <th className="p-3 font-medium">Last doctor</th>
                  <th className="p-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {patients.map((p) =>
                  editing === p.id ? (
                    <tr key={p.id}>
                      <td className="p-2">
                        <input
                          className="field min-h-[44px] w-full"
                          value={form.name}
                          onChange={(e) => setForm({ ...form, name: e.target.value })}
                          aria-label="Name"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          className="field min-h-[44px] w-16"
                          inputMode="numeric"
                          value={form.age}
                          onChange={(e) => setForm({ ...form, age: e.target.value })}
                          aria-label="Age"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          className="field min-h-[44px] w-full"
                          inputMode="tel"
                          value={form.phone}
                          onChange={(e) => setForm({ ...form, phone: e.target.value })}
                          aria-label="Phone"
                        />
                      </td>
                      <td className="p-3 text-slate">{p.last_doctor || "—"}</td>
                      <td className="whitespace-nowrap p-2">
                        <button
                          className="btn-primary px-3 py-1.5"
                          onClick={() => save(p)}
                          disabled={mut.isPending}
                        >
                          {mut.isPending ? "Saving…" : "Save"}
                        </button>
                        <button
                          className="btn-ghost ml-2 px-3 py-1.5"
                          onClick={cancelEdit}
                          disabled={mut.isPending}
                        >
                          Cancel
                        </button>
                      </td>
                    </tr>
                  ) : (
                    <tr key={p.id}>
                      <td className="p-3">
                        {p.name}
                        {p.is_primary && (
                          <span className="chip-token ml-2 text-[11px]">primary</span>
                        )}
                      </td>
                      <td className="p-3">{p.age ?? "—"}</td>
                      <td className="p-3">{p.phone || "—"}</td>
                      <td className="p-3">{p.last_doctor || "—"}</td>
                      <td className="whitespace-nowrap p-3">
                        <button
                          className="btn-ghost px-3 py-1.5"
                          onClick={() => startEdit(p)}
                        >
                          Edit
                        </button>
                        <button
                          className="btn-danger ml-2 px-3 py-1.5"
                          onClick={() => setDeleting(p)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}


function UpcomingAppointments({ branchId }) {
  const [doctorId, setDoctorId] = useState("");
  const [onDate, setOnDate] = useState("");

  const { data: doctorsRaw } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const doctors = Array.isArray(doctorsRaw) ? doctorsRaw : doctorsRaw?.doctors ?? [];

  const { data, isLoading } = useQuery({
    queryKey: ["upcoming", branchId, doctorId, onDate],
    queryFn: () => fetchUpcoming(branchId, { doctorId: doctorId || undefined, onDate: onDate || undefined, days: 15 }),
    enabled: Boolean(branchId)
  });
  const appts = data?.appointments ?? [];

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center gap-3 border-b border-hairline bg-teal-mint/60 px-4 py-3">
        <h2 className="font-display text-lg font-semibold">Upcoming appointments · next 15 days</h2>
        <span className="chip-muted">{appts.length}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select className="field h-9 py-1 text-sm" value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
            <option value="">All doctors</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <input type="date" className="field h-9 w-40 py-1 text-sm" value={onDate}
            onChange={(e) => setOnDate(e.target.value)} />
          {onDate && (
            <button className="btn-ghost h-9 px-3 text-xs" onClick={() => setOnDate("")}>Clear date</button>
          )}
        </div>
      </header>
      {isLoading ? (
        <p className="px-4 py-6 font-ui text-sm text-slate">Loading…</p>
      ) : appts.length === 0 ? (
        <p className="px-4 py-6 font-ui text-sm text-slate">No appointments in this window.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-ui text-sm">
            <thead>
              <tr className="text-left text-slate">
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Time / Token</th>
                <th className="px-4 py-2 font-medium">Patient</th>
                <th className="px-4 py-2 font-medium">Doctor</th>
              </tr>
            </thead>
            <tbody>
              {appts.map((a, i) => (
                <tr key={i} className="border-t border-hairline">
                  <td className="whitespace-nowrap px-4 py-2 numeral tabular-nums">
                    {new Date(a.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2">
                    {a.time
                      ? new Date(`2000-01-01T${a.time}`).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
                      : `Token ${a.token_number ?? "—"}`}
                  </td>
                  <td className="px-4 py-2 font-medium">{a.patient_name}</td>
                  <td className="px-4 py-2">{a.doctor_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
