import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fetchDoctors } from "../api/client.js";
import {
  listTreatmentPatients,
  listNotes,
  createNote,
  editNote,
  listFollowups,
  replyToPatient
} from "../api/treatment.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const today = () => new Date().toISOString().slice(0, 10);

// One step in the treatment timeline. `isLatest` = the newest visit: only it shows
// the pending "Next" + next-date — once a later visit records what was done, the
// prior "Next" has been performed and is no longer pending (Vinay 2026-06-24).
// `isLast` removes the connector line below the final dot.
function NoteCard({ n, isLatest, isLast, onEdit }) {
  return (
    <li className={`relative pl-6 text-left ${isLast ? "" : "pb-5"}`}>
      {/* connector line between this dot and the next */}
      {!isLast && (
        <span className="absolute left-[5px] top-3 h-full w-px bg-hairline" aria-hidden />
      )}
      {/* dot on the line */}
      <span
        className={`absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2 ${
          isLatest ? "border-teal bg-teal" : "border-teal bg-surface"
        }`}
        aria-hidden
      />
      <div className="flex w-full items-center gap-3">
        <span className="numeral text-sm text-teal-deep tabular-nums">{n.visit_date}</span>
        {n.is_final && <span className="chip-token">final</span>}
        <button
          type="button"
          onClick={() => onEdit(n)}
          className="ml-auto font-ui text-xs text-teal underline-offset-2 hover:underline"
        >
          Edit
        </button>
        {isLatest && n.next_reporting_date && (
          <span className="font-ui text-xs text-slate">next: {n.next_reporting_date}</span>
        )}
      </div>
      {n.steps_performed && (
        <p className="mt-1 font-ui text-sm">
          <span className="text-slate">Done: </span>
          {n.steps_performed}
        </p>
      )}
      {isLatest && n.next_steps && (
        <p className="mt-1 font-ui text-sm">
          <span className="text-slate">Next: </span>
          {n.next_steps}
        </p>
      )}
    </li>
  );
}

function ThreadRow({ item }) {
  const hasReply = Boolean(item.response && item.response.trim());
  const unreachable = item.status === "unreachable";
  return (
    <div className="space-y-2 px-4 py-3">
      {/* Clinic / agent message — left aligned */}
      <div className="flex flex-col items-start gap-1">
        <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-teal-mint/60 px-4 py-2">
          <p className="font-ui text-sm">{item.message}</p>
        </div>
        <div className="flex items-center gap-2 pl-1">
          <span className="font-ui text-[11px] uppercase tracking-wide text-slate">
            {(item.task_type ?? "").replace(/_/g, " ") || "follow-up"}
          </span>
          {unreachable && <span className="chip-muted text-[11px]">unreachable</span>}
          {item.status && !unreachable && (
            <span className="chip-muted text-[11px]">{item.status}</span>
          )}
        </div>
      </div>

      {/* Patient reply — right aligned, visually distinct */}
      {hasReply && (
        <div className="flex flex-col items-end gap-1">
          <div className="max-w-[85%] rounded-2xl rounded-tr-sm border border-amber-300 bg-amber-50 px-4 py-2">
            <p className="font-ui text-sm text-amber-900">{item.response}</p>
          </div>
          <span className="pr-1 font-ui text-[11px] uppercase tracking-wide text-amber-700">
            patient reply
          </span>
        </div>
      )}
    </div>
  );
}

export default function Treatments() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const [patientId, setPatientId] = useState("");
  // The selected treatment THREAD's doctor — one thread per (patient, doctor).
  const [threadDoctorId, setThreadDoctorId] = useState("");
  const [patientSearch, setPatientSearch] = useState("");
  const [filterDoctorId, setFilterDoctorId] = useState("");
  const [doctorId, setDoctorId] = useState("");
  const [visitDate, setVisitDate] = useState(today());
  const [stepsPerformed, setStepsPerformed] = useState("");
  const [nextSteps, setNextSteps] = useState("");
  const [nextReportingDate, setNextReportingDate] = useState("");
  const [followupQuestion, setFollowupQuestion] = useState("");
  const [isFinal, setIsFinal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [replyMessage, setReplyMessage] = useState("");

  const { data: doctors = [] } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const doctorList = useMemo(
    () => (Array.isArray(doctors) ? doctors : doctors?.doctors ?? []),
    [doctors]
  );

  const { data: patients = [], isLoading: patientsLoading } = useQuery({
    queryKey: ["treatment-patients", branchId],
    queryFn: () => listTreatmentPatients(branchId, { status: "all" }),
    enabled: Boolean(branchId)
  });

  const { data: notesData, isLoading: notesLoading } = useQuery({
    queryKey: ["treatment-notes", patientId, branchId, threadDoctorId],
    queryFn: () => listNotes(patientId, branchId, threadDoctorId),
    enabled: Boolean(patientId && branchId)
  });

  const { data: followups = [], isLoading: followupsLoading } = useQuery({
    queryKey: ["followups", patientId, branchId, threadDoctorId],
    queryFn: () => listFollowups(patientId, branchId, threadDoctorId),
    enabled: Boolean(patientId && branchId)
  });

  // Re-run on patientId change: the Visit-history / Follow-up / Add-note cards
  // mount only AFTER a patient is selected. [data-reveal] is opacity:0 in CSS, so
  // without re-revealing those late-mounted cards they stay invisible ("can't see
  // anything", 2026-06-24).
  useEffect(() => {
    revealStagger(pageRef.current);
  }, [patientId, threadDoctorId]);

  const selectedPatient = useMemo(
    () => patients.find(
      (p) => p.patient_id === patientId && (!threadDoctorId || p.doctor_id === threadDoctorId)
    ),
    [patients, patientId, threadDoctorId]
  );

  const filteredPatients = useMemo(() => {
    const q = patientSearch.trim().toLowerCase();
    return patients.filter(
      (p) =>
        (!filterDoctorId || p.doctor_id === filterDoctorId) &&
        (!q || p.name.toLowerCase().includes(q) || (p.phone_last4 || "").includes(q))
    );
  }, [patients, patientSearch, filterDoctorId]);

  // Default the note's doctor to the patient's treating doctor.
  useEffect(() => {
    if (selectedPatient?.doctor_id) setDoctorId(selectedPatient.doctor_id);
  }, [selectedPatient?.doctor_id]);

  const resetForm = () => {
    setVisitDate(today());
    setStepsPerformed("");
    setNextSteps("");
    setNextReportingDate("");
    setFollowupQuestion("");
    setIsFinal(false);
    setEditingId(null);
  };

  // Load an existing note into the form to edit it (PATCH on save). The follow-up
  // question lives on the task, not the note, so it starts blank — re-enter it.
  const startEdit = (n) => {
    setEditingId(n.id);
    setVisitDate(n.visit_date);
    setStepsPerformed(n.steps_performed || "");
    setNextSteps(n.next_steps || "");
    setNextReportingDate(n.next_reporting_date || "");
    setIsFinal(Boolean(n.is_final));
    setFollowupQuestion("");
    document.getElementById("steps")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        branch_id: branchId,
        doctor_id: doctorId || null,
        visit_date: visitDate,
        steps_performed: stepsPerformed.trim() || null,
        next_steps: nextSteps.trim() || null,
        next_reporting_date: nextReportingDate || null,
        followup_question: followupQuestion.trim() || null,
        is_final: isFinal
      };
      // Editing an existing note → PATCH it. Otherwise, attendance auto-creates a
      // blank log for the visit; if one exists for this date with no details yet,
      // FILL it (PATCH) instead of duplicating. Else create a new note.
      const blank = (notesData?.notes ?? []).find(
        (n) => n.visit_date === visitDate && !n.steps_performed && !n.next_steps
      );
      const targetId = editingId || blank?.id;
      return targetId ? editNote(targetId, payload) : createNote(patientId, payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["treatment-notes", patientId, branchId, threadDoctorId] });
      qc.invalidateQueries({ queryKey: ["treatment-patients", branchId] });
      // B25: a note with a follow-up question enqueues a next_visit_book task —
      // refresh the follow-up thread so it appears immediately (the reply
      // mutation already does this; note create/edit didn't).
      qc.invalidateQueries({ queryKey: ["followups", patientId, branchId, threadDoctorId] });
      resetForm();
      toast.success(isFinal ? "Treatment marked complete" : "Visit note added");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Couldn't save the note")
  });

  const canSubmit =
    Boolean(patientId) && Boolean(doctorId) && Boolean(visitDate) && !save.isPending;

  const reply = useMutation({
    mutationFn: () =>
      replyToPatient(patientId, {
        branch_id: branchId,
        doctor_id: doctorId || null,
        message: replyMessage.trim()
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["followups", patientId, branchId, threadDoctorId] });
      setReplyMessage("");
      toast.success("Reply queued for the patient");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Couldn't send the reply")
  });

  const canReply =
    Boolean(patientId) && Boolean(doctorId) && Boolean(replyMessage.trim()) && !reply.isPending;

  const needsAttention = followups.some(
    (f) => (f.response && f.response.trim()) || f.status === "unreachable"
  );

  if (!branchId)
    return <p className="font-ui text-slate">No branch linked to your account yet.</p>;

  const status = notesData?.treatment_status;
  const notes = notesData?.notes ?? [];

  return (
    <div ref={pageRef} className="mx-auto max-w-3xl space-y-6">
      <div data-reveal>
        <p className="eyebrow">Care</p>
        <h1 className="section-title text-2xl">Treatment progress</h1>
      </div>

      <div data-reveal className="card space-y-3 p-6">
        <label className="label">Patients under treatment</label>
        {/* Search + doctor filter: a clinic can have 100+ patients split across
            doctors — a bare dropdown doesn't scale (Vinay 2026-07-03). */}
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="search"
            className="field min-h-[48px] flex-1"
            placeholder="Search by name or phone…"
            value={patientSearch}
            onChange={(e) => setPatientSearch(e.target.value)}
            aria-label="Search patients"
          />
          <select
            className="field min-h-[48px] sm:w-56"
            value={filterDoctorId}
            onChange={(e) => setFilterDoctorId(e.target.value)}
            aria-label="Filter by doctor"
          >
            <option value="">All doctors</option>
            {doctorList.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
        {patientsLoading ? (
          <p className="font-ui text-sm text-slate">Loading patients…</p>
        ) : filteredPatients.length === 0 ? (
          <p className="font-ui text-sm text-slate">
            {patients.length === 0 ? "No patients under treatment yet." : "No patients match."}
          </p>
        ) : (
          <ul className="divide-y divide-hairline overflow-hidden rounded-xl border border-hairline">
            {filteredPatients.map((p) => {
              const selected = p.patient_id === patientId && p.doctor_id === threadDoctorId;
              return (
                <li key={`${p.patient_id}:${p.doctor_id}`}>
                  <button
                    type="button"
                    onClick={() => {
                      setPatientId(selected ? "" : p.patient_id);
                      setThreadDoctorId(selected ? "" : p.doctor_id);
                    }}
                    className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors min-h-[56px] ${
                      selected ? "bg-teal-mint/60" : "hover:bg-teal-mint/30"
                    }`}
                    aria-expanded={selected}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-ui font-medium">
                        {p.name} <span className="text-slate">· …{p.phone_last4}</span>
                      </span>
                      <span className="block truncate font-ui text-sm text-slate">
                        {p.doctor_name || "—"}
                        {p.next_reporting_date ? ` · next ${p.next_reporting_date}` : ""}
                      </span>
                    </span>
                    <span className={p.active ? "chip-muted shrink-0" : "chip-token shrink-0"}>
                      {p.active ? "Active" : "Completed"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {patientId && (
        <>
          {/* Timeline */}
          <section data-reveal className="card overflow-hidden">
            <header className="flex items-center gap-3 border-b border-hairline bg-teal-mint/60 px-4 py-3">
              <h2 className="font-display text-lg font-semibold">Visit history</h2>
              {selectedPatient?.doctor_name && (
                <span className="font-ui text-sm text-slate">
                  Dr: {selectedPatient.doctor_name}
                </span>
              )}
              {status && (
                <span className={status === "completed" ? "chip-token" : "chip-muted"}>
                  {status === "completed" ? "Completed" : "Active"}
                </span>
              )}
            </header>
            {notesLoading ? (
              <p className="px-4 py-6 font-ui text-sm text-slate">Loading visit notes…</p>
            ) : notes.length === 0 ? (
              <p className="px-4 py-6 font-ui text-sm text-slate">No visit notes recorded yet.</p>
            ) : (
              <ol className="px-5 py-5">
                {notes.map((n, i) => (
                  <NoteCard
                    key={n.id}
                    n={n}
                    isLatest={i === notes.length - 1}
                    isLast={i === notes.length - 1}
                    onEdit={startEdit}
                  />
                ))}
              </ol>
            )}
          </section>

          {/* Follow-up thread */}
          <section data-reveal className="card overflow-hidden">
            <header className="flex items-center gap-3 border-b border-hairline bg-teal-mint/60 px-4 py-3">
              <h2 className="font-display text-lg font-semibold">Follow-up thread</h2>
              {needsAttention && (
                <span className="chip-token bg-amber-100 text-amber-900">needs attention</span>
              )}
            </header>
            {followupsLoading ? (
              <p className="px-4 py-6 font-ui text-sm text-slate">Loading follow-ups…</p>
            ) : followups.length === 0 ? (
              <p className="px-4 py-6 font-ui text-sm text-slate">
                No follow-up calls or replies yet.
              </p>
            ) : (
              <div className="divide-y divide-hairline">
                {followups.map((item) => (
                  <ThreadRow key={item.id} item={item} />
                ))}
              </div>
            )}

            <form
              className="space-y-3 border-t border-hairline px-4 py-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (canReply) reply.mutate();
              }}
            >
              <label className="label" htmlFor="reply-message">Reply to patient</label>
              <textarea
                id="reply-message"
                className="field"
                rows={2}
                value={replyMessage}
                onChange={(e) => setReplyMessage(e.target.value)}
                placeholder="Advice to relay on the next call…"
              />
              <button type="submit" disabled={!canReply} className="btn-primary w-full py-3">
                {reply.isPending ? "Sending…" : "Send reply"}
              </button>
            </form>
          </section>

          {/* Add note */}
          <form
            data-reveal
            className="card space-y-5 p-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit) save.mutate();
            }}
          >
            <div className="flex items-center gap-3">
              <h2 className="font-display text-lg font-semibold">
                {editingId ? "Edit visit note" : "Add a visit note"}
              </h2>
              {editingId && (
                <button
                  type="button"
                  onClick={resetForm}
                  className="ml-auto font-ui text-xs text-slate underline-offset-2 hover:underline"
                >
                  Cancel edit
                </button>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="visit-date">Visit date</label>
                <input
                  id="visit-date"
                  type="date"
                  className="field min-h-[56px]"
                  value={visitDate}
                  onChange={(e) => setVisitDate(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="doctor-select">Doctor</label>
                <select
                  id="doctor-select"
                  className="field min-h-[56px]"
                  value={doctorId}
                  onChange={(e) => setDoctorId(e.target.value)}
                  required
                >
                  <option value="">Select…</option>
                  {doctorList.map((d) => {
                    const id = d.id ?? d.doctor_id;
                    return (
                      <option key={id} value={id}>{d.name}</option>
                    );
                  })}
                </select>
              </div>
            </div>

            <div>
              <label className="label" htmlFor="steps">Steps performed</label>
              <textarea
                id="steps"
                className="field"
                rows={2}
                value={stepsPerformed}
                onChange={(e) => setStepsPerformed(e.target.value)}
                placeholder="scaling, root canal session 1…"
              />
            </div>

            <div>
              <label className="label" htmlFor="next">Next steps</label>
              <textarea
                id="next"
                className="field"
                rows={2}
                value={nextSteps}
                onChange={(e) => setNextSteps(e.target.value)}
                placeholder="crown fitting next visit…"
              />
            </div>

            <div>
              <label className="label" htmlFor="followup-q">
                Question to ask on the follow-up call (optional)
              </label>
              <textarea
                id="followup-q"
                className="field"
                rows={2}
                value={followupQuestion}
                onChange={(e) => setFollowupQuestion(e.target.value)}
                placeholder="e.g. Is the pain reducing? Any swelling?"
              />
              <p className="mt-1 font-ui text-xs text-slate">
                The agent asks this on the next-visit reminder call, then helps them book.
              </p>
            </div>

            <div>
              <label className="label" htmlFor="next-date">Next reporting date (optional)</label>
              <input
                id="next-date"
                type="date"
                className="field min-h-[56px]"
                value={nextReportingDate}
                onChange={(e) => setNextReportingDate(e.target.value)}
                disabled={isFinal}
              />
            </div>

            <label className="flex min-h-[56px] cursor-pointer items-center gap-3 rounded-xl border border-hairline px-4 font-ui">
              <input
                type="checkbox"
                checked={isFinal}
                onChange={(e) => {
                  setIsFinal(e.target.checked);
                  if (e.target.checked) setNextReportingDate("");
                }}
                className="h-5 w-5 accent-teal"
              />
              <span>
                <span className="font-medium">Mark treatment complete</span>
                <span className="block text-xs text-slate">
                  Closes this patient&rsquo;s treatment — no further follow-up calls.
                </span>
              </span>
            </label>

            <button type="submit" disabled={!canSubmit} className="btn-primary w-full py-3">
              {save.isPending
                ? "Saving…"
                : isFinal
                  ? "Save & mark complete"
                  : editingId
                    ? "Save changes"
                    : "Add visit note"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
