import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fetchDoctors, markUnavailable, previewAffected } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

const today = () => new Date().toISOString().slice(0, 10);

export default function Availability() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const [doctorId, setDoctorId] = useState("");
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [reason, setReason] = useState("");

  const { data: doctorsRaw, isLoading } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const doctors = (Array.isArray(doctorsRaw) ? doctorsRaw : doctorsRaw?.doctors ?? []).filter(
    (d) => !d.status || d.status === "active"
  );
  const doctor = doctors.find((d) => (d.id ?? d.doctor_id) === doctorId);

  // Preview how many booked patients this leave would cancel
  const { data: affected } = useQuery({
    queryKey: ["affected", branchId, doctorId, from, to],
    queryFn: () => previewAffected(branchId, doctorId, from, to),
    enabled: Boolean(branchId && doctorId && from && to && from <= to)
  });

  // Re-run when loading flips: on a client-side nav the first render is the
  // "Loading doctors…" early return (no pageRef), so a mount-only reveal left
  // every [data-reveal] block at its CSS opacity:0 — permanently black page
  // until reload (live 2026-07-12, FIXLOG #334).
  useEffect(() => {
    if (!isLoading) revealStagger(pageRef.current);
  }, [isLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  const mark = useMutation({
    mutationFn: () =>
      markUnavailable(branchId, doctorId, { date_from: from, date_to: to, reason: reason.trim() || null }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["affected", branchId] });
      qc.invalidateQueries({ queryKey: ["queue", branchId] });
      toast.success(
        `${doctor?.name} marked off ${r.unavailable_dates} day(s)` +
          (r.cancelled_tokens ? ` · ${r.cancelled_tokens} booking(s) cancelled, patients will be contacted` : "")
      );
      // Keep the doctor selected so the receptionist can add another range immediately
      setReason("");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not mark unavailable")
  });

  const validRange = from && to && from <= to;
  const canSubmit = doctorId && validRange && !mark.isPending;

  if (isLoading) return <p className="font-ui text-slate">Loading doctors…</p>;

  return (
    <div ref={pageRef} className="mx-auto max-w-2xl space-y-6">
      <div data-reveal>
        <p className="eyebrow">Front desk</p>
        <h1 className="section-title text-2xl">Doctor unavailable / leave</h1>
        <p className="mt-1 font-ui text-sm text-slate">
          Mark a doctor off for a date range. Those dates are blocked on the calendar and any
          existing bookings are cancelled — patients get contacted to rebook.
        </p>
      </div>

      <form
        data-reveal
        className="card space-y-5 p-6"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) mark.mutate();
        }}
      >
        <div>
          <label className="label">Doctor</label>
          <div className="grid gap-2 sm:grid-cols-2">
            {doctors.map((d) => {
              const id = d.id ?? d.doctor_id;
              return (
                <button type="button" key={id} onClick={() => setDoctorId(id)}
                  className={`rounded-xl border px-4 py-3 text-left transition ${
                    doctorId === id
                      ? "border-teal bg-teal-mint shadow-card"
                      : "border-hairline bg-surface hover:border-teal-light/60"
                  }`}>
                  <p className="font-ui font-medium">{d.name}</p>
                  <span className={d.booking_type === "token" ? "chip-token mt-1" : "chip-slot mt-1"}>
                    {d.booking_type === "token" ? "token queue" : "appointments"}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">From</label>
            <input className="field" type="date" value={from} min={today()}
              onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div>
            <label className="label">To</label>
            <input className="field" type="date" value={to} min={from}
              onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>
        {!validRange && (
          <p className="font-ui text-sm text-danger">&ldquo;To&rdquo; date must be on or after &ldquo;From&rdquo;.</p>
        )}

        <div>
          <label className="label">Reason (optional)</label>
          <input className="field" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="On leave, conference, personal…" />
        </div>

        {doctorId && affected && (
          <div className={`rounded-xl border p-4 font-ui text-sm ${
            affected.count > 0 ? "border-gold/60 bg-gold-soft text-gold-ink" : "border-hairline bg-teal-mint/60 text-ink-soft"
          }`}>
            {affected.count > 0
              ? `${affected.count} existing booking(s) in this range will be cancelled and those patients contacted to rebook.`
              : "No existing bookings in this range — clean block."}
          </div>
        )}

        <button type="submit" disabled={!canSubmit} className="btn-primary w-full py-3">
          {mark.isPending ? "Marking…" : "Mark unavailable"}
        </button>
        <p className="text-center font-ui text-xs text-slate">
          After saving, you can pick new dates for the same doctor and mark again.
        </p>
      </form>
    </div>
  );
}
