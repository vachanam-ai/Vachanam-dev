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

const initials = (name) => {
  const parts = (name ?? "").replace(/^dr\.?\s*/i, "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "Dr";
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

function Chevron({ open }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden
      className={`shrink-0 text-slate transition-transform duration-200 ${open ? "rotate-180" : ""}`}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

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

  // Segmented control cell — selected = accent border + pill fill (monochrome).
  const seg = (active) =>
    `flex-1 rounded-xl border px-4 py-2.5 font-ui text-sm font-medium transition ${
      active ? "border-accent bg-pill text-ink" : "border-hairline bg-surface text-ink-soft hover:border-line2"
    }`;

  return (
    <form
      className="grid gap-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      {!isEdit && (
        <div className="sm:col-span-2">
          <p className="font-ui text-sm text-slate">
            Token queue = numbered walk-in line (high-volume). Appointments = fixed time slots.
          </p>
        </div>
      )}
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
              className={seg(f.booking_type === v)}>
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
              className={seg(f.schedule_mode === value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {f.schedule_mode === "recurring" ? (
        <div className="sm:col-span-2 space-y-3">
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
        <div className="sm:col-span-2 rounded-xl border border-hairline bg-band/60 p-4 font-ui text-sm text-ink-soft">
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
        {onCancel && (
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

  const fmtDay = (iso) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" });

  return (
    <div>
      <div className="mb-3">
        <h3 className="section-title">Publish an exact date</h3>
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
            <p className="rounded-lg bg-band p-3 font-ui text-sm text-ink-soft">No sessions: this publishes the doctor as unavailable.</p>
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

      {/* Next 15 days — compact chips, click to load that date into the form. */}
      <div className="mt-5">
        <p className="label">Next 15 days</p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {dates.map((entry) => {
            const published = entry.status !== "unpublished";
            const busy = published && entry.sessions.length > 0;
            return (
              <button key={entry.date} type="button"
                onClick={() => {
                  setSelectedDate(entry.date);
                  if (entry.is_published) {
                    setSessions(entry.sessions);
                    setTokenLimit(entry.token_limit ?? doctor.daily_token_limit ?? 50);
                    setNotes(entry.notes ?? "");
                  }
                }}
                className={`rounded-xl border p-3 text-left transition hover:border-line2 ${
                  selectedDate === entry.date ? "border-accent bg-pill" : "border-hairline"
                }`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="font-ui text-xs font-semibold text-ink">{fmtDay(entry.date)}</p>
                  <span className={busy ? "tag tag-good" : published ? "tag tag-warn" : "tag tag-crit"}>
                    {busy ? "open" : entry.source === "leave" ? "leave" : published ? "closed" : "—"}
                  </span>
                </div>
                <p className="mt-1 font-ui text-sm text-ink-soft">
                  {!published
                    ? "Not published"
                    : entry.sessions.length
                      ? entry.sessions.map((s) => `${s.start}–${s.end}`).join(" · ")
                      : entry.source === "leave" ? "On leave" : "Unavailable"}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** One doctor as a collapsed summary row that expands to reveal the editor +
 *  exact-date publisher. Only the header renders until opened — this is what
 *  keeps the page short (it was ~6700px with every publisher always open). */
function DoctorAccordion({ doctor, id, waiting, role, branchId, onChanged }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);

  const stop = useMutation({
    mutationFn: () => stopWalkinsToday(id, branchId),
    onSuccess: () => { toast.success("Walk-ins closed for today"); onChanged(); },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not close walk-ins")
  });
  const remove = useMutation({
    mutationFn: () => deleteDoctor(branchId, id),
    onSuccess: () => { toast.success("Doctor removed (bookings history is kept)"); onChanged(); },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not remove doctor")
  });

  return (
    <section data-reveal className="card overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-4 p-4 text-left transition-colors hover:bg-pill/50">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-line2 bg-pill font-ui text-sm font-semibold text-ink-soft">
          {initials(doctor.name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-ui text-base font-semibold text-ink">{doctor.name}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={doctor.booking_type === "token" ? "chip-token" : "chip-slot"}>
              {doctor.booking_type === "token" ? "token queue" : "appointments"}
            </span>
            {doctor.specialization && <span className="font-ui text-xs text-slate">{doctor.specialization}</span>}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="numeral text-2xl text-ink">{waiting}</p>
          <p className="font-ui text-[10px] uppercase tracking-[0.12em] text-slate">waiting</p>
        </div>
        <Chevron open={open} />
      </button>

      {open && (
        <div className="space-y-5 border-t border-hairline p-4 sm:p-6">
          {role === "org_admin" && (
            <div className="flex flex-wrap gap-2">
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setEditing((e) => !e)}>
                {editing ? "Close editor" : "Edit details"}
              </button>
              {doctor.booking_type === "token" && (
                <button onClick={() => stop.mutate()} disabled={stop.isPending} className="btn-gold px-3 py-1.5 text-sm">
                  Stop walk-ins today
                </button>
              )}
              <button className="btn-danger px-3 py-1.5 text-sm" disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm(`Remove ${doctor.name}? Patients can no longer be booked with them; past bookings stay.`)) {
                    remove.mutate();
                  }
                }}>
                Remove
              </button>
            </div>
          )}

          {editing && (
            <div className="rounded-2xl border border-hairline bg-pill/40 p-4 sm:p-5">
              <AddDoctorForm branchId={branchId} doctorId={id} initial={doctor}
                onCancel={() => setEditing(false)}
                onDone={() => { setEditing(false); qc.invalidateQueries({ queryKey: ["doctors", branchId] }); }} />
            </div>
          )}

          <DateSchedulePublisher branchId={branchId} doctor={doctor} />
        </div>
      )}
    </section>
  );
}

export default function DoctorSchedule() {
  const { branchId, user, role } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);
  const [adding, setAdding] = useState(false);

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
  const mine = doctors.filter((d) => d.user_id === user?.user_id || d.invited_email === user?.email);
  const visible = mine.length ? mine : doctors;

  useEffect(() => {
    if (doctors.length) revealStagger(pageRef.current);
  }, [doctors.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const invalidate = () => qc.invalidateQueries({ queryKey: ["doctors", branchId] });

  return (
    <div ref={pageRef} className="space-y-5">
      <div data-reveal className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">{role === "doctor" ? "Doctor" : "Team"}</p>
          <h1 className="section-title text-2xl">{role === "doctor" ? "My schedule" : "Doctors & schedules"}</h1>
          <p className="mt-1 font-ui text-sm text-slate">
            {visible.length} {visible.length === 1 ? "doctor" : "doctors"} · tap a card to publish dates or edit
          </p>
        </div>
        {role === "org_admin" && (
          <button className="btn-primary" onClick={() => setAdding((a) => !a)}>
            {adding ? "Close" : "+ Add doctor"}
          </button>
        )}
      </div>

      {adding && role === "org_admin" && (
        <div data-reveal className="card p-5 sm:p-6">
          <h2 className="section-title mb-4">Add a doctor</h2>
          <AddDoctorForm branchId={branchId}
            onCancel={() => setAdding(false)}
            onDone={() => { setAdding(false); invalidate(); }} />
        </div>
      )}

      {visible.map((d) => {
        const id = d.id ?? d.doctor_id;
        const todayEntry = queue?.doctors?.find((q) => q.doctor_id === id);
        const waiting = todayEntry?.patients?.filter((p) => p.status === "confirmed").length ?? 0;
        return (
          <DoctorAccordion key={id} doctor={d} id={id} waiting={waiting} role={role}
            branchId={branchId} onChanged={invalidate} />
        );
      })}

      {visible.length === 0 && role !== "org_admin" && (
        <p className="font-ui text-sm text-slate">No doctor profile linked to your account yet.</p>
      )}
    </div>
  );
}
