import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createDoctor,
  deleteDoctor,
  fetchDoctors,
  fetchTodayQueue,
  stopWalkinsToday,
  updateDoctor
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // ISO 0-6

const EMPTY_DOCTOR = {
  name: "",
  specialization: "",
  booking_type: "token",
  daily_token_limit: 50,
  working_hours_start: "09:00",
  working_hours_end: "17:00",
  slot_duration_minutes: 15,
  available_weekdays: [0, 1, 2, 3, 4, 5], // Mon-Sat default (Indian clinics)
  google_calendar_id: ""
};

function WeekdayPicker({ value, onChange }) {
  const toggle = (i) =>
    onChange(value.includes(i) ? value.filter((d) => d !== i) : [...value, i].sort());
  return (
    <div className="flex flex-wrap gap-1.5">
      {WEEKDAYS.map((label, i) => (
        <button type="button" key={label} onClick={() => toggle(i)}
          className={`h-10 w-12 rounded-lg border font-ui text-sm font-medium transition ${
            value.includes(i)
              ? "border-teal bg-teal text-white"
              : "border-hairline bg-surface text-slate hover:border-teal-light/60"
          }`}>
          {label}
        </button>
      ))}
    </div>
  );
}

const fmtDays = (days) => {
  if (!days?.length || days.length === 7) return "Every day";
  return days.map((d) => WEEKDAYS[d]).join(" · ");
};

function AddDoctorForm({ branchId, onDone, initial = null, doctorId = null, onCancel }) {
  const isEdit = Boolean(doctorId);
  const [f, setF] = useState(
    initial
      ? {
          ...EMPTY_DOCTOR,
          ...initial,
          working_hours_start: initial.working_hours_start?.slice(0, 5) ?? "09:00",
          working_hours_end: initial.working_hours_end?.slice(0, 5) ?? "17:00",
          specialization: initial.specialization ?? "",
          daily_token_limit: initial.daily_token_limit ?? 50,
          slot_duration_minutes: initial.slot_duration_minutes ?? 15,
          available_weekdays: initial.available_weekdays ?? [0, 1, 2, 3, 4, 5],
          google_calendar_id: initial.google_calendar_id ?? ""
        }
      : EMPTY_DOCTOR
  );
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));
  const isToken = f.booking_type === "token";

  const create = useMutation({
    mutationFn: () => {
      const payload = {
        name: f.name.trim(),
        specialization: f.specialization.trim() || null,
        booking_type: f.booking_type,
        daily_token_limit: isToken ? Number(f.daily_token_limit) : null,
        working_hours_start: f.working_hours_start || null,
        working_hours_end: f.working_hours_end || null,
        slot_duration_minutes: isToken ? null : Number(f.slot_duration_minutes),
        available_weekdays: f.available_weekdays,
        google_calendar_id: f.google_calendar_id.trim() || null
      };
      return isEdit ? updateDoctor(branchId, doctorId, payload) : createDoctor(branchId, payload);
    },
    onSuccess: (d) => {
      toast.success(isEdit ? `${d.name} updated` : `${d.name} added`);
      if (!isEdit) setF(EMPTY_DOCTOR);
      onDone();
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not save doctor")
  });

  return (
    <form
      className="card grid gap-4 p-6 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="sm:col-span-2">
        <h2 className="font-display text-lg font-semibold">{isEdit ? `Edit ${f.name || "doctor"}` : "Add a doctor"}</h2>
        <p className="font-ui text-sm text-slate">
          Token queue = numbered walk-in line (high-volume). Appointments = fixed time slots.
        </p>
      </div>
      <div>
        <label className="label">Doctor name</label>
        <input className="field" required value={f.name} onChange={set("name")} placeholder="Dr. Srinivas" />
      </div>
      <div>
        <label className="label">Specialization</label>
        <input className="field" value={f.specialization} onChange={set("specialization")} placeholder="dental, skin…" />
      </div>
      <div className="sm:col-span-2">
        <label className="label">Booking style</label>
        <div className="flex gap-2">
          {[["token", "Token queue"], ["appointment", "Time slots"]].map(([v, l]) => (
            <button type="button" key={v} onClick={() => setF((s) => ({ ...s, booking_type: v }))}
              className={`flex-1 rounded-xl border px-4 py-2.5 font-ui text-sm font-medium transition ${
                f.booking_type === v
                  ? v === "token" ? "border-teal bg-teal-mint" : "border-gold bg-gold-soft"
                  : "border-hairline bg-surface hover:border-teal-light/60"
              }`}>
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="sm:col-span-2">
        <label className="label">Available days</label>
        <WeekdayPicker
          value={f.available_weekdays}
          onChange={(days) => setF((s) => ({ ...s, available_weekdays: days }))}
        />
      </div>
      <div>
        <label className="label">Hours start</label>
        <input className="field" type="time" value={f.working_hours_start} onChange={set("working_hours_start")} />
      </div>
      <div>
        <label className="label">Hours end</label>
        <input className="field" type="time" value={f.working_hours_end} onChange={set("working_hours_end")} />
      </div>
      {isToken ? (
        <div>
          <label className="label">Daily token limit</label>
          <input className="field" type="number" min={1} max={500}
            value={f.daily_token_limit} onChange={set("daily_token_limit")} />
        </div>
      ) : (
        <div>
          <label className="label">Slot length (minutes)</label>
          <input className="field" type="number" min={5} max={240}
            value={f.slot_duration_minutes} onChange={set("slot_duration_minutes")} />
        </div>
      )}
      <div className="sm:col-span-2">
        <label className="label">Doctor's own Google Calendar ID (optional)</label>
        <input className="field" value={f.google_calendar_id} onChange={set("google_calendar_id")}
          placeholder="doctor.name@gmail.com or abc123…@group.calendar.google.com" />
        <p className="mt-1 font-ui text-xs text-slate">
          Give each doctor their own calendar so one doctor's bookings don't appear on
          everyone's schedule. Share that calendar with the clinic's service account
          (same steps as in Settings → Google Calendar), then paste its ID here. Left
          empty, this doctor's events go to the clinic-wide calendar.
        </p>
      </div>
      <div className="flex gap-3 sm:col-span-2">
        <button className="btn-primary flex-1" disabled={create.isPending}>
          {create.isPending ? "Saving…" : isEdit ? "Save changes" : "Add doctor"}
        </button>
        {isEdit && (
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

export default function DoctorSchedule() {
  const { branchId, user, role } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);
  const [editingId, setEditingId] = useState(null);

  const { data: doctorsRaw } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const { data: queue } = useQuery({
    queryKey: ["queue", branchId],
    queryFn: () => fetchTodayQueue(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 30_000
  });

  const doctors = Array.isArray(doctorsRaw) ? doctorsRaw : doctorsRaw?.doctors ?? [];
  // A doctor user sees their own card (matched by linked user) or all if unmatched
  const mine =
    doctors.filter((d) => d.user_id === user?.user_id || d.invited_email === user?.email);
  const visible = mine.length ? mine : doctors;

  useEffect(() => {
    if (doctors.length) revealStagger(pageRef.current);
  }, [doctors.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useMutation({
    mutationFn: (doctorId) => stopWalkinsToday(doctorId, branchId),
    onSuccess: () => {
      toast.success("Walk-ins closed for today");
      qc.invalidateQueries({ queryKey: ["doctors", branchId] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not close walk-ins")
  });

  const remove = useMutation({
    mutationFn: (doctorId) => deleteDoctor(branchId, doctorId),
    onSuccess: () => {
      toast.success("Doctor removed (bookings history is kept)");
      qc.invalidateQueries({ queryKey: ["doctors", branchId] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not remove doctor")
  });

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal>
        <p className="eyebrow">Doctor</p>
        <h1 className="section-title text-2xl">My schedule</h1>
      </div>

      {visible.map((d) => {
        const id = d.id ?? d.doctor_id;
        const todayEntry = queue?.doctors?.find((q) => q.doctor_id === id);
        const waiting = todayEntry?.patients?.filter((p) => p.status === "confirmed").length ?? 0;
        return (
          <section key={id} data-reveal className="card p-6">
            <div className="flex flex-wrap items-start gap-4">
              <div className="min-w-0 flex-1">
                <h2 className="font-display text-xl font-semibold">{d.name}</h2>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className={d.booking_type === "token" ? "chip-token" : "chip-slot"}>
                    {d.booking_type === "token" ? "token queue" : "appointments"}
                  </span>
                  {d.working_hours_start && (
                    <span className="font-ui text-sm text-slate tabular-nums">
                      {d.working_hours_start}–{d.working_hours_end}
                    </span>
                  )}
                  <span className="font-ui text-xs text-slate">{fmtDays(d.available_weekdays)}</span>
                </div>
              </div>
              <div className="text-center">
                <p className="numeral text-5xl text-teal-deep">{waiting}</p>
                <p className="font-ui text-xs uppercase tracking-[0.14em] text-slate">waiting now</p>
              </div>
            </div>

            {role === "org_admin" && (
              <div className="mt-4 flex gap-2 border-t border-hairline pt-4">
                <button
                  className="btn-ghost px-3 py-1.5 text-sm"
                  onClick={() => setEditingId(editingId === id ? null : id)}
                >
                  {editingId === id ? "Close editor" : "Edit"}
                </button>
                <button
                  className="btn-danger px-3 py-1.5 text-sm"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove ${d.name}? Patients can no longer be booked with them; past bookings stay.`)) {
                      remove.mutate(id);
                    }
                  }}
                >
                  Remove
                </button>
              </div>
            )}

            {editingId === id && (
              <div className="mt-4">
                <AddDoctorForm
                  branchId={branchId}
                  doctorId={id}
                  initial={d}
                  onCancel={() => setEditingId(null)}
                  onDone={() => {
                    setEditingId(null);
                    qc.invalidateQueries({ queryKey: ["doctors", branchId] });
                  }}
                />
              </div>
            )}

            {d.booking_type === "token" && (
              <div className="mt-5 border-t border-hairline pt-4">
                <button
                  onClick={() => stop.mutate(id)}
                  disabled={stop.isPending}
                  className="btn-gold"
                >
                  Stop walk-ins for today
                </button>
                <p className="mt-2 font-ui text-xs text-slate">
                  Patients already holding tokens keep them; the desk can&rsquo;t add new walk-ins.
                </p>
              </div>
            )}
          </section>
        );
      })}

      {visible.length === 0 && role !== "org_admin" && (
        <p className="font-ui text-sm text-slate">No doctor profile linked to your account yet.</p>
      )}

      {role === "org_admin" && (
        <AddDoctorForm
          branchId={branchId}
          onDone={() => qc.invalidateQueries({ queryKey: ["doctors", branchId] })}
        />
      )}
    </div>
  );
}
