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
import QuestionsCard from "../components/QuestionsCard.jsx";
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
  available_weekdays: [0, 1, 2, 3, 4, 5] // Mon-Sat default (Indian clinics)
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
          available_weekdays: initial.available_weekdays ?? [0, 1, 2, 3, 4, 5]
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
        available_weekdays: f.available_weekdays
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
      {/* Per-doctor Google Calendar removed 2026-08-03 (Vinay): one calendar per
          clinic. Doctors see their own appointments in their dashboard account
          instead. A doctor-level calendar the service account could not write to
          silently rolled back the booking that depended on it. */}
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

const shortT = (t) => (t || "").replace(/^0/, "").replace(":00", "");

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
  const [showForm, setShowForm] = useState(false);
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
      setShowForm(false);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not publish schedule")
  });

  // Weekday + day only ("Wed 29") — month shown just when it rolls over, to
  // keep chips one line. Load a chip into the form on click (opens the form).
  const loadDate = (entry) => {
    setSelectedDate(entry.date);
    if (entry.is_published) {
      setSessions(entry.sessions);
      setTokenLimit(entry.token_limit ?? doctor.daily_token_limit ?? 50);
      setNotes(entry.notes ?? "");
    }
    setShowForm(true);
  };

  return (
    <div>
      {/* Compact 15-day availability strip — the default view. */}
      <div className="mb-2 flex items-center justify-between">
        <p className="label mb-0">Next 15 days</p>
        <button type="button" onClick={() => setShowForm((v) => !v)}
          className="font-ui text-xs font-semibold text-ink underline-offset-4 hover:underline">
          {showForm ? "Hide" : "＋ Publish a date"}
        </button>
      </div>
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5 lg:grid-cols-7">
        {dates.map((entry) => {
          const d = new Date(`${entry.date}T00:00:00`);
          const published = entry.status !== "unpublished";
          const open = published && entry.sessions.length > 0;
          const dot = open ? "var(--good)" : entry.source === "leave" ? "var(--warn)"
            : published ? "var(--slate)" : "var(--faint, #b7b8b4)";
          const hrs = !published ? "—"
            : entry.sessions.length ? entry.sessions.map((s) => `${shortT(s.start)}–${shortT(s.end)}`).join(" ")
            : entry.source === "leave" ? "Leave" : "Closed";
          return (
            <button key={entry.date} type="button" onClick={() => loadDate(entry)}
              title={hrs}
              className={`rounded-lg border px-2 py-1.5 text-left transition hover:border-line2 ${
                selectedDate === entry.date && showForm ? "border-accent bg-pill" : "border-hairline"
              }`}>
              <div className="flex items-center justify-between gap-1">
                <span className="font-ui text-[11px] font-semibold text-ink">
                  {d.toLocaleDateString("en-IN", { weekday: "short" })} {d.getDate()}
                </span>
                <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: dot }} />
              </div>
              <p className="mt-0.5 truncate font-ui text-[10.5px] leading-tight text-slate">{hrs}</p>
            </button>
          );
        })}
      </div>

      {/* Publish/override form — on demand only, so it never dominates the card. */}
      {showForm && (
        <div className="mt-3 rounded-xl border border-hairline bg-pill/40 p-3 sm:p-4">
          <p className="font-ui text-xs text-slate">Overrides the weekly pattern for one date. Empty sessions = unavailable.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Date</label>
              <input className="field" type="date" min={rangeStart} value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)} />
            </div>
            {doctor.booking_type === "token" && (
              <div>
                <label className="label">Token limit</label>
                <input className="field" type="number" min={1} max={500} value={tokenLimit}
                  onChange={(e) => setTokenLimit(e.target.value)} />
              </div>
            )}
            <div className="sm:col-span-2">
              <label className="label">Sessions</label>
              {sessions.length ? (
                <SessionsEditor sessions={sessions} onChange={setSessions} />
              ) : (
                <p className="rounded-lg bg-band p-3 font-ui text-sm text-ink-soft">No sessions: publishes as unavailable.</p>
              )}
              <button type="button" className="btn-ghost mt-2 px-3 py-1.5 text-xs"
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
          <button className="btn-primary mt-3" disabled={publish.isPending} onClick={() => publish.mutate()}>
            {publish.isPending ? "Publishing…" : "Publish this date"}
          </button>
        </div>
      )}
    </div>
  );
}

/* "Mon Tue Wed · 9–17" one-line summary of the doctor's weekly pattern. */
function timingSummary(doctor) {
  const sched = scheduleForForm(doctor);
  const days = Object.keys(sched).map(Number).filter((d) => (sched[String(d)] || []).length).sort((a, b) => a - b);
  if (!days.length) return "No weekly schedule set";
  const first = sched[String(days[0])][0];
  const hrs = first ? `${shortT(first.start)}–${shortT(first.end)}` : "";
  return `${days.map((d) => WEEKDAYS[d]).join(" ")}${hrs ? ` · ${hrs}` : ""}`;
}

/** One doctor as a compact card. Clicking Edit expands the card horizontally
 *  (GSAP, driven from DoctorsBoard) and fades in the day-wise editor + exact-
 *  date publisher; the other cards compress to make room. */
function DoctorCard({ doctor, id, waiting, role, branchId, expanded, onToggle, onChanged, setRef }) {
  const qc = useQueryClient();
  const editorRef = useRef(null);
  const isAdmin = role === "org_admin";

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

  // Fade the day-wise editor in AFTER the horizontal expand settles.
  useEffect(() => {
    if (!expanded || !editorRef.current) return;
    let cancelled = false;
    import("gsap").then(({ gsap }) => {
      if (cancelled || !editorRef.current) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      gsap.fromTo(editorRef.current, { opacity: 0, y: 8 },
        { opacity: 1, y: 0, duration: reduce ? 0 : 0.4, delay: reduce ? 0 : 0.28, ease: "power2.out" });
    });
    return () => { cancelled = true; };
  }, [expanded]);

  return (
    <div ref={setRef} data-docid={id} style={{ flexGrow: 1 }} className="min-w-0 md:basis-0">
      <section data-reveal className={`card overflow-hidden ${expanded ? "ring-1 ring-accent/40" : ""}`}>
        <div className="flex items-start gap-3 p-4">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-line2 bg-pill font-ui text-sm font-semibold text-ink-soft">
            {initials(doctor.name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-ui text-base font-semibold text-ink">{doctor.name}</p>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className={doctor.booking_type === "token" ? "chip-token" : "chip-slot"}>
                {doctor.booking_type === "token" ? "token queue" : "appointments"}
              </span>
              {doctor.specialization && <span className="truncate font-ui text-xs text-slate">{doctor.specialization}</span>}
            </div>
            <p className="mt-1.5 truncate font-ui text-xs text-slate" title={timingSummary(doctor)}>
              {timingSummary(doctor)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="numeral text-2xl text-ink">{waiting}</p>
            <p className="font-ui text-[10px] uppercase tracking-[0.12em] text-slate">waiting</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-hairline px-4 py-3">
          <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={onToggle}>
            {expanded ? "Close" : isAdmin ? "Edit" : "Manage dates"}
          </button>
          {isAdmin && doctor.booking_type === "token" && (
            <button onClick={() => stop.mutate()} disabled={stop.isPending} className="btn-gold px-3 py-1.5 text-sm">
              Stop walk-ins today
            </button>
          )}
          {isAdmin && (
            <button className="btn-danger px-3 py-1.5 text-sm" disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Remove ${doctor.name}? Patients can no longer be booked with them; past bookings stay.`)) {
                  remove.mutate();
                }
              }}>
              Remove
            </button>
          )}
        </div>

        {expanded && (
          <div ref={editorRef} className="space-y-4 border-t border-hairline p-4">
            {isAdmin && (
              <div className="rounded-2xl border border-hairline bg-pill/40 p-4 sm:p-5">
                <AddDoctorForm branchId={branchId} doctorId={id} initial={doctor}
                  onCancel={onToggle}
                  onDone={() => { onToggle(); qc.invalidateQueries({ queryKey: ["doctors", branchId] }); }} />
              </div>
            )}
            <DateSchedulePublisher branchId={branchId} doctor={doctor} />
          </div>
        )}
      </section>
    </div>
  );
}

/** Side-by-side doctor board. One editing card grows and the others compress,
 *  animated with GSAP flex-grow tweens (instant under reduced-motion). */
function DoctorsBoard({ doctors, queue, role, branchId, onChanged }) {
  const [editingId, setEditingId] = useState(null);
  const cardRefs = useRef({});
  const setRef = (id) => (el) => { if (el) cardRefs.current[id] = el; else delete cardRefs.current[id]; };

  useEffect(() => {
    let cancelled = false;
    import("gsap").then(({ gsap }) => {
      if (cancelled) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      for (const d of doctors) {
        const id = d.id ?? d.doctor_id;
        const el = cardRefs.current[id];
        if (!el) continue;
        const target = editingId ? (id === editingId ? 2.6 : 0.7) : 1;
        gsap.to(el, { flexGrow: target, duration: reduce ? 0 : 0.5, ease: "power3.out" });
      }
    });
    return () => { cancelled = true; };
  }, [editingId, doctors.length]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start">
      {doctors.map((d) => {
        const id = d.id ?? d.doctor_id;
        const todayEntry = queue?.doctors?.find((q) => q.doctor_id === id);
        const waiting = todayEntry?.patients?.filter((p) => p.status === "confirmed").length ?? 0;
        return (
          <DoctorCard key={id} doctor={d} id={id} waiting={waiting} role={role} branchId={branchId}
            expanded={editingId === id} onChanged={onChanged} setRef={setRef(id)}
            onToggle={() => setEditingId((cur) => (cur === id ? null : id))} />
        );
      })}
    </div>
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
    // On `doctors`, not its length: editing a doctor re-renders its card
    // without changing the count, and the new card would stay invisible.
  }, [doctors]);

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

      {/* Patient questions waiting on the doctor's answer (2026-08-02) — the
          same card the owner sees on the Dashboard; hidden when there are none. */}
      <QuestionsCard branchId={branchId} />

      {visible.length > 0 && (
        <DoctorsBoard doctors={visible} queue={queue} role={role}
          branchId={branchId} onChanged={invalidate} />
      )}

      {visible.length === 0 && role !== "org_admin" && (
        <p className="font-ui text-sm text-slate">No doctor profile linked to your account yet.</p>
      )}
    </div>
  );
}
