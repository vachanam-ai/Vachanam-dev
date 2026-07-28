import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createDoctor,
  deleteDoctor,
  fetchDoctorSchedules,
  fetchDoctors,
  fetchTodayQueue,
  publishDoctorSchedule,
  stopWalkinsToday,
  updateDoctor
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { fetchUpcoming } from "../api/patients.js";
import { revealStagger } from "../lib/motion.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // ISO 0-6

const EMPTY_DOCTOR = {
  name: "",
  specialization: "",
  booking_type: "token",
  schedule_mode: "recurring",
  recurring_schedule: {},
  daily_token_limit: 50,
  working_hours_start: "09:00",
  working_hours_end: "17:00",
  slot_duration_minutes: 15,
  available_weekdays: [0, 1, 2, 3, 4, 5], // Mon-Sat default (Indian clinics)
  google_calendar_id: ""
};

const localISO = (value) => {
  const d = new Date(value);
  const offset = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 10);
};

const scheduleForForm = (doctor) => {
  if (doctor?.recurring_schedule && Object.keys(doctor.recurring_schedule).length) {
    return doctor.recurring_schedule;
  }
  const days = doctor?.available_weekdays ?? [0, 1, 2, 3, 4, 5];
  const start = doctor?.working_hours_start?.slice(0, 5) ?? "09:00";
  const end = doctor?.working_hours_end?.slice(0, 5) ?? "17:00";
  return Object.fromEntries(days.map((day) => [String(day), [{ start, end }]]));
};

function SessionsEditor({ sessions, onChange }) {
  const update = (index, key, value) =>
    onChange(sessions.map((session, i) => i === index ? { ...session, [key]: value } : session));
  return (
    <div className="space-y-2">
      {sessions.map((session, index) => (
        <div key={index} className="flex items-center gap-2">
          <input className="field" type="time" value={session.start}
            onChange={(e) => update(index, "start", e.target.value)} />
          <span className="text-slate">to</span>
          <input className="field" type="time" value={session.end}
            onChange={(e) => update(index, "end", e.target.value)} />
          {sessions.length > 1 && (
            <button type="button" className="btn-ghost px-3" onClick={() => onChange(sessions.filter((_, i) => i !== index))}>
              Remove
            </button>
          )}
        </div>
      ))}
      <button type="button" className="btn-ghost px-3 py-1.5 text-sm"
        onClick={() => onChange([...sessions, { start: "17:00", end: "21:00" }])}>
        + Add another session
      </button>
    </div>
  );
}

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
          schedule_mode: initial.schedule_mode ?? "recurring",
          recurring_schedule: scheduleForForm(initial),
          available_weekdays: initial.available_weekdays ?? [0, 1, 2, 3, 4, 5],
          google_calendar_id: initial.google_calendar_id ?? ""
        }
      : { ...EMPTY_DOCTOR, recurring_schedule: scheduleForForm(null) }
  );
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));
  const isToken = f.booking_type === "token";

  const create = useMutation({
    mutationFn: () => {
      const payload = {
        name: f.name.trim(),
        specialization: f.specialization.trim() || null,
        booking_type: f.booking_type,
        schedule_mode: f.schedule_mode,
        recurring_schedule: f.schedule_mode === "recurring" ? f.recurring_schedule : {},
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
      if (!isEdit) setF({ ...EMPTY_DOCTOR, recurring_schedule: scheduleForForm(null) });
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
        <label className="label">How is this doctor&apos;s schedule published?</label>
        <div className="flex gap-2">
          {[["recurring", "Repeats weekly"], ["date_specific", "Different every date"]].map(([value, label]) => (
            <button type="button" key={value}
              onClick={() => setF((s) => ({ ...s, schedule_mode: value }))}
              className={`flex-1 rounded-xl border px-4 py-2.5 font-ui text-sm font-medium ${
                f.schedule_mode === value ? "border-teal bg-teal-mint" : "border-hairline bg-surface"
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {f.schedule_mode === "recurring" ? (
        <div className="sm:col-span-2 space-y-4">
          <p className="font-ui text-xs text-slate">Each weekday can have several separate sessions. Breaks remain unavailable.</p>
          {WEEKDAYS.map((label, day) => {
            const sessions = f.recurring_schedule?.[String(day)] ?? [];
            const enabled = sessions.length > 0;
            return (
              <div key={label} className="rounded-xl border border-hairline p-3">
                <label className="mb-2 flex items-center gap-2 font-ui text-sm font-medium">
                  <input type="checkbox" checked={enabled} onChange={(e) => setF((state) => ({
                    ...state,
                    available_weekdays: e.target.checked
                      ? [...new Set([...state.available_weekdays, day])].sort()
                      : state.available_weekdays.filter((value) => value !== day),
                    recurring_schedule: {
                      ...state.recurring_schedule,
                      [String(day)]: e.target.checked ? [{ start: "09:00", end: "17:00" }] : []
                    }
                  }))} />
                  {label}
                </label>
                {enabled && <SessionsEditor sessions={sessions} onChange={(next) => setF((state) => ({
                  ...state,
                  recurring_schedule: { ...state.recurring_schedule, [String(day)]: next }
                }))} />}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="sm:col-span-2 rounded-xl border border-gold/40 bg-gold-soft p-4 font-ui text-sm text-slate">
          No schedule is assumed. Publish every exact date below; until then the voice agent says “timing not confirmed yet” and refuses bookings.
        </div>
      )}
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

function DateSchedulePublisher({ branchId, doctor }) {
  const qc = useQueryClient();
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const [selectedDate, setSelectedDate] = useState(localISO(tomorrow));
  const [sessions, setSessions] = useState([
    { start: "09:00", end: "12:00" },
    { start: "17:00", end: "21:00" }
  ]);
  const [tokenLimit, setTokenLimit] = useState(doctor.daily_token_limit ?? 50);
  const [notes, setNotes] = useState("");
  const rangeStart = localISO(new Date());
  const rangeEndDate = new Date();
  rangeEndDate.setDate(rangeEndDate.getDate() + 14);
  const rangeEnd = localISO(rangeEndDate);

  const { data: dates = [] } = useQuery({
    queryKey: ["doctor-schedules", branchId, doctor.id, rangeStart, rangeEnd],
    queryFn: () => fetchDoctorSchedules(branchId, doctor.id, rangeStart, rangeEnd),
    enabled: Boolean(branchId && doctor.id)
  });
  const publish = useMutation({
    mutationFn: () => publishDoctorSchedule(branchId, doctor.id, selectedDate, {
      sessions,
      token_limit: doctor.booking_type === "token" ? Number(tokenLimit) : null,
      notes: notes.trim() || null
    }),
    onSuccess: () => {
      toast.success(`${doctor.name}'s ${selectedDate} schedule published`);
      qc.invalidateQueries({ queryKey: ["doctor-schedules", branchId, doctor.id] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not publish schedule")
  });

  return (
    <div className="mt-5 border-t border-hairline pt-5">
      <div className="mb-3">
        <h3 className="font-display text-lg font-semibold">Publish an exact date</h3>
        <p className="font-ui text-xs text-slate">This exact-date entry overrides any weekly pattern. Empty sessions explicitly mark the doctor unavailable.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">Date</label>
          <input className="field" type="date" min={rangeStart} value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)} />
        </div>
        {doctor.booking_type === "token" && (
          <div>
            <label className="label">Token limit for this date</label>
            <input className="field" type="number" min={1} max={500} value={tokenLimit}
              onChange={(e) => setTokenLimit(e.target.value)} />
          </div>
        )}
        <div className="sm:col-span-2">
          <label className="label">Sessions</label>
          {sessions.length ? (
            <SessionsEditor sessions={sessions} onChange={setSessions} />
          ) : (
            <p className="rounded-lg bg-gold-soft p-3 font-ui text-sm">No sessions: this publishes the doctor as unavailable.</p>
          )}
          <button type="button" className="btn-ghost mt-2 px-3 py-1.5 text-sm"
            onClick={() => setSessions(sessions.length ? [] : [{ start: "09:00", end: "12:00" }])}>
            {sessions.length ? "Mark unavailable all day" : "Add a session"}
          </button>
        </div>
        <div className="sm:col-span-2">
          <label className="label">Internal note (optional)</label>
          <input className="field" value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="Schedule shared by doctor at 7pm" />
        </div>
      </div>
      <button className="btn-primary mt-4" disabled={publish.isPending} onClick={() => publish.mutate()}>
        {publish.isPending ? "Publishing…" : "Publish exact schedule"}
      </button>

      <div className="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {dates.map((entry) => (
          <button key={entry.date} type="button" onClick={() => {
            setSelectedDate(entry.date);
            if (entry.is_published) {
              setSessions(entry.sessions);
              setTokenLimit(entry.token_limit ?? doctor.daily_token_limit ?? 50);
              setNotes(entry.notes ?? "");
            }
          }} className="rounded-xl border border-hairline p-3 text-left">
            <p className="font-ui text-xs font-semibold uppercase tracking-wide text-slate">{entry.date}</p>
            <p className={`mt-1 font-ui text-sm ${entry.status === "unpublished" ? "text-gold-deep" : "text-ink"}`}>
              {entry.status === "unpublished"
                ? "Not published"
                : entry.sessions.length
                  ? entry.sessions.map((s) => `${s.start}–${s.end}`).join(" · ")
                  : entry.source === "leave" ? "On leave" : "Unavailable"}
            </p>
            <p className="mt-1 font-ui text-[11px] text-slate">{entry.source.replace("_", " ")}</p>
          </button>
        ))}
      </div>
    </div>
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
                  <span className="font-ui text-xs text-slate">
                    {d.schedule_mode === "date_specific" ? "Exact-date schedules" : "Recurring multi-session schedule"}
                  </span>
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

            <DateSchedulePublisher branchId={branchId} doctor={d} />

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


function MyUpcomingPatients({ branchId }) {
  const { data, isLoading } = useQuery({
    queryKey: ["my-upcoming", branchId],
    queryFn: () => fetchUpcoming(branchId, { days: 30 }),
    enabled: Boolean(branchId)
  });
  const appts = data?.appointments ?? [];
  return (
    <section data-reveal className="card overflow-hidden">
      <header className="flex items-center gap-3 border-b border-hairline bg-teal-mint/60 px-4 py-3">
        <h2 className="font-display text-lg font-semibold">My patients · next 30 days</h2>
        <span className="chip-muted">{appts.length}</span>
      </header>
      {isLoading ? (
        <p className="px-4 py-6 font-ui text-sm text-slate">Loading…</p>
      ) : appts.length === 0 ? (
        <p className="px-4 py-6 font-ui text-sm text-slate">No upcoming patients.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-ui text-sm">
            <thead>
              <tr className="text-left text-slate">
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Time / Token</th>
                <th className="px-4 py-2 font-medium">Patient</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
